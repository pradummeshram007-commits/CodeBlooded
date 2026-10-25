"""Bundle ingestion: manifest, company context, contracts (+ segmentation).

Nothing here assumes relationships between documents: the manifest only supplies file
paths and titles. Document kind and IDs come from each document's own text.

Operational inputs (events, ledger, holidays, clock) get loader functions and tables
for Norns/Heimdall, but ``ingest_bundle`` only registers them as resources.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from odin.config import OdinConfig
from odin.ingest.segmenter import DECORATION_RE, Segmentation, segment
from odin.state.models import Checkpoint, Clause, Document, Event, Flag, Holiday, LedgerEntry, Resource
from odin.state.store import StateStore

EXTERNAL_ID_RE = re.compile(r"(?:CONTRACT|DOCUMENT)\s+ID:\s*([A-Z0-9][A-Z0-9-]+)")
SELF_SUPPLEMENT_RE = re.compile(
    r"\bthis\b[^.]{0,80}?\b(is incorporated (?:by reference )?into|supplements|forms part of)\b", re.I
)
CONTRACT_ID_IN_TEXT_RE = re.compile(r"\bQH-[A-Z0-9]+-\d{4}-[A-Z0-9]+\b")

RESOURCE_KINDS = {
    "company/context.txt": "company_context",
    "data/payments_ledger.csv": "ledger",
    "data/holidays.csv": "holidays",
}


def read_text_exact(path: Path) -> str:
    """Decode without newline translation so offsets match the file byte-for-byte text."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(bundle_dir: Path) -> list[dict[str, str]]:
    data = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    return list(data.get("files", []))


def text_title(text: str) -> str | None:
    """The upper-case title banner at the top of a document."""
    parts: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or DECORATION_RE.match(line):
            if parts:
                break
            continue
        letters = [c for c in s if c.isalpha()]
        if letters and all(c.isupper() for c in letters) and not EXTERNAL_ID_RE.search(s):
            parts.append(s)
            continue
        break
    return " ".join(parts) or None


def classify_kind(title: str | None, preamble: str) -> str:
    t = (title or "").upper()
    if "STANDARD TERMS" in t:
        return "standard_terms"
    if "AMENDMENT" in t:
        return "amendment"
    if "ADDENDUM" in t:
        return "addendum"
    if SELF_SUPPLEMENT_RE.search(preamble):
        return "addendum"   # e.g. an SLA that declares itself incorporated into another agreement
    return "contract"


@dataclass
class DocIngest:
    doc_id: str
    status: str                  # new | changed | unchanged
    clauses: int
    method: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class IngestReport:
    documents: list[DocIngest] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)

    @property
    def changed_doc_ids(self) -> list[str]:
        return [d.doc_id for d in self.documents if d.status != "unchanged"]


def _clauses_from(seg: Segmentation) -> list[Clause]:
    return [
        Clause(
            clause_id=c.clause_id, doc_id=c.doc_id, number=c.number, ref=c.ref, heading=c.heading, text=c.text,
            char_start=c.char_start, char_end=c.char_end, level=c.level, parent_id=c.parent_id,
            ordinal=c.ordinal, kind=c.kind,
        )
        for c in seg.clauses
    ]


def ingest_document(store: StateStore, path: Path, rel_path: str, title: str | None, source: str = "bundle") -> DocIngest:
    doc_id = path.stem
    text = read_text_exact(path)
    seg = segment(doc_id, text)
    preamble = next((c.text for c in seg.clauses if c.kind == "preamble"), text[:2000])
    banner = text_title(text)
    m = EXTERNAL_ID_RE.search(text[:2000])
    doc = Document(
        doc_id=doc_id,
        title=title or banner or doc_id,
        text_title=banner,
        path=rel_path,
        sha256=sha256_file(path),
        kind=classify_kind(banner, preamble),  # type: ignore[arg-type]
        external_id=m.group(1) if m else None,
        source=source,
    )
    is_new = store.get_document(doc_id) is None
    changed = store.upsert_document(doc)
    if changed or not store.list_clauses(doc_id):
        with store.transaction():
            store.replace_clauses(doc_id, _clauses_from(seg))
            store.supersede_flags(doc_id, raised_by="ingest")
            if seg.unparseable:
                store.add_flag(
                    Flag(
                        doc_id=doc_id,
                        type="unparseable",
                        description="; ".join(seg.warnings) or "numbering scheme not recognised; paragraph chunks used",
                        raised_by="ingest",
                    )
                )
    status = "new" if is_new else ("changed" if changed else "unchanged")
    return DocIngest(doc_id, status, len(seg.clauses), seg.method, seg.warnings)


def ingest_bundle(store: StateStore, cfg: OdinConfig, source: str = "bundle") -> IngestReport:
    """Register every manifest file; segment and store every contract text.

    Contract .txt files present on disk but missing from the manifest (e.g. delivered by
    a later drop) are ingested too, titled from their own banner.
    """
    bundle = cfg.paths.bundle_dir
    report = IngestReport()
    manifest = load_manifest(bundle)
    titles = {f["path"]: f.get("title") for f in manifest}

    store.upsert_resource(Resource(path="manifest.json", kind="manifest", title="Bundle manifest",
                                   sha256=sha256_file(bundle / "manifest.json")))
    clock = cfg.paths.pack_dir / "clock.json"
    if clock.exists():
        store.upsert_resource(Resource(path="../clock.json", kind="clock", title="Simulated clock", sha256=sha256_file(clock)))
    for entry in manifest:
        rel = entry["path"]
        full = bundle / rel
        if rel.startswith("contracts/") or not full.exists():
            continue
        kind = RESOURCE_KINDS.get(rel) or ("events" if rel.startswith("events/") else "data")
        store.upsert_resource(Resource(path=rel, kind=kind, title=entry.get("title"), sha256=sha256_file(full)))
        report.resources.append(rel)

    contract_paths = {p.relative_to(bundle).as_posix(): p for p in sorted((bundle / "contracts").glob("*.txt"))}
    ordered = [r for r in titles if r in contract_paths] + [r for r in contract_paths if r not in titles]
    for rel in ordered:
        report.documents.append(ingest_document(store, contract_paths[rel], rel, titles.get(rel), source))
    return report


def document_text(cfg: OdinConfig, doc: Document) -> str:
    return read_text_exact(cfg.paths.bundle_dir / doc.path)


def registry(store: StateStore) -> list[dict[str, Any]]:
    """What each document says about itself, used to resolve references in other documents."""
    out = []
    for d in store.list_documents():
        out.append({
            "doc_id": d.doc_id,
            "file": Path(d.path).name,
            "kind": d.kind,
            "external_id": d.external_id,
            "title_in_text": d.text_title,
        })
    return out


# --------------------------------------------------------------------------- later-agent inputs


def load_events(path: Path, drop: str) -> list[Event]:
    """Parse a JSONL drop. Malformed lines are kept with parse_error set, never dropped silently."""
    events: list[Event] = []
    for n, line in enumerate(read_text_exact(path).splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError("line is not a JSON object")
            events.append(Event(
                event_id=obj.get("event_id"), drop=drop, line_no=n, timestamp=obj.get("timestamp"),
                channel=obj.get("channel"), from_party=obj.get("from"), to_party=obj.get("to"),
                subject=obj.get("subject"), body=obj.get("body"), raw=line,
            ))
        except (json.JSONDecodeError, ValueError) as exc:
            events.append(Event(event_id=None, drop=drop, line_no=n, raw=line, parse_error=str(exc)))
    return events


def load_ledger(path: Path) -> list[LedgerEntry]:
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for n, r in enumerate(csv.DictReader(fh), start=2):
            m = CONTRACT_ID_IN_TEXT_RE.search(r.get("reference", ""))
            rows.append(LedgerEntry(
                line_no=n, date=r["date"], from_party=r["from"], to_party=r["to"], amount=float(r["amount"]),
                reference=r["reference"], status=r["status"], contract_id=m.group(0) if m else None,
            ))
    return rows


def load_holidays(path: Path) -> list[Holiday]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [Holiday(date=r["date"], name=r["name"], observed_by=r["observed_by"]) for r in csv.DictReader(fh)]


def load_clock(path: Path) -> list[Checkpoint]:
    data = json.loads(path.read_text(encoding="utf-8"))
    points = [Checkpoint(idx=0, date=data["start_date"], label="start")]
    points += [Checkpoint(idx=i, date=d, label="checkpoint") for i, d in enumerate(data.get("checkpoints", []), start=1)]
    return points

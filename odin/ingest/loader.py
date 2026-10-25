"""Ingestion helpers shared by the upload pipeline and bundle seeding.

Nothing here assumes relationships between documents: the manifest only supplies file
paths and titles. Document kind and IDs come from each document's own text.

Parsers for the operational inputs (ledger, holidays, clock, events) live here too; the
bundle seeding (``odin/ingest/bundle.py``) loads ledger, holidays and clock into tables and
leaves the event drops unparsed for Heimdall.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from odin.config import OdinConfig
from odin.ingest.segmenter import DECORATION_RE, Segmentation
from odin.state.models import Checkpoint, Clause, Document, Event, Holiday, LedgerEntry
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


def clauses_from(seg: Segmentation) -> list[Clause]:
    return [
        Clause(
            clause_id=c.clause_id, doc_id=c.doc_id, number=c.number, ref=c.ref, heading=c.heading, text=c.text,
            char_start=c.char_start, char_end=c.char_end, level=c.level, parent_id=c.parent_id,
            ordinal=c.ordinal, kind=c.kind,
        )
        for c in seg.clauses
    ]


def document_text(cfg: OdinConfig, doc: Document) -> str:
    """The text clause offsets index into: stored in the database since step 2A, else the bundle file."""
    if doc.text is not None:
        return doc.text
    return read_text_exact(cfg.paths.bundle_dir / doc.path)


def registry(store: StateStore) -> list[dict[str, Any]]:
    """What each document says about itself, used to resolve references in other documents."""
    out = []
    # Sorted by doc_id, not by ingest time, so prompts (and their LLM cache keys) do not depend on upload order.
    for d in sorted(store.list_documents(include_text=False), key=lambda d: d.doc_id):
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

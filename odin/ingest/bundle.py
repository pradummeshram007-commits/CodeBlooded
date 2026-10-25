"""Seed the dev-pack bundle into the state store and the file store. Idempotent.

* ``contracts/X.txt`` + ``contracts/X.pdf``: ``ingest_file`` each, .txt first, so every pair
  becomes ONE document (the .txt is the text source, the .pdf the viewable original).
* ``company/context.txt``: a resource row with its full text, plus a stored copy.
* ``data/payments_ledger.csv`` -> ``ledger_entries``, ``data/holidays.csv`` -> ``holidays``,
  ``../clock.json`` -> ``clock_checkpoints`` (plus stored copies).
* ``events/*.jsonl``: stored copies and resource rows only. They are NOT parsed here;
  Heimdall reads them drop by drop.
* ``manifest.json``: resource row + stored copy. The manifest only supplies paths and
  titles; relationships between documents come from the text (Thor).

Nothing is re-uploaded or re-extracted when a file's sha256 is unchanged.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from odin.config import OdinConfig
from odin.ingest.loader import RESOURCE_KINDS, load_clock, load_holidays, load_ledger, load_manifest
from odin.ingest.upload import UploadResult, ingest_file
from odin.state.files import FileStore, safe_filename
from odin.state.models import Resource
from odin.state.store import StateStore

RESOURCE_MIME = {
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
}
_STATUS = {"created": "new", "updated": "changed", "attached": "changed", "duplicate": "unchanged"}


@dataclass
class DocIngest:
    doc_id: str
    status: str                  # new | changed | unchanged (of the document's text source)
    clauses: int
    method: str                  # parse status: parsed | fallback | unparseable
    warnings: list[str] = field(default_factory=list)
    original: str | None = None  # file name of the viewable original


@dataclass
class IngestReport:
    documents: list[DocIngest] = field(default_factory=list)
    uploads: list[UploadResult] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    tables: dict[str, int] = field(default_factory=dict)   # rows inserted by this run

    @property
    def changed_doc_ids(self) -> list[str]:
        return [d.doc_id for d in self.documents if d.status != "unchanged"]


def resource_object_path(rel: str, sha256: str) -> str:
    parent = Path(rel).parent.as_posix().strip("./")
    return "/".join(p for p in ("_bundle", parent, sha256, safe_filename(Path(rel).name)) if p)


def _register_resource(store: StateStore, files: FileStore, full: Path, rel: str, kind: str, title: str | None,
                       *, keep_text: bool = False) -> bool:
    data = full.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    old = store.get_resource(rel)
    path = resource_object_path(rel, sha)
    if not (old and old.sha256 == sha and old.storage_path == path):
        files.upload(path, data, RESOURCE_MIME.get(full.suffix.lower(), "application/octet-stream"))
    return store.upsert_resource(Resource(
        path=rel, kind=kind, title=title, sha256=sha, storage_path=path,
        mime_type=RESOURCE_MIME.get(full.suffix.lower()), size_bytes=len(data),
        text=data.decode("utf-8") if keep_text else None,
    ))


def ingest_bundle(
    store: StateStore,
    cfg: OdinConfig,
    files: FileStore | None = None,
    *,
    include_pdfs: bool = True,
    load_tables: bool = True,
    source: str = "bundle",
    progress: Callable[[str], None] | None = None,
) -> IngestReport:
    """Seed every bundle file (see module docstring). Contracts are not extracted here (run Thor)."""
    if files is None:
        from odin.state.backend import open_file_store

        files = open_file_store(cfg)
    say = progress or (lambda _m: None)
    bundle = cfg.paths.bundle_dir
    report = IngestReport()
    manifest = load_manifest(bundle)
    titles = {f["path"]: f.get("title") for f in manifest}
    files.ensure_bucket()

    # Contracts: manifest order first, then any .txt on disk the manifest does not list (a later drop).
    contracts = bundle / "contracts"
    txts = {p.relative_to(bundle).as_posix(): p for p in sorted(contracts.glob("*.txt"))}
    ordered = [r for r in titles if r in txts] + [r for r in txts if r not in titles]
    for rel in ordered:
        txt = txts[rel]
        res = ingest_file(txt.read_bytes(), txt.name, store=store, files=files, cfg=cfg, extract=False,
                          title=titles.get(rel), rel_path=rel, source=source)
        report.uploads.append(res)
        entry = DocIngest(res.doc_id, _STATUS[res.outcome], res.clauses or len(store.list_clauses(res.doc_id)),
                          res.parse_status or "", list(res.warnings))
        pdf = txt.with_suffix(".pdf")
        if include_pdfs and pdf.exists():
            pres = ingest_file(pdf.read_bytes(), pdf.name, store=store, files=files, cfg=cfg, extract=False, source=source)
            report.uploads.append(pres)
            entry.warnings += pres.warnings
        doc = store.get_document(res.doc_id, include_text=False)
        entry.original = doc.original_filename if doc else None
        report.documents.append(entry)
        say(f"{res.doc_id}: {res.outcome}" + (f", original {entry.original}" if entry.original else ""))

    # Everything else the bundle ships.
    if _register_resource(store, files, bundle / "manifest.json", "manifest.json", "manifest", "Bundle manifest"):
        report.resources.append("manifest.json")
    clock = cfg.paths.pack_dir / "clock.json"
    if clock.exists():
        if _register_resource(store, files, clock, "../clock.json", "clock", "Simulated clock"):
            report.resources.append("../clock.json")
        if load_tables:
            report.tables["clock_checkpoints"] = store.add_checkpoints(load_clock(clock))
    for entry_m in manifest:
        rel = entry_m["path"]
        full = bundle / rel
        if rel.startswith("contracts/") or not full.exists():
            continue
        kind = RESOURCE_KINDS.get(rel) or ("events" if rel.startswith("events/") else "data")
        if _register_resource(store, files, full, rel, kind, entry_m.get("title"), keep_text=kind == "company_context"):
            report.resources.append(rel)
        if load_tables and kind == "ledger":
            report.tables["ledger_entries"] = store.add_ledger(load_ledger(full))
        elif load_tables and kind == "holidays":
            report.tables["holidays"] = store.add_holidays(load_holidays(full))
    return report

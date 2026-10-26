"""Shared state store: one interface, two backends.

* ``SQLiteStateStore``: ``state/odin.db``. The default, and the offline fallback.
* ``PostgresStateStore`` (``odin/state/postgres.py``): Supabase Postgres. Its schema
  comes from ``supabase/migrations/*.sql``; the SQLite schema below mirrors it table for
  table (``tests/test_migrations.py`` keeps the two in step).

Every agent goes through these methods; no SQL lives outside ``odin/state``. The SQL is
written once, in the subset both engines accept (``ON CONFLICT``, ``TRUE``/``FALSE``,
``COALESCE``); a backend only supplies the connection, placeholders and type round-trips.

Writes are idempotent where the spec requires it: re-ingesting an unchanged document is a
no-op, relations are de-duplicated by a unique index, and extractions are versioned
instead of overwritten. Multi-row writes run inside ``transaction()`` so a failure never
leaves half a document behind.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from odin.state.models import (
    Checkpoint,
    Citation,
    Clause,
    ClockEvent,
    ClockState,
    DocRelation,
    Document,
    DocumentFile,
    Event,
    ExposureItem,
    Extraction,
    Flag,
    HeimdallAlert,
    HeimdallEvent,
    HeimdallTask,
    Holiday,
    LedgerEntry,
    LokiFinding,
    Message,
    ObligationInstance,
    ObligationRule,
    Resource,
    TimelineSnapshot,
    TraceEntry,
    Workstream,
    Writeup,
    utcnow,
)

SCHEMA_VERSION = 4

# Every table, in dependency order (export, row counts, test cleanup).
TABLES = (
    "documents", "document_files", "clauses", "extractions", "citations", "flags", "doc_relations", "messages",
    "workstreams", "trace", "resources", "events", "ledger_entries", "holidays", "clock_checkpoints",
    "obligation_rules", "obligation_instances", "clock_state", "clock_history", "timeline_snapshots",
    "exposure_items", "writeups", "loki_findings", "heimdall_events", "heimdall_alerts", "heimdall_tasks",
)

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    text_title TEXT,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('contract','standard_terms','amendment','addendum')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','extracting','complete','partial','failed')),
    status_reason TEXT,
    coverage REAL,
    external_id TEXT,
    source TEXT NOT NULL DEFAULT 'bundle',
    extracted_sha256 TEXT,
    text TEXT,
    text_source TEXT CHECK (text_source IN ('txt','pdf_extracted')),
    parse_status TEXT CHECK (parse_status IN ('parsed','fallback','unparseable')),
    storage_path TEXT,
    original_filename TEXT,
    mime_type TEXT,
    uploaded_at TEXT,
    ingested_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_documents_sha ON documents(sha256);

CREATE TABLE IF NOT EXISTS document_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id),
    role TEXT NOT NULL CHECK (role IN ('text_source','original','attachment')),
    sha256 TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    similarity REAL,
    uploaded_at TEXT NOT NULL,
    UNIQUE (doc_id, sha256)
);
CREATE INDEX IF NOT EXISTS ix_document_files_sha ON document_files(sha256);

CREATE TABLE IF NOT EXISTS clauses (
    clause_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id),
    number TEXT NOT NULL,
    ref TEXT NOT NULL,
    heading TEXT,
    text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    level INTEGER NOT NULL DEFAULT 1,
    parent_id TEXT,
    ordinal INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'clause'
);
CREATE INDEX IF NOT EXISTS ix_clauses_doc ON clauses(doc_id, ordinal);

CREATE TABLE IF NOT EXISTS extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id),
    field_type TEXT NOT NULL,
    field_key TEXT NOT NULL,
    value TEXT,
    readings TEXT NOT NULL DEFAULT '[]',
    raw_text TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    status TEXT NOT NULL CHECK (status IN ('extracted','ambiguous','missing','contradictory')),
    source_kind TEXT NOT NULL DEFAULT 'sourced' CHECK (source_kind IN ('sourced','analysis')),
    agent TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    is_current INTEGER NOT NULL DEFAULT 1,
    supersedes_id INTEGER REFERENCES extractions(id),
    run_id TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_extractions_doc ON extractions(doc_id, is_current);
CREATE INDEX IF NOT EXISTS ix_extractions_key ON extractions(doc_id, agent, field_key, version);

CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    extraction_id INTEGER REFERENCES extractions(id),
    doc_id TEXT NOT NULL,
    clause_id TEXT,
    clause_ref TEXT,
    quote TEXT NOT NULL,
    llm_quote TEXT,
    llm_clause_id TEXT,
    char_start INTEGER,
    char_end INTEGER,
    verified INTEGER NOT NULL DEFAULT 0,
    match_method TEXT NOT NULL DEFAULT 'none',
    source_type TEXT NOT NULL DEFAULT 'clause'
);
CREATE INDEX IF NOT EXISTS ix_citations_extraction ON citations(extraction_id);
CREATE INDEX IF NOT EXISTS ix_citations_clause ON citations(clause_id);

CREATE TABLE IF NOT EXISTS flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT,
    clause_id TEXT,
    type TEXT NOT NULL CHECK (type IN ('ambiguous','missing','contradictory','unparseable','cross_reference','unverified_citation')),
    description TEXT NOT NULL,
    raised_by TEXT NOT NULL,
    extraction_id INTEGER REFERENCES extractions(id),
    evidence TEXT,
    evidence_verified INTEGER,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','superseded')),
    run_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_flags_doc ON flags(doc_id, status);

CREATE TABLE IF NOT EXISTS doc_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_doc TEXT NOT NULL,
    to_doc TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('incorporates','amends','supersedes','references','conflicts')),
    clause_id TEXT,
    citation TEXT NOT NULL DEFAULT '{}',
    extraction_id INTEGER REFERENCES extractions(id),
    raised_by TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_relations ON doc_relations(from_doc, to_doc, type, COALESCE(clause_id, ''), raised_by);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('clarification_request','clarification_response','claim','verification','ruling','alert')),
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','done','failed')),
    in_reply_to INTEGER REFERENCES messages(id),
    workstream_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_inbox ON messages(to_agent, status, type);

CREATE TABLE IF NOT EXISTS workstreams (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    members TEXT NOT NULL DEFAULT '[]',
    agent_status TEXT NOT NULL DEFAULT '{}',
    notes TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trace (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    run_id TEXT,
    agent TEXT NOT NULL,
    action TEXT NOT NULL,
    input_ref TEXT,
    output_ref TEXT,
    tokens INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_trace_run ON trace(run_id, agent);

-- Inputs for the later agents (Norns / Heimdall / Tyr). Filled by odin.ingest.loader.
CREATE TABLE IF NOT EXISTS resources (
    path TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT,
    sha256 TEXT NOT NULL,
    storage_path TEXT,
    mime_type TEXT,
    size_bytes INTEGER,
    text TEXT,
    loaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT,
    drop_name TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    timestamp TEXT,
    channel TEXT,
    from_party TEXT,
    to_party TEXT,
    subject TEXT,
    body TEXT,
    raw TEXT NOT NULL,
    parse_error TEXT,
    processed_by TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_events_line ON events(drop_name, line_no);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    line_no INTEGER NOT NULL UNIQUE,
    date TEXT NOT NULL,
    from_party TEXT NOT NULL,
    to_party TEXT NOT NULL,
    amount REAL NOT NULL,
    reference TEXT NOT NULL,
    status TEXT NOT NULL,
    contract_id TEXT
);

CREATE TABLE IF NOT EXISTS holidays (
    date TEXT NOT NULL,
    name TEXT NOT NULL,
    observed_by TEXT NOT NULL,
    PRIMARY KEY (date, observed_by)
);

CREATE TABLE IF NOT EXISTS clock_checkpoints (
    idx INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    label TEXT NOT NULL
);

-- Norns (supabase/migrations/002_norns.sql)
CREATE TABLE IF NOT EXISTS obligation_rules (
    rule_id TEXT PRIMARY KEY,
    contract TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('payment','notice','renewal','report','cure','penalty_trigger','credit')),
    name TEXT NOT NULL,
    payer TEXT,
    payee TEXT,
    anchor TEXT NOT NULL,
    anchor_date TEXT,
    offset_amount INTEGER,
    offset_unit TEXT,
    offset_direction TEXT,
    day_type TEXT CHECK (day_type IN ('business','calendar','unspecified')),
    recurrence TEXT,
    amount TEXT,
    formula TEXT,
    currency TEXT,
    escalations TEXT NOT NULL DEFAULT '[]',
    caps TEXT NOT NULL DEFAULT '[]',
    conditions TEXT NOT NULL DEFAULT '[]',
    valid_from TEXT,
    valid_to TEXT,
    citations TEXT NOT NULL DEFAULT '[]',
    flags TEXT NOT NULL DEFAULT '[]',
    source_kind TEXT NOT NULL DEFAULT 'analysis',
    built_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_obligation_rules_contract ON obligation_rules(contract, kind);

CREATE TABLE IF NOT EXISTS obligation_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of TEXT NOT NULL,
    instance_key TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    contract TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    period TEXT,
    anchor_date TEXT,
    due_date TEXT,
    due_date_calendar TEXT,
    due_date_business TEXT,
    day_type TEXT,
    amount TEXT,
    currency TEXT,
    payer TEXT,
    payee TEXT,
    status TEXT NOT NULL CHECK (status IN ('paid_on_time','paid_late','partial','unpaid','upcoming','met','missed','triggered')),
    paid_amount TEXT,
    paid_date TEXT,
    ledger_lines TEXT NOT NULL DEFAULT '[]',
    days_remaining INTEGER,
    severity TEXT,
    flags TEXT NOT NULL DEFAULT '[]',
    citations TEXT NOT NULL DEFAULT '[]',
    UNIQUE (as_of, instance_key)
);
CREATE INDEX IF NOT EXISTS ix_obligation_instances_asof ON obligation_instances(as_of, contract);

CREATE TABLE IF NOT EXISTS clock_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_as_of TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clock_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    from_as_of TEXT,
    to_as_of TEXT NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS timeline_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of TEXT NOT NULL,
    created_at TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '{}',
    chart_data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_timeline_snapshots_asof ON timeline_snapshots(as_of, id);

CREATE TABLE IF NOT EXISTS exposure_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of TEXT NOT NULL,
    scenario TEXT NOT NULL CHECK (scenario IN ('worst_case','on_time')),
    contract TEXT NOT NULL,
    category TEXT NOT NULL,
    amount TEXT,
    status TEXT NOT NULL CHECK (status IN ('quantified','unquantified')),
    accrues_on TEXT,
    description TEXT NOT NULL,
    formula TEXT,
    inputs TEXT NOT NULL DEFAULT '{}',
    citations TEXT NOT NULL DEFAULT '[]',
    source_kind TEXT NOT NULL DEFAULT 'analysis',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_exposure_items_asof ON exposure_items(as_of, scenario);

CREATE TABLE IF NOT EXISTS writeups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of TEXT NOT NULL,
    label TEXT NOT NULL,
    generated_by TEXT NOT NULL CHECK (generated_by IN ('llm','template')),
    text TEXT NOT NULL,
    model TEXT,
    prompt_hash TEXT,
    check_passed INTEGER,
    meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_writeups_asof ON writeups(as_of, id);

-- Loki (supabase/migrations/003_loki.sql)
CREATE TABLE IF NOT EXISTS loki_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    run_id TEXT,
    model TEXT,
    source_kind TEXT NOT NULL DEFAULT 'analysis',
    type TEXT CHECK (type IN ('ambiguity','one_sided','hidden_liability')),
    title TEXT NOT NULL,
    exploited_by TEXT,
    citations TEXT NOT NULL DEFAULT '[]',
    readings TEXT NOT NULL DEFAULT '[]',
    attack_path TEXT NOT NULL DEFAULT '[]',
    severity TEXT CHECK (severity IN ('critical','high','medium','low')),
    severity_reason TEXT NOT NULL DEFAULT '',
    likelihood TEXT CHECK (likelihood IN ('high','medium','low')),
    likelihood_reason TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    impact TEXT NOT NULL DEFAULT '"unquantified"',
    status TEXT NOT NULL CHECK (status IN ('accepted','rejected')),
    rejection_reason TEXT,
    part TEXT,
    rank INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_loki_findings_doc ON loki_findings(doc_id, as_of, status);

-- Heimdall (supabase/migrations/004_heimdall.sql)
CREATE TABLE IF NOT EXISTS heimdall_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of TEXT NOT NULL,
    drop_name TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    event_id TEXT,
    raw TEXT NOT NULL,
    event_date TEXT,
    channel TEXT,
    sender TEXT,
    recipient TEXT,
    subject TEXT,
    status TEXT NOT NULL CHECK (status IN ('mapped','unmapped','noise','unparseable')),
    status_reason TEXT,
    type TEXT,
    doc_ids TEXT NOT NULL DEFAULT '[]',
    clause_ids TEXT NOT NULL DEFAULT '[]',
    fact TEXT,
    is_noise INTEGER NOT NULL DEFAULT 0,
    noise_reason TEXT,
    mapped_by TEXT CHECK (mapped_by IN ('code','llm')),
    confidence REAL,
    potential_breach INTEGER NOT NULL DEFAULT 0,
    breach_reason TEXT,
    exposure TEXT NOT NULL DEFAULT '{}',
    run_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (as_of, drop_name, line_no)
);

CREATE TABLE IF NOT EXISTS heimdall_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of TEXT NOT NULL,
    alert_key TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('critical','high','medium','low')),
    kind TEXT NOT NULL,
    contract TEXT,
    clause_id TEXT,
    due_date TEXT,
    message TEXT NOT NULL,
    citation TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL CHECK (source IN ('norns','event')),
    event_id TEXT,
    instance_key TEXT,
    run_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (as_of, alert_key)
);

CREATE TABLE IF NOT EXISTS heimdall_tasks (
    as_of TEXT NOT NULL,
    task_id TEXT NOT NULL,
    title TEXT NOT NULL,
    contract TEXT NOT NULL,
    kind TEXT NOT NULL,
    period TEXT,
    due_date TEXT,
    amount TEXT,
    citation TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('Not Complete','In Progress','Completed')),
    status_source TEXT NOT NULL CHECK (status_source IN ('norns','user')),
    norns_status TEXT,
    fact TEXT,
    payer TEXT,
    payee TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (as_of, task_id)
);
"""

# Columns added after the first SQLite release; older state/odin.db files are upgraded in place.
_SQLITE_ADDED_COLUMNS = {
    "documents": [
        ("text", "TEXT"),
        ("text_source", "TEXT CHECK (text_source IN ('txt','pdf_extracted'))"),
        ("parse_status", "TEXT CHECK (parse_status IN ('parsed','fallback','unparseable'))"),
        ("storage_path", "TEXT"),
        ("original_filename", "TEXT"),
        ("mime_type", "TEXT"),
        ("uploaded_at", "TEXT"),
    ],
    "resources": [("storage_path", "TEXT"), ("mime_type", "TEXT"), ("size_bytes", "INTEGER"), ("text", "TEXT")],
}
# Renamed in step 2A (they were never filled before): ledger -> ledger_entries, checkpoints -> clock_checkpoints.
_SQLITE_RETIRED_TABLES = ("ledger", "checkpoints")

_JSON_COLUMNS = {
    "extractions": ("value", "readings"),
    "doc_relations": ("citation",),
    "messages": ("payload",),
    "workstreams": ("members", "agent_status"),
    "trace": ("meta",),
    "events": ("processed_by",),
    "obligation_rules": ("recurrence", "escalations", "caps", "conditions", "citations", "flags"),
    "obligation_instances": ("ledger_lines", "flags", "citations"),
    "timeline_snapshots": ("summary", "chart_data"),
    "exposure_items": ("inputs", "citations"),
    "writeups": ("meta",),
    "loki_findings": ("citations", "readings", "attack_path", "impact", "notes"),
    "heimdall_events": ("doc_ids", "clause_ids", "fact", "exposure"),
    "heimdall_alerts": ("citation",),
    "heimdall_tasks": ("citation", "fact"),
}
_BOOL_COLUMNS = {
    "extractions": ("is_current",),
    "citations": ("verified",),
    "flags": ("evidence_verified",),
    "doc_relations": ("verified",),
    "writeups": ("check_passed",),
    "heimdall_events": ("is_noise", "potential_breach"),
}
# Money columns: stored as numeric (Postgres) / text (SQLite), always read back as Decimal.
_DECIMAL_COLUMNS = {
    "obligation_rules": ("amount",),
    "obligation_instances": ("amount", "paid_amount"),
    "exposure_items": ("amount",),
    "heimdall_tasks": ("amount",),
}
_DOCUMENT_COLUMNS = tuple(Document.model_fields)
_DOCUMENT_COLUMNS_NO_TEXT = ", ".join(c for c in _DOCUMENT_COLUMNS if c != "text")
# Columns update_document() may change directly (everything else goes through upsert / set_document_status).
_DOCUMENT_UPDATABLE = {"storage_path", "original_filename", "mime_type", "uploaded_at", "parse_status", "title"}


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)


def _plain(value: Any) -> Any:
    """Driver values -> the plain types the pydantic models use (ISO strings, floats)."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.isoformat(timespec="microseconds" if value.microsecond else "seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


class StateStore:
    """Backend-neutral store. Subclasses implement the five plumbing methods at the bottom."""

    backend = "base"
    json_native = False          # True when the driver already returns parsed JSON (Postgres jsonb)

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._depth = 0

    # ------------------------------------------------------------------ plumbing helpers

    def _row(self, table: str, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        raw = dict(row)
        d = {k: _plain(v) for k, v in raw.items()}
        for col in _DECIMAL_COLUMNS.get(table, ()):
            if raw.get(col) is not None:
                d[col] = Decimal(str(raw[col]))
        for col in _JSON_COLUMNS.get(table, ()):
            if isinstance(d.get(col), str) and not self.json_native:
                d[col] = json.loads(d[col])
        for col in _BOOL_COLUMNS.get(table, ()):
            if d.get(col) is not None:
                d[col] = bool(d[col])
        if table == "events" and "drop_name" in d:
            d["drop"] = d.pop("drop_name")
        return d

    def _rows(self, table: str, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self._row(table, r) for r in rows]  # type: ignore[misc]

    def _one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    @staticmethod
    def _prepare(table: str, data: dict[str, Any]) -> dict[str, Any]:
        data = dict(data)
        for col in _JSON_COLUMNS.get(table, ()):
            if col in data:
                data[col] = _dumps(data[col])
        for col in _DECIMAL_COLUMNS.get(table, ()):
            if data.get(col) is not None:
                data[col] = str(data[col])           # exact: numeric in Postgres, text in SQLite
        return data

    def _insert(self, table: str, data: dict[str, Any], *, ignore_conflicts: bool = False,
                returning_id: bool = True) -> int | None:
        data = self._prepare(table, data)
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        sql = f"INSERT INTO {table} ({cols}) VALUES ({marks})" + (" ON CONFLICT DO NOTHING" if ignore_conflicts else "")
        if returning_id:
            return self._insert_id(sql, tuple(data.values()))
        self._write(sql, tuple(data.values()))
        return None

    def _insert_many(self, table: str, rows: Iterable[dict[str, Any]], *, ignore_conflicts: bool = False) -> int:
        prepared = [self._prepare(table, r) for r in rows]
        if not prepared:
            return 0
        cols = list(prepared[0])
        sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
               + (" ON CONFLICT DO NOTHING" if ignore_conflicts else ""))
        return self._write_many(sql, [tuple(r[c] for c in cols) for r in prepared])

    # ------------------------------------------------------------------ documents

    def upsert_document(self, doc: Document) -> bool:
        """Insert or update a document. Returns True when it is new or its sha256 changed."""
        existing = self.get_document(doc.doc_id, include_text=False)
        if existing is None:
            self._insert("documents", doc.model_dump(), returning_id=False)
            return True
        files = (doc.storage_path, doc.original_filename, doc.mime_type, doc.uploaded_at)
        if existing.sha256 == doc.sha256:
            # Unchanged text: keep extraction status; refresh metadata, fill in what was missing.
            self._write(
                """UPDATE documents SET title=?, text_title=?, path=?, kind=?, external_id=?,
                   text=COALESCE(?, text), text_source=COALESCE(?, text_source), parse_status=COALESCE(?, parse_status),
                   storage_path=COALESCE(?, storage_path), original_filename=COALESCE(?, original_filename),
                   mime_type=COALESCE(?, mime_type), uploaded_at=COALESCE(?, uploaded_at) WHERE doc_id=?""",
                (doc.title, doc.text_title, doc.path, doc.kind, doc.external_id, doc.text, doc.text_source,
                 doc.parse_status, *files, doc.doc_id),
            )
            return False
        self._write(
            """UPDATE documents SET title=?, text_title=?, path=?, sha256=?, kind=?, external_id=?, source=?,
               text=?, text_source=?, parse_status=?,
               storage_path=COALESCE(?, storage_path), original_filename=COALESCE(?, original_filename),
               mime_type=COALESCE(?, mime_type), uploaded_at=COALESCE(?, uploaded_at),
               status='pending', status_reason='document text changed', coverage=NULL, updated_at=? WHERE doc_id=?""",
            (doc.title, doc.text_title, doc.path, doc.sha256, doc.kind, doc.external_id, doc.source, doc.text,
             doc.text_source, doc.parse_status, *files, utcnow(), doc.doc_id),
        )
        return True

    def get_document(self, doc_id: str, *, include_text: bool = True) -> Document | None:
        cols = "*" if include_text else _DOCUMENT_COLUMNS_NO_TEXT
        row = self._row("documents", self._one(f"SELECT {cols} FROM documents WHERE doc_id=?", (doc_id,)))
        return Document.model_validate(row) if row else None

    def list_documents(self, *, include_text: bool = True) -> list[Document]:
        cols = "*" if include_text else _DOCUMENT_COLUMNS_NO_TEXT
        rows = self._query(f"SELECT {cols} FROM documents ORDER BY ingested_at, doc_id")
        return [Document.model_validate(r) for r in self._rows("documents", rows)]

    def find_document_by_sha(self, sha256: str) -> Document | None:
        row = self._one(f"SELECT {_DOCUMENT_COLUMNS_NO_TEXT} FROM documents WHERE sha256=? ORDER BY doc_id", (sha256,))
        return Document.model_validate(self._row("documents", row)) if row else None

    def update_document(self, doc_id: str, **changes: Any) -> None:
        bad = set(changes) - _DOCUMENT_UPDATABLE
        if bad:
            raise ValueError(f"update_document cannot change {sorted(bad)}")
        if not changes:
            return
        sets = ", ".join(f"{k}=?" for k in changes)
        self._write(f"UPDATE documents SET {sets}, updated_at=? WHERE doc_id=?", (*changes.values(), utcnow(), doc_id))

    def needs_extraction(self, doc_id: str) -> bool:
        """False when the current text was already extracted completely, or when there is no text to extract."""
        doc = self.get_document(doc_id, include_text=False)
        if doc is None or doc.parse_status == "unparseable":
            return False
        return not (doc.status == "complete" and doc.extracted_sha256 == doc.sha256)

    def set_document_status(
        self,
        doc_id: str,
        status: str,
        reason: str | None = None,
        coverage: float | None = None,
        extracted_sha256: str | None = None,
    ) -> None:
        self._write(
            """UPDATE documents SET status=?, status_reason=?, coverage=COALESCE(?, coverage),
               extracted_sha256=COALESCE(?, extracted_sha256), updated_at=? WHERE doc_id=?""",
            (status, reason, coverage, extracted_sha256, utcnow(), doc_id),
        )

    # ------------------------------------------------------------------ document files

    def add_document_file(self, f: DocumentFile) -> int | None:
        """Register a stored file; a (doc_id, sha256) pair is stored once."""
        return self._insert("document_files", f.model_dump(exclude={"id"}), ignore_conflicts=True)

    def find_file_by_sha(self, sha256: str) -> DocumentFile | None:
        row = self._one("SELECT * FROM document_files WHERE sha256=? ORDER BY id LIMIT 1", (sha256,))
        return DocumentFile.model_validate(self._row("document_files", row)) if row else None

    def list_document_files(self, doc_id: str) -> list[DocumentFile]:
        rows = self._query("SELECT * FROM document_files WHERE doc_id=? ORDER BY id", (doc_id,))
        return [DocumentFile.model_validate(r) for r in self._rows("document_files", rows)]

    # ------------------------------------------------------------------ clauses

    def replace_clauses(self, doc_id: str, clauses: Iterable[Clause]) -> None:
        with self.transaction():
            self._write("DELETE FROM clauses WHERE doc_id=?", (doc_id,))
            self._insert_many("clauses", (c.model_dump() for c in clauses))

    def get_clause(self, clause_id: str) -> Clause | None:
        row = self._one("SELECT * FROM clauses WHERE clause_id=?", (clause_id,))
        return Clause.model_validate(self._row("clauses", row)) if row else None

    def list_clauses(self, doc_id: str) -> list[Clause]:
        rows = self._query("SELECT * FROM clauses WHERE doc_id=? ORDER BY ordinal", (doc_id,))
        return [Clause.model_validate(r) for r in self._rows("clauses", rows)]

    # ------------------------------------------------------------------ extractions + citations

    def add_extraction(self, ex: Extraction, citations: Iterable[Citation] = ()) -> int:
        with self.transaction():
            data = ex.model_dump(exclude={"id"})
            data["readings"] = [r.model_dump() if hasattr(r, "model_dump") else r for r in ex.readings]
            ex_id = self._insert("extractions", data)
            assert ex_id is not None
            self._insert_many("citations", (c.model_dump(exclude={"id"}) | {"extraction_id": ex_id} for c in citations))
        return ex_id

    def add_citation(self, c: Citation) -> int:
        new_id = self._insert("citations", c.model_dump(exclude={"id"}))
        assert new_id is not None
        return new_id

    def get_extraction(self, ex_id: int) -> Extraction | None:
        row = self._row("extractions", self._one("SELECT * FROM extractions WHERE id=?", (ex_id,)))
        return Extraction.model_validate(row) if row else None

    def current_extractions(self, doc_id: str | None = None, agent: str | None = None) -> list[Extraction]:
        sql, args = "SELECT * FROM extractions WHERE is_current = TRUE", []
        if doc_id:
            sql += " AND doc_id=?"
            args.append(doc_id)
        if agent:
            sql += " AND agent=?"
            args.append(agent)
        rows = self._query(sql + " ORDER BY doc_id, id", args)
        return [Extraction.model_validate(r) for r in self._rows("extractions", rows)]

    def extraction_history(self, doc_id: str, field_key: str) -> list[Extraction]:
        rows = self._query(
            "SELECT * FROM extractions WHERE doc_id=? AND field_key=? ORDER BY version, id", (doc_id, field_key)
        )
        return [Extraction.model_validate(r) for r in self._rows("extractions", rows)]

    def latest_version(self, doc_id: str, agent: str, field_key: str) -> Extraction | None:
        row = self._one(
            "SELECT * FROM extractions WHERE doc_id=? AND agent=? AND field_key=? ORDER BY version DESC, id DESC LIMIT 1",
            (doc_id, agent, field_key),
        )
        return Extraction.model_validate(self._row("extractions", row)) if row else None

    def retire_extraction(self, ex_id: int) -> None:
        self._write("UPDATE extractions SET is_current = FALSE WHERE id=?", (ex_id,))

    def retire_current(self, doc_id: str, agent: str) -> int:
        """Mark every current extraction of (doc, agent) as historical. Returns the count."""
        return self._write(
            "UPDATE extractions SET is_current = FALSE WHERE doc_id=? AND agent=? AND is_current = TRUE", (doc_id, agent)
        )

    def citations_for(self, extraction_id: int) -> list[Citation]:
        rows = self._query("SELECT * FROM citations WHERE extraction_id=? ORDER BY id", (extraction_id,))
        return [Citation.model_validate(r) for r in self._rows("citations", rows)]

    def citations_for_document(self, doc_id: str, *, current_only: bool = True) -> list[Citation]:
        """Every citation of the document's (current) extractions, in one query (viewer, dashboard)."""
        sql = "SELECT c.* FROM citations c JOIN extractions e ON e.id = c.extraction_id WHERE e.doc_id=?"
        if current_only:
            sql += " AND e.is_current = TRUE"
        rows = self._query(sql + " ORDER BY c.id", (doc_id,))
        return [Citation.model_validate(r) for r in self._rows("citations", rows)]

    def current_extractions_citing(self, clause_ids: str | Iterable[str]) -> list[Extraction]:
        ids = [clause_ids] if isinstance(clause_ids, str) else list(clause_ids)
        if not ids:
            return []
        marks = ", ".join("?" for _ in ids)
        rows = self._query(
            f"""SELECT DISTINCT e.* FROM extractions e JOIN citations c ON c.extraction_id = e.id
               WHERE e.is_current = TRUE AND c.clause_id IN ({marks}) ORDER BY e.id""",
            ids,
        )
        return [Extraction.model_validate(r) for r in self._rows("extractions", rows)]

    # ------------------------------------------------------------------ flags

    def add_flag(self, flag: Flag) -> int:
        new_id = self._insert("flags", flag.model_dump(exclude={"id"}))
        assert new_id is not None
        return new_id

    def list_flags(self, doc_id: str | None = None, status: str | None = "open") -> list[Flag]:
        sql, args = "SELECT * FROM flags WHERE 1=1", []
        if doc_id:
            sql += " AND doc_id=?"
            args.append(doc_id)
        if status:
            sql += " AND status=?"
            args.append(status)
        rows = self._query(sql + " ORDER BY id", args)
        return [Flag.model_validate(r) for r in self._rows("flags", rows)]

    def supersede_flags(self, doc_id: str, raised_by: str) -> int:
        return self._write(
            "UPDATE flags SET status='superseded' WHERE doc_id=? AND raised_by=? AND status='open'", (doc_id, raised_by)
        )

    def supersede_flags_for_extraction(self, extraction_id: int) -> int:
        """Retire the open flags raised about one extraction (it was replaced by a new version)."""
        return self._write("UPDATE flags SET status='superseded' WHERE extraction_id=? AND status='open'", (extraction_id,))

    def set_flag_status(self, flag_id: int, status: str) -> None:
        self._write("UPDATE flags SET status=? WHERE id=?", (status, flag_id))

    # ------------------------------------------------------------------ relations

    def add_relation(self, rel: DocRelation) -> int | None:
        """Insert unless an identical (from, to, type, citing clause, agent) row exists."""
        return self._insert("doc_relations", rel.model_dump(exclude={"id"}), ignore_conflicts=True)

    def delete_relations(self, from_or_citing_doc: str, raised_by: str) -> None:
        """Drop relations an agent derived from one document's clauses (before re-deriving them)."""
        self._write("DELETE FROM doc_relations WHERE raised_by=? AND clause_id LIKE ?", (raised_by, f"{from_or_citing_doc}:%"))

    def delete_relations_for_extraction(self, extraction_id: int) -> int:
        """Drop the edges derived from one extraction (it was replaced by a new version)."""
        return self._write("DELETE FROM doc_relations WHERE extraction_id=?", (extraction_id,))

    def list_relations(self, doc_id: str | None = None) -> list[DocRelation]:
        sql, args = "SELECT * FROM doc_relations", []
        if doc_id:
            sql += " WHERE from_doc=? OR to_doc=?"
            args += [doc_id, doc_id]
        rows = self._query(sql + " ORDER BY from_doc, to_doc, type, id", args)
        return [DocRelation.model_validate(r) for r in self._rows("doc_relations", rows)]

    # ------------------------------------------------------------------ messages

    def post_message(self, msg: Message) -> int:
        new_id = self._insert("messages", msg.model_dump(exclude={"id"}))
        assert new_id is not None
        return new_id

    def get_message(self, msg_id: int) -> Message | None:
        row = self._row("messages", self._one("SELECT * FROM messages WHERE id=?", (msg_id,)))
        return Message.model_validate(row) if row else None

    def pending_messages(self, to_agent: str, type: str | None = None) -> list[Message]:
        sql, args = "SELECT * FROM messages WHERE to_agent=? AND status='pending'", [to_agent]
        if type:
            sql += " AND type=?"
            args.append(type)
        rows = self._query(sql + " ORDER BY id", args)
        return [Message.model_validate(r) for r in self._rows("messages", rows)]

    def set_message_status(self, msg_id: int, status: str) -> None:
        self._write("UPDATE messages SET status=?, updated_at=? WHERE id=?", (status, utcnow(), msg_id))

    # ------------------------------------------------------------------ workstreams

    def upsert_workstream(self, ws: Workstream) -> None:
        with self.transaction():
            existing = self._row("workstreams", self._one("SELECT agent_status FROM workstreams WHERE id=?", (ws.id,)))
            status = dict(existing["agent_status"]) if existing else {}
            status.update(ws.agent_status)  # merge: one agent never erases another's status
            self._write(
                """INSERT INTO workstreams (id, scope, members, agent_status, notes, updated_at) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET scope=excluded.scope, members=excluded.members,
                   agent_status=excluded.agent_status, notes=excluded.notes, updated_at=excluded.updated_at""",
                (ws.id, ws.scope, _dumps(ws.members), _dumps(status), ws.notes, utcnow()),
            )

    def list_workstreams(self) -> list[Workstream]:
        rows = self._query("SELECT * FROM workstreams ORDER BY id")
        return [Workstream.model_validate(r) for r in self._rows("workstreams", rows)]

    # ------------------------------------------------------------------ trace

    def log_trace(self, entry: TraceEntry) -> int:
        new_id = self._insert("trace", entry.model_dump(exclude={"id"}))
        assert new_id is not None
        return new_id

    def trace(self, run_id: str | None = None, agent: str | None = None) -> list[TraceEntry]:
        sql, args = "SELECT * FROM trace WHERE 1=1", []
        if run_id:
            sql += " AND run_id=?"
            args.append(run_id)
        if agent:
            sql += " AND agent=?"
            args.append(agent)
        rows = self._query(sql + " ORDER BY id", args)
        return [TraceEntry.model_validate(r) for r in self._rows("trace", rows)]

    # ------------------------------------------------------------------ inputs for later agents

    def upsert_resource(self, res: Resource) -> bool:
        """Insert or refresh a resource. Returns False when nothing changed."""
        old = self.get_resource(res.path)
        if old and old.sha256 == res.sha256 and (res.storage_path is None or res.storage_path == old.storage_path) \
                and (res.text is None or old.text is not None):
            return False
        data = res.model_dump()
        if old and old.sha256 == res.sha256:
            for col in ("storage_path", "mime_type", "size_bytes", "text"):
                if data[col] is None:
                    data[col] = getattr(old, col)   # same file: keep what an earlier load already stored
        cols = list(data)
        self._write(
            f"""INSERT INTO resources ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})
                ON CONFLICT(path) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in cols if c != 'path')}""",
            tuple(data.values()),
        )
        return True

    def get_resource(self, path: str) -> Resource | None:
        row = self._one("SELECT * FROM resources WHERE path=?", (path,))
        return Resource.model_validate(self._row("resources", row)) if row else None

    def list_resources(self, kind: str | None = None) -> list[Resource]:
        sql, args = "SELECT * FROM resources", []
        if kind:
            sql += " WHERE kind=?"
            args.append(kind)
        rows = self._query(sql + " ORDER BY path", args)
        return [Resource.model_validate(r) for r in self._rows("resources", rows)]

    def add_events(self, events: Iterable[Event]) -> int:
        rows = []
        for e in events:
            data = e.model_dump(exclude={"id"})
            data["drop_name"] = data.pop("drop")
            rows.append(data)
        with self.transaction():
            return self._insert_many("events", rows, ignore_conflicts=True)

    def add_ledger(self, entries: Iterable[LedgerEntry]) -> int:
        with self.transaction():
            return self._insert_many("ledger_entries", (e.model_dump(exclude={"id"}) for e in entries), ignore_conflicts=True)

    def list_ledger(self) -> list[LedgerEntry]:
        rows = self._query("SELECT * FROM ledger_entries ORDER BY line_no")
        return [LedgerEntry.model_validate(r) for r in self._rows("ledger_entries", rows)]

    def add_holidays(self, holidays: Iterable[Holiday]) -> int:
        with self.transaction():
            return self._insert_many("holidays", (h.model_dump() for h in holidays), ignore_conflicts=True)

    def list_holidays(self) -> list[Holiday]:
        rows = self._query("SELECT * FROM holidays ORDER BY date, observed_by")
        return [Holiday.model_validate(r) for r in self._rows("holidays", rows)]

    def add_checkpoints(self, points: Iterable[Checkpoint]) -> int:
        with self.transaction():
            return self._insert_many("clock_checkpoints", (p.model_dump() for p in points), ignore_conflicts=True)

    def list_checkpoints(self) -> list[Checkpoint]:
        rows = self._query("SELECT * FROM clock_checkpoints ORDER BY idx")
        return [Checkpoint.model_validate(r) for r in self._rows("clock_checkpoints", rows)]

    # ------------------------------------------------------------------ Norns: rules, instances, clock, snapshots

    def replace_obligation_rules(self, contracts: Iterable[str], rules: Iterable[ObligationRule]) -> int:
        """Rules are derived data: rebuilding a contract replaces all of its rules in one transaction."""
        contracts = list(contracts)
        with self.transaction():
            for c in contracts:
                self._write("DELETE FROM obligation_rules WHERE contract=?", (c,))
            return self._insert_many("obligation_rules", (r.model_dump() for r in rules))

    def list_obligation_rules(self, contract: str | None = None) -> list[ObligationRule]:
        sql, args = "SELECT * FROM obligation_rules", []
        if contract:
            sql += " WHERE contract=?"
            args.append(contract)
        rows = self._query(sql + " ORDER BY contract, kind, rule_id", args)
        return [ObligationRule.model_validate(r) for r in self._rows("obligation_rules", rows)]

    def replace_obligation_instances(self, as_of: str, instances: Iterable[ObligationInstance]) -> int:
        with self.transaction():
            self._write("DELETE FROM obligation_instances WHERE as_of=?", (as_of,))
            return self._insert_many("obligation_instances", (i.model_dump(exclude={"id"}) for i in instances))

    def list_obligation_instances(self, as_of: str, contract: str | None = None) -> list[ObligationInstance]:
        sql, args = "SELECT * FROM obligation_instances WHERE as_of=?", [as_of]
        if contract:
            sql += " AND contract=?"
            args.append(contract)
        rows = self._query(sql + " ORDER BY due_date, instance_key", args)
        return [ObligationInstance.model_validate(r) for r in self._rows("obligation_instances", rows)]

    def get_clock_state(self) -> ClockState | None:
        row = self._one("SELECT * FROM clock_state WHERE id=1")
        return ClockState.model_validate(self._row("clock_state", row)) if row else None

    def set_clock_state(self, as_of: str, action: str, note: str | None = None) -> ClockEvent:
        """Move the clock (one row) and record the move in clock_history, atomically."""
        with self.transaction():
            old = self.get_clock_state()
            self._write("""INSERT INTO clock_state (id, current_as_of, updated_at) VALUES (1, ?, ?)
                           ON CONFLICT(id) DO UPDATE SET current_as_of=excluded.current_as_of,
                           updated_at=excluded.updated_at""", (as_of, utcnow()))
            ev = ClockEvent(action=action, from_as_of=old.current_as_of if old else None, to_as_of=as_of, note=note)
            ev.id = self._insert("clock_history", ev.model_dump(exclude={"id"}))
        return ev

    def list_clock_history(self) -> list[ClockEvent]:
        rows = self._query("SELECT * FROM clock_history ORDER BY id")
        return [ClockEvent.model_validate(r) for r in self._rows("clock_history", rows)]

    def add_timeline_snapshot(self, snap: TimelineSnapshot) -> int:
        new_id = self._insert("timeline_snapshots", snap.model_dump(exclude={"id"}))
        assert new_id is not None
        return new_id

    def latest_snapshot(self, as_of: str | None = None) -> TimelineSnapshot | None:
        if as_of:
            row = self._one("SELECT * FROM timeline_snapshots WHERE as_of=? ORDER BY id DESC LIMIT 1", (as_of,))
        else:
            row = self._one("SELECT * FROM timeline_snapshots ORDER BY id DESC LIMIT 1")
        return TimelineSnapshot.model_validate(self._row("timeline_snapshots", row)) if row else None

    def replace_exposure_items(self, as_of: str, items: Iterable[ExposureItem]) -> int:
        with self.transaction():
            self._write("DELETE FROM exposure_items WHERE as_of=?", (as_of,))
            return self._insert_many("exposure_items", (i.model_dump(exclude={"id"}) for i in items))

    def list_exposure_items(self, as_of: str, scenario: str | None = None) -> list[ExposureItem]:
        sql, args = "SELECT * FROM exposure_items WHERE as_of=?", [as_of]
        if scenario:
            sql += " AND scenario=?"
            args.append(scenario)
        rows = self._query(sql + " ORDER BY scenario, contract, accrues_on, id", args)
        return [ExposureItem.model_validate(r) for r in self._rows("exposure_items", rows)]

    def add_writeup(self, w: Writeup) -> int:
        new_id = self._insert("writeups", w.model_dump(exclude={"id"}))
        assert new_id is not None
        return new_id

    def latest_writeup(self, as_of: str) -> Writeup | None:
        row = self._one("SELECT * FROM writeups WHERE as_of=? ORDER BY id DESC LIMIT 1", (as_of,))
        return Writeup.model_validate(self._row("writeups", row)) if row else None

    # ------------------------------------------------------------------ Loki: adversarial review findings

    def replace_loki_findings(self, doc_id: str, as_of: str, findings: Iterable[LokiFinding]) -> int:
        """A re-run for the same document and as_of replaces its findings, in one transaction."""
        with self.transaction():
            self._write("DELETE FROM loki_findings WHERE doc_id=? AND as_of=?", (doc_id, as_of))
            return self._insert_many("loki_findings", (f.model_dump(exclude={"id"}) for f in findings))

    def list_loki_findings(self, doc_id: str | None = None, as_of: str | None = None,
                           status: str | None = None) -> list[LokiFinding]:
        sql, args = "SELECT * FROM loki_findings WHERE 1=1", []
        for col, value in (("doc_id", doc_id), ("as_of", as_of), ("status", status)):
            if value:
                sql += f" AND {col}=?"
                args.append(value)
        rows = self._query(sql + " ORDER BY doc_id, as_of, rank, id", args)
        return [LokiFinding.model_validate(r) for r in self._rows("loki_findings", rows)]

    # ------------------------------------------------------------------ Heimdall: events, alerts, task board

    def replace_heimdall_events(self, as_of: str, drop_name: str, events: Iterable[HeimdallEvent]) -> int:
        """A re-run of one drop on one clock date replaces what that run stored."""
        with self.transaction():
            self._write("DELETE FROM heimdall_events WHERE as_of=? AND drop_name=?", (as_of, drop_name))
            return self._insert_many("heimdall_events", (e.model_dump(exclude={"id"}) for e in events))

    def list_heimdall_events(self, as_of: str | None = None, drop_name: str | None = None) -> list[HeimdallEvent]:
        sql, args = "SELECT * FROM heimdall_events WHERE 1=1", []
        for col, value in (("as_of", as_of), ("drop_name", drop_name)):
            if value:
                sql += f" AND {col}=?"
                args.append(value)
        rows = self._query(sql + " ORDER BY as_of, drop_name, line_no", args)
        return [HeimdallEvent.model_validate(r) for r in self._rows("heimdall_events", rows)]

    def heimdall_runs(self) -> list[tuple[str, str]]:
        """(as_of, drop_name) of every stored Heimdall run, oldest first."""
        rows = self._query("SELECT DISTINCT as_of, drop_name FROM heimdall_events ORDER BY as_of, drop_name")
        return [(str(_plain(r["as_of"])), r["drop_name"]) for r in rows]

    def replace_heimdall_alerts(self, as_of: str, alerts: Iterable[HeimdallAlert]) -> int:
        with self.transaction():
            self._write("DELETE FROM heimdall_alerts WHERE as_of=?", (as_of,))
            return self._insert_many("heimdall_alerts", (a.model_dump(exclude={"id"}) for a in alerts))

    def list_heimdall_alerts(self, as_of: str) -> list[HeimdallAlert]:
        rows = self._query("SELECT * FROM heimdall_alerts WHERE as_of=? ORDER BY id", (as_of,))
        return [HeimdallAlert.model_validate(r) for r in self._rows("heimdall_alerts", rows)]

    def upsert_heimdall_task(self, task: HeimdallTask) -> None:
        data = self._prepare("heimdall_tasks", task.model_dump())
        cols = list(data)
        self._write(
            f"""INSERT INTO heimdall_tasks ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})
                ON CONFLICT(as_of, task_id) DO UPDATE SET
                {', '.join(f'{c}=excluded.{c}' for c in cols if c not in ('as_of', 'task_id'))}""",
            tuple(data.values()),
        )

    def delete_heimdall_tasks(self, as_of: str, task_ids: Iterable[str]) -> int:
        n = 0
        with self.transaction():
            for task_id in task_ids:
                n += self._write("DELETE FROM heimdall_tasks WHERE as_of=? AND task_id=?", (as_of, task_id))
        return n

    def list_heimdall_tasks(self, as_of: str) -> list[HeimdallTask]:
        rows = self._query("SELECT * FROM heimdall_tasks WHERE as_of=? ORDER BY due_date, task_id", (as_of,))
        return [HeimdallTask.model_validate(r) for r in self._rows("heimdall_tasks", rows)]

    def set_heimdall_task_status(self, as_of: str, task_id: str, status: str, fact: dict[str, Any] | None) -> bool:
        """A user's tag change. False when the task is Norns' (paid / met), which the user cannot change."""
        n = self._write(
            """UPDATE heimdall_tasks SET status=?, status_source='user', fact=?, updated_at=?
               WHERE as_of=? AND task_id=? AND status_source <> 'norns'""",
            (status, _dumps(fact), utcnow(), as_of, task_id),
        )
        return n > 0

    # ------------------------------------------------------------------ summaries

    def document_stats(self) -> dict[str, dict[str, int]]:
        """Per document: current fields found / missing, open flags, failed citations (one query each)."""
        stats: dict[str, dict[str, int]] = {}

        def bucket(doc_id: str) -> dict[str, int]:
            return stats.setdefault(doc_id, {"fields": 0, "missing": 0, "flags": 0, "citations_failed": 0})

        for r in self._query(
            """SELECT doc_id, SUM(CASE WHEN status='missing' THEN 0 ELSE 1 END) AS fields,
                      SUM(CASE WHEN status='missing' THEN 1 ELSE 0 END) AS missing
               FROM extractions WHERE is_current = TRUE GROUP BY doc_id"""
        ):
            bucket(r["doc_id"]).update(fields=int(r["fields"] or 0), missing=int(r["missing"] or 0))
        for r in self._query("SELECT doc_id, COUNT(*) AS n FROM flags WHERE status='open' AND doc_id IS NOT NULL GROUP BY doc_id"):
            bucket(r["doc_id"])["flags"] = int(r["n"])
        for r in self._query(
            """SELECT e.doc_id, SUM(CASE WHEN c.verified THEN 0 ELSE 1 END) AS n FROM citations c
               JOIN extractions e ON e.id = c.extraction_id WHERE e.is_current = TRUE GROUP BY e.doc_id"""
        ):
            bucket(r["doc_id"])["citations_failed"] = int(r["n"] or 0)
        return stats

    def row_counts(self) -> dict[str, int]:
        return {t: int(self._one(f"SELECT COUNT(*) AS n FROM {t}")["n"]) for t in TABLES}  # type: ignore[index]

    # ------------------------------------------------------------------ export

    def export(self, include_clause_text: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "backend": self.backend, "exported_at": utcnow()}
        for t in TABLES:
            rows = self._rows(t, self._query(f"SELECT * FROM {t}"))
            if t == "clauses" and not include_clause_text:
                for r in rows:
                    r.pop("text", None)
            if t == "documents":
                for r in rows:
                    r.pop("text", None)        # the clauses carry the text; keep the export readable
            out[t] = rows
        return out

    def export_json(self, path: str | Path, include_clause_text: bool = True) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.export(include_clause_text), ensure_ascii=False, indent=2, default=_json_default),
                        encoding="utf-8")
        return path

    # ------------------------------------------------------------------ backend plumbing

    @contextmanager
    def transaction(self) -> Iterator["StateStore"]:  # pragma: no cover - abstract
        raise NotImplementedError
        yield self

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    def _write(self, sql: str, params: Sequence[Any] = ()) -> int:  # pragma: no cover
        raise NotImplementedError

    def _write_many(self, sql: str, seq: list[tuple[Any, ...]]) -> int:  # pragma: no cover
        raise NotImplementedError

    def _insert_id(self, sql: str, params: Sequence[Any]) -> int | None:  # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def describe(self) -> str:
        return self.backend


class SQLiteStateStore(StateStore):
    backend = "sqlite"

    def __init__(self, db_path: str | Path):
        super().__init__()
        self.db_path = Path(db_path)
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # One connection shared by every thread (Streamlit reruns, Thor's pool); the lock serialises use.
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._upgrade_old_schema()
        self.conn.executescript(SQLITE_SCHEMA)
        self.conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(SCHEMA_VERSION),))
        self.conn.commit()

    def _upgrade_old_schema(self) -> None:
        existing = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, columns in _SQLITE_ADDED_COLUMNS.items():
            if table not in existing:
                continue
            have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for name, ddl in columns:
                if name not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        for table in _SQLITE_RETIRED_TABLES:
            if table in existing and not self.conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                self.conn.execute(f"DROP TABLE {table}")
        self.conn.commit()

    def describe(self) -> str:
        return f"sqlite ({self.db_path})"

    @contextmanager
    def transaction(self) -> Iterator[StateStore]:
        """Nested-safe transaction: commits once at the outermost level, rolls back on error."""
        with self._lock:
            self._depth += 1
            try:
                yield self
                if self._depth == 1:
                    self.conn.commit()
            except BaseException:
                if self._depth == 1:
                    self.conn.rollback()
                raise
            finally:
                self._depth -= 1

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def _write(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.transaction():
            return self.conn.execute(sql, tuple(params)).rowcount

    def _write_many(self, sql: str, seq: list[tuple[Any, ...]]) -> int:
        with self.transaction():
            return self.conn.executemany(sql, seq).rowcount

    def _insert_id(self, sql: str, params: Sequence[Any]) -> int | None:
        with self.transaction():
            cur = self.conn.execute(sql, tuple(params))
        return int(cur.lastrowid) if cur.rowcount else None

    def close(self) -> None:
        self.conn.close()

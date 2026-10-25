"""SQLite-backed shared state (state/odin.db) with a JSON export.

One store is shared by every agent. Writes are idempotent where the spec requires it:
re-ingesting an unchanged document is a no-op, relations are de-duplicated by a unique
index, and extractions are versioned instead of overwritten.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from odin.state.models import (
    Citation,
    Clause,
    DocRelation,
    Document,
    Event,
    Extraction,
    Flag,
    Holiday,
    LedgerEntry,
    Message,
    Resource,
    TraceEntry,
    Workstream,
    utcnow,
)

SCHEMA_VERSION = 1

SCHEMA = """
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
    ingested_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

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
CREATE UNIQUE INDEX IF NOT EXISTS ux_relations ON doc_relations(from_doc, to_doc, type, IFNULL(clause_id, ''), raised_by);

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

CREATE TABLE IF NOT EXISTS ledger (
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

CREATE TABLE IF NOT EXISTS checkpoints (
    idx INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    label TEXT NOT NULL
);
"""

_JSON_COLUMNS = {
    "extractions": ("value", "readings"),
    "doc_relations": ("citation",),
    "messages": ("payload",),
    "workstreams": ("members", "agent_status"),
    "trace": ("meta",),
    "events": ("processed_by",),
}
_BOOL_COLUMNS = {
    "extractions": ("is_current",),
    "citations": ("verified",),
    "flags": ("evidence_verified",),
    "doc_relations": ("verified",),
}


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class StateStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._depth = 0
        self.conn.executescript(SCHEMA)
        self.conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ plumbing

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Nested-safe transaction: commits once at the outermost level, rolls back on error."""
        self._depth += 1
        try:
            yield self.conn
            if self._depth == 1:
                self.conn.commit()
        except BaseException:
            if self._depth == 1:
                self.conn.rollback()
            raise
        finally:
            self._depth -= 1

    def _row(self, table: str, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        d = dict(row)
        for col in _JSON_COLUMNS.get(table, ()):
            if d.get(col) is not None:
                d[col] = json.loads(d[col])
        for col in _BOOL_COLUMNS.get(table, ()):
            if d.get(col) is not None:
                d[col] = bool(d[col])
        if table == "events":
            d["drop"] = d.pop("drop_name")
        return d

    def _rows(self, table: str, rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
        return [self._row(table, r) for r in rows]  # type: ignore[misc]

    def _insert(self, table: str, data: dict[str, Any]) -> int:
        data = dict(data)
        for col in _JSON_COLUMNS.get(table, ()):
            if col in data:
                data[col] = _dumps(data[col])
        for col in _BOOL_COLUMNS.get(table, ()):
            if col in data and data[col] is not None:
                data[col] = int(bool(data[col]))
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        with self.transaction():
            cur = self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(data.values()))
        return int(cur.lastrowid)

    # ------------------------------------------------------------------ documents

    def upsert_document(self, doc: Document) -> bool:
        """Insert or update a document. Returns True when it is new or its sha256 changed."""
        existing = self.get_document(doc.doc_id)
        if existing is None:
            self._insert("documents", doc.model_dump())
            return True
        if existing.sha256 == doc.sha256:
            # Unchanged text: keep extraction status; refresh metadata only.
            with self.transaction():
                self.conn.execute(
                    "UPDATE documents SET title=?, text_title=?, path=?, kind=?, external_id=? WHERE doc_id=?",
                    (doc.title, doc.text_title, doc.path, doc.kind, doc.external_id, doc.doc_id),
                )
            return False
        with self.transaction():
            self.conn.execute(
                """UPDATE documents SET title=?, text_title=?, path=?, sha256=?, kind=?, external_id=?, source=?,
                   status='pending', status_reason='document text changed', coverage=NULL, updated_at=? WHERE doc_id=?""",
                (doc.title, doc.text_title, doc.path, doc.sha256, doc.kind, doc.external_id, doc.source, utcnow(), doc.doc_id),
            )
        return True

    def get_document(self, doc_id: str) -> Document | None:
        row = self.conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        return Document.model_validate(dict(row)) if row else None

    def list_documents(self) -> list[Document]:
        rows = self.conn.execute("SELECT * FROM documents ORDER BY ingested_at, doc_id").fetchall()
        return [Document.model_validate(dict(r)) for r in rows]

    def needs_extraction(self, doc_id: str) -> bool:
        """False only when the current text was already extracted completely."""
        doc = self.get_document(doc_id)
        if doc is None:
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
        with self.transaction():
            self.conn.execute(
                """UPDATE documents SET status=?, status_reason=?, coverage=COALESCE(?, coverage),
                   extracted_sha256=COALESCE(?, extracted_sha256), updated_at=? WHERE doc_id=?""",
                (status, reason, coverage, extracted_sha256, utcnow(), doc_id),
            )

    # ------------------------------------------------------------------ clauses

    def replace_clauses(self, doc_id: str, clauses: Iterable[Clause]) -> None:
        with self.transaction():
            self.conn.execute("DELETE FROM clauses WHERE doc_id=?", (doc_id,))
            for c in clauses:
                self._insert("clauses", c.model_dump())

    def get_clause(self, clause_id: str) -> Clause | None:
        row = self.conn.execute("SELECT * FROM clauses WHERE clause_id=?", (clause_id,)).fetchone()
        return Clause.model_validate(dict(row)) if row else None

    def list_clauses(self, doc_id: str) -> list[Clause]:
        rows = self.conn.execute("SELECT * FROM clauses WHERE doc_id=? ORDER BY ordinal", (doc_id,)).fetchall()
        return [Clause.model_validate(dict(r)) for r in rows]

    # ------------------------------------------------------------------ extractions + citations

    def add_extraction(self, ex: Extraction, citations: Iterable[Citation] = ()) -> int:
        with self.transaction():
            data = ex.model_dump(exclude={"id"})
            data["readings"] = [r.model_dump() if hasattr(r, "model_dump") else r for r in ex.readings]
            ex_id = self._insert("extractions", data)
            for c in citations:
                self.add_citation(c.model_copy(update={"extraction_id": ex_id}))
        return ex_id

    def add_citation(self, c: Citation) -> int:
        return self._insert("citations", c.model_dump(exclude={"id"}))

    def get_extraction(self, ex_id: int) -> Extraction | None:
        row = self.conn.execute("SELECT * FROM extractions WHERE id=?", (ex_id,)).fetchone()
        return Extraction.model_validate(self._row("extractions", row)) if row else None

    def current_extractions(self, doc_id: str | None = None, agent: str | None = None) -> list[Extraction]:
        sql, args = "SELECT * FROM extractions WHERE is_current=1", []
        if doc_id:
            sql += " AND doc_id=?"
            args.append(doc_id)
        if agent:
            sql += " AND agent=?"
            args.append(agent)
        rows = self.conn.execute(sql + " ORDER BY doc_id, id", args).fetchall()
        return [Extraction.model_validate(self._row("extractions", r)) for r in rows]

    def extraction_history(self, doc_id: str, field_key: str) -> list[Extraction]:
        rows = self.conn.execute(
            "SELECT * FROM extractions WHERE doc_id=? AND field_key=? ORDER BY version, id", (doc_id, field_key)
        ).fetchall()
        return [Extraction.model_validate(self._row("extractions", r)) for r in rows]

    def latest_version(self, doc_id: str, agent: str, field_key: str) -> Extraction | None:
        row = self.conn.execute(
            "SELECT * FROM extractions WHERE doc_id=? AND agent=? AND field_key=? ORDER BY version DESC, id DESC LIMIT 1",
            (doc_id, agent, field_key),
        ).fetchone()
        return Extraction.model_validate(self._row("extractions", row)) if row else None

    def retire_extraction(self, ex_id: int) -> None:
        with self.transaction():
            self.conn.execute("UPDATE extractions SET is_current=0 WHERE id=?", (ex_id,))

    def retire_current(self, doc_id: str, agent: str) -> int:
        """Mark every current extraction of (doc, agent) as historical. Returns the count."""
        with self.transaction():
            cur = self.conn.execute(
                "UPDATE extractions SET is_current=0 WHERE doc_id=? AND agent=? AND is_current=1", (doc_id, agent)
            )
        return cur.rowcount

    def citations_for(self, extraction_id: int) -> list[Citation]:
        rows = self.conn.execute("SELECT * FROM citations WHERE extraction_id=? ORDER BY id", (extraction_id,)).fetchall()
        return [Citation.model_validate(self._row("citations", r)) for r in rows]

    def current_extractions_citing(self, clause_ids: str | Iterable[str]) -> list[Extraction]:
        ids = [clause_ids] if isinstance(clause_ids, str) else list(clause_ids)
        if not ids:
            return []
        marks = ", ".join("?" for _ in ids)
        rows = self.conn.execute(
            f"""SELECT DISTINCT e.* FROM extractions e JOIN citations c ON c.extraction_id = e.id
               WHERE e.is_current=1 AND c.clause_id IN ({marks}) ORDER BY e.id""",
            ids,
        ).fetchall()
        return [Extraction.model_validate(self._row("extractions", r)) for r in rows]

    # ------------------------------------------------------------------ flags

    def add_flag(self, flag: Flag) -> int:
        return self._insert("flags", flag.model_dump(exclude={"id"}))

    def list_flags(self, doc_id: str | None = None, status: str | None = "open") -> list[Flag]:
        sql, args = "SELECT * FROM flags WHERE 1=1", []
        if doc_id:
            sql += " AND doc_id=?"
            args.append(doc_id)
        if status:
            sql += " AND status=?"
            args.append(status)
        rows = self.conn.execute(sql + " ORDER BY id", args).fetchall()
        return [Flag.model_validate(self._row("flags", r)) for r in rows]

    def supersede_flags(self, doc_id: str, raised_by: str) -> int:
        with self.transaction():
            cur = self.conn.execute(
                "UPDATE flags SET status='superseded' WHERE doc_id=? AND raised_by=? AND status='open'", (doc_id, raised_by)
            )
        return cur.rowcount

    def set_flag_status(self, flag_id: int, status: str) -> None:
        with self.transaction():
            self.conn.execute("UPDATE flags SET status=? WHERE id=?", (status, flag_id))

    # ------------------------------------------------------------------ relations

    def add_relation(self, rel: DocRelation) -> int | None:
        """Insert unless an identical (from, to, type, citing clause, agent) row exists."""
        data = rel.model_dump(exclude={"id"})
        data["citation"] = _dumps(data["citation"])
        data["verified"] = int(data["verified"])
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        with self.transaction():
            cur = self.conn.execute(f"INSERT OR IGNORE INTO doc_relations ({cols}) VALUES ({marks})", tuple(data.values()))
        return int(cur.lastrowid) if cur.rowcount else None

    def delete_relations(self, from_or_citing_doc: str, raised_by: str) -> None:
        """Drop relations an agent derived from one document's clauses (before re-deriving them)."""
        with self.transaction():
            self.conn.execute(
                "DELETE FROM doc_relations WHERE raised_by=? AND clause_id LIKE ?", (raised_by, f"{from_or_citing_doc}:%")
            )

    def list_relations(self, doc_id: str | None = None) -> list[DocRelation]:
        sql, args = "SELECT * FROM doc_relations", []
        if doc_id:
            sql += " WHERE from_doc=? OR to_doc=?"
            args += [doc_id, doc_id]
        rows = self.conn.execute(sql + " ORDER BY from_doc, to_doc, type, id", args).fetchall()
        return [DocRelation.model_validate(self._row("doc_relations", r)) for r in rows]

    # ------------------------------------------------------------------ messages

    def post_message(self, msg: Message) -> int:
        return self._insert("messages", msg.model_dump(exclude={"id"}))

    def get_message(self, msg_id: int) -> Message | None:
        row = self.conn.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
        return Message.model_validate(self._row("messages", row)) if row else None

    def pending_messages(self, to_agent: str, type: str | None = None) -> list[Message]:
        sql, args = "SELECT * FROM messages WHERE to_agent=? AND status='pending'", [to_agent]
        if type:
            sql += " AND type=?"
            args.append(type)
        rows = self.conn.execute(sql + " ORDER BY id", args).fetchall()
        return [Message.model_validate(self._row("messages", r)) for r in rows]

    def set_message_status(self, msg_id: int, status: str) -> None:
        with self.transaction():
            self.conn.execute("UPDATE messages SET status=?, updated_at=? WHERE id=?", (status, utcnow(), msg_id))

    # ------------------------------------------------------------------ workstreams

    def upsert_workstream(self, ws: Workstream) -> None:
        existing = self.conn.execute("SELECT agent_status FROM workstreams WHERE id=?", (ws.id,)).fetchone()
        status = json.loads(existing["agent_status"]) if existing else {}
        status.update(ws.agent_status)  # merge: one agent never erases another's status
        with self.transaction():
            self.conn.execute(
                """INSERT INTO workstreams (id, scope, members, agent_status, notes, updated_at) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET scope=excluded.scope, members=excluded.members,
                   agent_status=excluded.agent_status, notes=excluded.notes, updated_at=excluded.updated_at""",
                (ws.id, ws.scope, _dumps(ws.members), _dumps(status), ws.notes, utcnow()),
            )

    def list_workstreams(self) -> list[Workstream]:
        rows = self.conn.execute("SELECT * FROM workstreams ORDER BY id").fetchall()
        return [Workstream.model_validate(self._row("workstreams", r)) for r in rows]

    # ------------------------------------------------------------------ trace

    def log_trace(self, entry: TraceEntry) -> int:
        return self._insert("trace", entry.model_dump(exclude={"id"}))

    def trace(self, run_id: str | None = None, agent: str | None = None) -> list[TraceEntry]:
        sql, args = "SELECT * FROM trace WHERE 1=1", []
        if run_id:
            sql += " AND run_id=?"
            args.append(run_id)
        if agent:
            sql += " AND agent=?"
            args.append(agent)
        rows = self.conn.execute(sql + " ORDER BY id", args).fetchall()
        return [TraceEntry.model_validate(self._row("trace", r)) for r in rows]

    # ------------------------------------------------------------------ inputs for later agents

    def upsert_resource(self, res: Resource) -> bool:
        row = self.conn.execute("SELECT sha256 FROM resources WHERE path=?", (res.path,)).fetchone()
        if row and row["sha256"] == res.sha256:
            return False
        with self.transaction():
            self.conn.execute(
                "INSERT OR REPLACE INTO resources (path, kind, title, sha256, loaded_at) VALUES (?, ?, ?, ?, ?)",
                (res.path, res.kind, res.title, res.sha256, res.loaded_at),
            )
        return True

    def add_events(self, events: Iterable[Event]) -> int:
        n = 0
        with self.transaction():
            for e in events:
                data = e.model_dump(exclude={"id"})
                data["drop_name"] = data.pop("drop")
                data["processed_by"] = _dumps(data["processed_by"])
                cols = ", ".join(data)
                marks = ", ".join("?" for _ in data)
                cur = self.conn.execute(f"INSERT OR IGNORE INTO events ({cols}) VALUES ({marks})", tuple(data.values()))
                n += cur.rowcount
        return n

    def add_ledger(self, entries: Iterable[LedgerEntry]) -> int:
        n = 0
        with self.transaction():
            for e in entries:
                data = e.model_dump(exclude={"id"})
                cols = ", ".join(data)
                marks = ", ".join("?" for _ in data)
                cur = self.conn.execute(f"INSERT OR IGNORE INTO ledger ({cols}) VALUES ({marks})", tuple(data.values()))
                n += cur.rowcount
        return n

    def add_holidays(self, holidays: Iterable[Holiday]) -> int:
        n = 0
        with self.transaction():
            for h in holidays:
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO holidays (date, name, observed_by) VALUES (?, ?, ?)", (h.date, h.name, h.observed_by)
                )
                n += cur.rowcount
        return n

    # ------------------------------------------------------------------ export

    def export(self, include_clause_text: bool = True) -> dict[str, Any]:
        tables = [
            "documents", "clauses", "extractions", "citations", "flags", "doc_relations", "messages",
            "workstreams", "trace", "resources", "events", "ledger", "holidays", "checkpoints",
        ]
        out: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "exported_at": utcnow()}
        for t in tables:
            rows = self._rows(t, self.conn.execute(f"SELECT * FROM {t}").fetchall())
            if t == "clauses" and not include_clause_text:
                for r in rows:
                    r.pop("text", None)
            out[t] = rows
        return out

    def export_json(self, path: str | Path, include_clause_text: bool = True) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.export(include_clause_text), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

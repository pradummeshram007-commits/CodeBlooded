"""StateStore behaviour, run against both backends (SQLite always; Supabase Postgres when configured)."""
from __future__ import annotations

import sqlite3

import pytest

from odin.agents.thor import Thor
from odin.ingest.bundle import ingest_bundle
from odin.state.errors import StoreUnavailable
from odin.state.models import (
    Checkpoint,
    Citation,
    Clause,
    DocRelation,
    Document,
    DocumentFile,
    Extraction,
    Holiday,
    LedgerEntry,
    Reading,
)
from odin.state.store import TABLES, SQLiteStateStore

from .conftest import A3_ALL, DOC_IDS, doc_id_of, field, make_llm, reply


def _doc(sha: str = "abc", **kw) -> Document:
    return Document(doc_id="X1", title="t", path="contracts/X1.txt", sha256=sha, kind="contract", **kw)


def test_upsert_unchanged_document_is_a_noop(any_store) -> None:
    assert any_store.upsert_document(_doc()) is True
    assert any_store.upsert_document(_doc()) is False
    assert len(any_store.list_documents()) == 1


def test_needs_extraction_lifecycle(any_store) -> None:
    any_store.upsert_document(_doc("v1"))
    assert any_store.needs_extraction("X1")
    any_store.set_document_status("X1", "complete", coverage=100.0, extracted_sha256="v1")
    assert not any_store.needs_extraction("X1")
    any_store.upsert_document(_doc("v2"))                 # text changed -> back to pending
    assert any_store.get_document("X1").status == "pending"
    assert any_store.needs_extraction("X1")


def test_unparseable_documents_need_no_extraction(any_store) -> None:
    any_store.upsert_document(_doc(text="", parse_status="unparseable"))
    assert not any_store.needs_extraction("X1")


def test_document_text_and_storage_columns_round_trip(any_store) -> None:
    doc = _doc(text="SECTION 1 — X\nbody “quoted” §3.1\n", text_source="txt", parse_status="parsed",
               storage_path="X1/abc/X1.pdf", original_filename="X1.pdf", mime_type="application/pdf",
               uploaded_at="2026-10-25T08:28:23+00:00")
    any_store.upsert_document(doc)
    got = any_store.get_document("X1")
    assert got.text == doc.text and got.text_source == "txt" and got.parse_status == "parsed"
    assert (got.storage_path, got.original_filename, got.mime_type) == ("X1/abc/X1.pdf", "X1.pdf", "application/pdf")
    assert got.uploaded_at == "2026-10-25T08:28:23+00:00" and got.ingested_at == doc.ingested_at
    light = any_store.list_documents(include_text=False)[0]
    assert light.text is None and light.storage_path == "X1/abc/X1.pdf"
    assert any_store.find_document_by_sha("abc").doc_id == "X1"
    # unchanged sha: missing columns are filled, present ones kept
    any_store.upsert_document(_doc(storage_path=None))
    assert any_store.get_document("X1").storage_path == "X1/abc/X1.pdf"


def test_json_bool_and_float_columns_round_trip(any_store) -> None:
    any_store.upsert_document(_doc())
    ex = Extraction(doc_id="X1", field_type="payment", field_key="fee", value={"amount": 8000.5, "currency": "USD"},
                    readings=[Reading(interpretation="a", value={"x": 1})], raw_text="r", confidence=0.85,
                    status="ambiguous", run_id="r1")
    ex_id = any_store.add_extraction(ex, [Citation(doc_id="X1", clause_id="X1:1", quote="q" * 10, verified=True,
                                                   match_method="exact", char_start=3, char_end=13)])
    got = any_store.get_extraction(ex_id)
    assert got.value == {"amount": 8000.5, "currency": "USD"} and got.readings[0].value == {"x": 1}
    assert got.is_current is True and got.confidence == 0.85 and isinstance(got.created_at, str)
    cite = any_store.citations_for(ex_id)[0]
    assert cite.verified is True and cite.char_start == 3
    any_store.retire_extraction(ex_id)
    assert any_store.get_extraction(ex_id).is_current is False
    assert any_store.current_extractions("X1") == []


def test_transaction_rolls_back_everything(any_store) -> None:
    """A failure in the middle of a multi-row write leaves nothing behind (no half-writes)."""
    with pytest.raises(RuntimeError):
        with any_store.transaction():
            any_store.upsert_document(_doc())
            any_store.replace_clauses("X1", [Clause(clause_id="X1:1", doc_id="X1", number="1", ref="Section 1",
                                                    text="t", char_start=0, char_end=1)])
            raise RuntimeError("boom")
    assert any_store.get_document("X1") is None
    assert any_store.list_clauses("X1") == []


def test_ingest_bundle_twice_is_idempotent(any_store, cfg) -> None:
    first = ingest_bundle(any_store, cfg, include_pdfs=False)
    n_clauses = sum(len(any_store.list_clauses(d)) for d in DOC_IDS)
    counts = any_store.row_counts()
    second = ingest_bundle(any_store, cfg, include_pdfs=False)
    assert sorted(first.changed_doc_ids) == sorted(DOC_IDS)
    assert second.changed_doc_ids == []
    assert sum(len(any_store.list_clauses(d)) for d in DOC_IDS) == n_clauses == 276
    assert any_store.row_counts() == counts
    assert len(any_store.list_documents()) == 8
    assert all(d.text and d.text_source == "txt" and d.parse_status == "parsed" for d in any_store.list_documents())
    # tables for the later agents
    assert counts["ledger_entries"] == 25 and counts["holidays"] == 10 and counts["clock_checkpoints"] == 4
    assert counts["events"] == 0                       # drops stay unprocessed until Heimdall
    events = any_store.list_resources("events")
    assert len(events) == 2 and all(r.storage_path and r.text is None for r in events)
    context = any_store.get_resource("company/context.txt")
    assert context.text and "Quillhub" in context.text and context.storage_path


def test_document_files_are_stored_once(any_store) -> None:
    any_store.upsert_document(_doc())
    f = DocumentFile(doc_id="X1", role="original", sha256="s1", storage_path="X1/s1/X1.pdf",
                     original_filename="X1.pdf", mime_type="application/pdf", size_bytes=10)
    assert any_store.add_document_file(f) is not None
    assert any_store.add_document_file(f) is None
    assert [x.storage_path for x in any_store.list_document_files("X1")] == ["X1/s1/X1.pdf"]
    assert any_store.find_file_by_sha("s1").doc_id == "X1"


def test_input_tables_are_idempotent(any_store) -> None:
    ledger = [LedgerEntry(line_no=2, date="2026-08-05", from_party="Q", to_party="S", amount=8000.0, reference="r",
                          status="paid", contract_id="QH-STRATO-2026-001")]
    assert any_store.add_ledger(ledger) == 1 and any_store.add_ledger(ledger) == 0
    assert any_store.list_ledger()[0].amount == 8000.0 and any_store.list_ledger()[0].date == "2026-08-05"
    hol = [Holiday(date="2026-12-25", name="Christmas Day", observed_by="All")]
    assert any_store.add_holidays(hol) == 1 and any_store.add_holidays(hol) == 0
    pts = [Checkpoint(idx=0, date="2027-01-15", label="start"), Checkpoint(idx=1, date="2027-03-15", label="checkpoint")]
    assert any_store.add_checkpoints(pts) == 2 and any_store.add_checkpoints(pts) == 0
    assert [p.date for p in any_store.list_checkpoints()] == ["2027-01-15", "2027-03-15"]


def test_relations_are_deduplicated(any_store) -> None:
    rel = DocRelation(from_doc="A1", to_doc="STD", type="incorporates", clause_id="A1:preamble", citation={"q": "x"})
    assert any_store.add_relation(rel) is not None
    assert any_store.add_relation(rel) is None
    rels = any_store.list_relations()
    assert len(rels) == 1 and rels[0].citation == {"q": "x"}


def _responder(system, messages):
    doc = doc_id_of(messages)
    return reply([field("governing_law", "governing_law", {"law": "unknown"},
                        [(f"{doc}:preamble", "THIS QUOTE DOES NOT EXIST ANYWHERE IN THE DOCUMENT")])]
                 + (A3_ALL if doc == "A3" else []))


def test_thor_rerun_skips_unchanged_documents(any_ingested, cfg) -> None:
    llm, provider = make_llm(cfg, _responder)
    Thor(any_ingested, llm, cfg).run(["A3"], workers=1)
    assert any_ingested.get_document("A3").status == "complete"
    calls, rows = len(provider.calls), len(any_ingested.current_extractions("A3"))

    llm2, provider2 = make_llm(cfg, _responder)
    results = Thor(any_ingested, llm2, cfg).run(["A3"], workers=1)
    assert calls >= 1
    assert results[0].skipped and len(provider2.calls) == 0
    assert len(any_ingested.current_extractions("A3")) == rows
    stats = any_ingested.document_stats()["A3"]
    assert stats["fields"] + stats["missing"] == rows and stats["citations_failed"] >= 1


def test_forced_rerun_versions_instead_of_overwriting(any_ingested, cfg) -> None:
    llm, provider = make_llm(cfg, _responder)
    Thor(any_ingested, llm, cfg).run(["A3"], workers=1)
    first_calls = len(provider.calls)
    Thor(any_ingested, llm, cfg).run(["A3"], force=True, workers=1)
    assert len(provider.calls) == first_calls           # identical prompts -> served from the disk cache
    history = any_ingested.extraction_history("A3", "governing_law")
    assert [e.version for e in history] == [1, 2]
    assert [e.is_current for e in history] == [False, True]
    assert history[1].supersedes_id == history[0].id


def test_export_covers_every_table(any_store) -> None:
    any_store.upsert_document(_doc(text="body"))
    out = any_store.export()
    assert set(TABLES) <= set(out) and out["backend"] == any_store.backend
    assert "text" not in out["documents"][0]


# --------------------------------------------------------------------------- backend-specific


def test_unreachable_postgres_fails_with_a_clear_message() -> None:
    pytest.importorskip("psycopg")
    from odin.state.postgres import PostgresStateStore

    with pytest.raises(StoreUnavailable) as err:
        PostgresStateStore("postgresql://odin:s3cr3t%40pw@127.0.0.1:1/odin", retries=1, backoff_s=0.0,
                           connect_timeout_s=2, sleep=lambda s: None)
    msg = str(err.value)
    assert "STATE_BACKEND=sqlite" in msg and "127.0.0.1:1" in msg
    assert "s3cr3t" not in msg and "2 attempt(s)" in msg


def test_sqlite_upgrades_a_step1_database_in_place(tmp_path) -> None:
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT NOT NULL, text_title TEXT, path TEXT NOT NULL,
            sha256 TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', status_reason TEXT,
            coverage REAL, external_id TEXT, source TEXT NOT NULL DEFAULT 'bundle', extracted_sha256 TEXT,
            ingested_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO documents VALUES ('A1','t',NULL,'contracts/A1.txt','abc','contract','complete',NULL,100,NULL,
            'bundle','abc','2026-10-25T08:28:23+00:00','2026-10-25T08:28:23+00:00');
        CREATE TABLE resources (path TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT, sha256 TEXT NOT NULL,
            loaded_at TEXT NOT NULL);
        CREATE TABLE ledger (id INTEGER PRIMARY KEY);
        CREATE TABLE checkpoints (idx INTEGER PRIMARY KEY);
    """)
    conn.close()
    s = SQLiteStateStore(path)
    doc = s.get_document("A1")
    assert doc.status == "complete" and doc.text is None and doc.storage_path is None
    assert s.row_counts()["ledger_entries"] == 0
    s.close()
    names = {r[0] for r in sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ledger" not in names and "checkpoints" not in names and "document_files" in names

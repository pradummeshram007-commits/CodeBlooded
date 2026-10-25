from __future__ import annotations

from odin.agents.thor import Thor
from odin.ingest.loader import ingest_bundle
from odin.state.models import DocRelation, Document

from .conftest import DOC_IDS, doc_id_of, field, make_llm, reply


def _doc(sha: str = "abc") -> Document:
    return Document(doc_id="X1", title="t", path="contracts/X1.txt", sha256=sha, kind="contract")


def test_upsert_unchanged_document_is_a_noop(store) -> None:
    assert store.upsert_document(_doc()) is True
    assert store.upsert_document(_doc()) is False
    assert len(store.list_documents()) == 1


def test_needs_extraction_lifecycle(store) -> None:
    store.upsert_document(_doc("v1"))
    assert store.needs_extraction("X1")
    store.set_document_status("X1", "complete", coverage=100.0, extracted_sha256="v1")
    assert not store.needs_extraction("X1")
    store.upsert_document(_doc("v2"))                 # text changed -> back to pending
    assert store.get_document("X1").status == "pending"
    assert store.needs_extraction("X1")


def test_ingest_bundle_twice_is_idempotent(store, cfg) -> None:
    first = ingest_bundle(store, cfg)
    n_clauses = sum(len(store.list_clauses(d)) for d in DOC_IDS)
    second = ingest_bundle(store, cfg)
    assert sorted(first.changed_doc_ids) == sorted(DOC_IDS)
    assert second.changed_doc_ids == []
    assert sum(len(store.list_clauses(d)) for d in DOC_IDS) == n_clauses
    assert len(store.list_documents()) == 8


def test_relations_are_deduplicated(store) -> None:
    rel = DocRelation(from_doc="A1", to_doc="STD", type="incorporates", clause_id="A1:preamble")
    assert store.add_relation(rel) is not None
    assert store.add_relation(rel) is None
    assert len(store.list_relations()) == 1


def _responder(system, messages):
    doc = doc_id_of(messages)
    return reply([field("governing_law", "governing_law", {"law": "unknown"},
                        [(f"{doc}:preamble", "THIS QUOTE DOES NOT EXIST ANYWHERE IN THE DOCUMENT")])])


def test_thor_rerun_skips_unchanged_documents(ingested, cfg) -> None:
    llm, provider = make_llm(cfg, _responder)
    Thor(ingested, llm, cfg).run(["A3"], workers=1)
    assert ingested.get_document("A3").status == "complete"
    calls, rows = len(provider.calls), len(ingested.current_extractions("A3"))

    llm2, provider2 = make_llm(cfg, _responder)
    results = Thor(ingested, llm2, cfg).run(["A3"], workers=1)
    assert calls >= 1
    assert results[0].skipped and len(provider2.calls) == 0
    assert len(ingested.current_extractions("A3")) == rows


def test_forced_rerun_versions_instead_of_overwriting(ingested, cfg) -> None:
    llm, provider = make_llm(cfg, _responder)
    Thor(ingested, llm, cfg).run(["A3"], workers=1)
    first_calls = len(provider.calls)
    Thor(ingested, llm, cfg).run(["A3"], force=True, workers=1)
    assert len(provider.calls) == first_calls           # identical prompts -> served from the disk cache
    history = ingested.extraction_history("A3", "governing_law")
    assert [e.version for e in history] == [1, 2]
    assert [e.is_current for e in history] == [False, True]
    assert history[1].supersedes_id == history[0].id

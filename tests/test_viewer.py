"""Contract viewer: clause split, fields next to the clauses they cite, deep-link highlighting."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from odin.agents.thor import Thor
from odin.ingest.upload import ingest_file
from odin.state.backend import open_file_store
from odin.viewer import contract_link, get_contract_view, render_clauses_html

from .conftest import doc_id_of, field, make_llm, reply

QUOTE = "If this Cover Page and the\nStandard Terms conflict on any point, this Cover Page controls."


def _responder(system, messages):
    if doc_id_of(messages) != "A1":
        return reply([])
    return reply([
        field("governing_law", "precedence", {"law": None}, [("A1:preamble", QUOTE)], confidence=0.9),
        field("party", "provider", {"name": "StratoNode Inc.", "role": "provider"},
              [("A1:provider-information", "Legal Name: StratoNode Inc.")], confidence=0.95),
        field("payment", "invented_fee", {"amount": 1.0}, [("A1:C", "a fee that is nowhere in the contract")],
              confidence=0.8),
    ])


@pytest.fixture
def a1(store, cfg):
    files = open_file_store(cfg)
    bundle = cfg.paths.bundle_dir / "contracts"
    ingest_file((bundle / "A1.txt").read_bytes(), "A1.txt", store=store, files=files, cfg=cfg, extract=False)
    ingest_file((bundle / "A1.pdf").read_bytes(), "A1.pdf", store=store, files=files, cfg=cfg, extract=False)
    llm, _ = make_llm(cfg, _responder)
    Thor(store, llm, cfg).run(["A1"], workers=1)
    return store, files, cfg


def test_view_has_metadata_original_clauses_and_badges(a1) -> None:
    store, files, cfg = a1
    view = get_contract_view("A1", store=store, files=files, cfg=cfg)
    assert view.doc["doc_id"] == "A1" and view.doc["text_source"] == "txt" and view.doc["clauses"] == 16
    assert view.original["available"] and view.original["mime_type"] == "application/pdf"
    assert view.original["url"] is None              # local file store: the page reads the bytes instead
    assert files.download(view.original["storage_path"])[:5] == b"%PDF-"
    # own ranges partition the text: every clause character is shown exactly once
    shown = sum(e - s for v in view.clauses for s, e in v.own)
    top = [v for v in view.clauses if v.parent_id is None]
    assert shown == sum(v.char_end - v.char_start for v in top)
    pre = view.clause("A1:preamble")
    keys = {b.field_key: b for b in pre.fields}
    assert keys["precedence"].verified and keys["precedence"].confidence == 0.9
    fee = next(b for b in view.fields if b.field_key == "invented_fee")
    assert not fee.verified and fee.confidence <= 0.3   # Thor caps unverified citations


def test_deep_link_highlights_the_cited_quote(a1) -> None:
    store, files, cfg = a1
    view = get_contract_view("A1", "A1:preamble", "this Cover Page controls", store=store, files=files, cfg=cfg)
    t = view.target
    assert t["found"] and t["clause_id"] == "A1:preamble" and t["quote"] == "this Cover Page controls"
    assert view.text[t["char_start"]:t["char_end"]] == "this Cover Page controls"
    page = render_clauses_html(view)
    assert '<mark class="target">this Cover Page controls</mark>' in page
    assert 'id="clause-A1:preamble"' in page and "scrollIntoView" in page and '"clause-A1:preamble"' in page


def test_deep_link_tolerates_whitespace_and_finds_moved_quotes(a1) -> None:
    store, files, cfg = a1
    view = get_contract_view("A1", "A1:preamble", "If this Cover Page and the Standard Terms conflict",
                             store=store, files=files, cfg=cfg)
    assert view.target["found"] and "\n" in view.target["quote"]        # matched across the hard line wrap
    moved = get_contract_view("A1", "A1:preamble", "Legal Name: StratoNode Inc.", store=store, files=files, cfg=cfg)
    assert moved.target["found"] and moved.target["clause_id"] == "A1:provider-information"
    assert "not in A1:preamble" in moved.target["note"]
    bad = get_contract_view("A1", "A1:Z9", None, store=store, files=files, cfg=cfg)
    assert not bad.target["found"] and "not a clause" in bad.target["note"]


def test_clause_only_link_marks_the_clause(a1) -> None:
    store, files, cfg = a1
    view = get_contract_view("A1", "B", store=store, files=files, cfg=cfg)   # "Section B" style ref resolves
    assert view.target["clause_id"] == "A1:B" and view.clause("A1:B").is_target
    assert 'class="row target" id="clause-A1:B"' in render_clauses_html(view)


def test_contract_link_round_trips() -> None:
    url = contract_link("A1", "A1:4.2", "within thirty (30) days")
    q = parse_qs(urlsplit(url).query)
    assert urlsplit(url).path == "/Contracts" and q == {"doc": ["A1"], "clause": ["A1:4.2"],
                                                         "quote": ["within thirty (30) days"]}


def test_unknown_document_raises(store, cfg) -> None:
    with pytest.raises(LookupError):
        get_contract_view("NOPE", store=store, files=open_file_store(cfg), cfg=cfg)

from __future__ import annotations

import pytest

from odin.config import load_config
from odin.ingest.loader import read_text_exact
from odin.ingest.segmenter import segment

from .conftest import DOC_IDS

CONTRACTS = load_config(env={}).paths.bundle_dir / "contracts"


def _seg(doc_id: str):
    text = read_text_exact(CONTRACTS / f"{doc_id}.txt")
    return text, segment(doc_id, text)


@pytest.mark.parametrize("doc_id", DOC_IDS)
def test_every_document_segments_by_its_own_numbering(doc_id: str) -> None:
    text, seg = _seg(doc_id)
    assert seg.method == "numbered"
    assert seg.warnings == []          # also asserts no substantive text falls outside every clause
    ids = [c.clause_id for c in seg.clauses]
    assert len(ids) == len(set(ids))
    by_id = seg.by_id()
    for c in seg.clauses:
        assert c.clause_id.startswith(f"{doc_id}:")
        assert text[c.char_start:c.char_end] == c.text           # exact offsets
        assert c.text == c.text.strip() and c.text
        if c.level == 2:
            parent = by_id[c.parent_id]
            assert parent.char_start <= c.char_start and c.char_end <= parent.char_end


EXPECTED = {
    "STD": ["STD:preamble", "STD:using-this-agreement", "STD:1", "STD:1.1", "STD:3.3", "STD:5.1", "STD:12.10",
            "STD:13.1", "STD:13.28"],
    "A1": ["A1:preamble", "A1:provider-information", "A1:customer-information", "A1:B", "A1:C", "A1:E", "A1:I",
           "A1:I.1", "A1:I.3", "A1:signatures"],
    "A2": ["A2:preamble", "A2:1.3", "A2:2.1", "A2:3.1", "A2:3.2", "A2:5", "A2:5.5", "A2:6.1", "A2:closing"],
    "A3": ["A3:preamble", "A3:amendment-effective-date", "A3:1", "A3:2", "A3:3", "A3:closing", "A3:signatures"],
    "B1": ["B1:D", "B1:3.1", "B1:3.5", "B1:4.2", "B1:5.1", "B1:6.1", "B1:7.2", "B1:8.2", "B1:J", "B1:K"],
    "B2": ["B2:preamble", "B2:3.1", "B2:4.2", "B2:8.1", "B2:signatures", "B2:note"],
    "C1": ["C1:B", "C1:C", "C1:3.1", "C1:4.1", "C1:F", "C1:H.1", "C1:H.3", "C1:note"],
    "D1": ["D1:preamble", "D1:3.1", "D1:4.2", "D1:9.1", "D1:10.9", "D1:ExA", "D1:ExA.M1", "D1:ExA.M5",
           "D1:ExA.acceptance-criteria", "D1:signatures"],
}


@pytest.mark.parametrize("doc_id", DOC_IDS)
def test_expected_clauses_present(doc_id: str) -> None:
    _, seg = _seg(doc_id)
    ids = {c.clause_id for c in seg.clauses}
    missing = [i for i in EXPECTED[doc_id] if i not in ids]
    assert not missing


def test_quoted_replacement_text_is_not_split_into_clauses() -> None:
    # A3 quotes the new SLA §3.1/§3.2 wording; those numbers belong to A2, not to A3.
    _, seg = _seg("A3")
    ids = {c.clause_id for c in seg.clauses}
    assert "A3:3.1" not in ids and "A3:3.2" not in ids
    assert "fifteen\n        (15) days" in seg.by_id()["A3:1"].text


def test_clause_refs_follow_each_documents_style() -> None:
    _, b1 = _seg("B1")
    _, a1 = _seg("A1")
    _, std = _seg("STD")
    assert b1.by_id()["B1:3.1"].ref == "§3.1"
    assert b1.by_id()["B1:3.1"].heading == "Uptime Commitment"
    assert b1.by_id()["B1:3.1"].parent_id == "B1:D"
    assert a1.by_id()["A1:C"].ref == "Section C"
    assert std.by_id()["STD:4.4"].heading == "Late Payment"
    assert std.by_id()["STD:13.16"].heading == '"Non-Renewal Notice Period"'


def test_banners_are_not_clauses() -> None:
    for doc_id in DOC_IDS:
        _, seg = _seg(doc_id)
        assert not any(c.text.lstrip().startswith("END OF") for c in seg.clauses)
        assert not any(c.text.strip() == "KEY TERMS" for c in seg.clauses)


def test_unstructured_text_falls_back_to_paragraphs() -> None:
    text = "Just some prose.\nNo numbering here.\n\nA second paragraph\nwith two lines.\n\n\nThird."
    seg = segment("X1", text)
    assert seg.method == "paragraph" and seg.unparseable
    assert [c.clause_id for c in seg.clauses] == ["X1:p1", "X1:p2", "X1:p3"]
    for c in seg.clauses:
        assert text[c.char_start:c.char_end] == c.text


@pytest.mark.parametrize("text", ["", "   \n\n  ", "\x00\x01\x02 binary-ish �", "=" * 80 + "\n" + "-" * 80])
def test_segmenter_never_crashes(text: str) -> None:
    seg = segment("Z9", text)
    assert seg.method in ("numbered", "paragraph")

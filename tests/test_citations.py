from __future__ import annotations

import pytest

from odin.citations import ClauseIndex, find_quote, verify_citation
from odin.config import load_config
from odin.ingest.loader import read_text_exact
from odin.ingest.segmenter import segment
from odin.state.models import Clause

CONTRACTS = load_config(env={}).paths.bundle_dir / "contracts"


@pytest.fixture(scope="module")
def b1() -> ClauseIndex:
    text = read_text_exact(CONTRACTS / "B1.txt")
    seg = segment("B1", text)
    clauses = [Clause(**{k: getattr(c, k) for k in Clause.model_fields}) for c in seg.clauses]
    return ClauseIndex("B1", clauses, text)


def test_exact_match_passes(b1: ClauseIndex) -> None:
    quote = "Payment Period:  45 days from invoice date."
    c = verify_citation(b1, "B1:C", quote)
    assert c.verified and c.match_method == "exact"
    assert b1.doc_text[c.char_start:c.char_end] == quote
    assert c.clause_id == "B1:C" and c.clause_ref == "Section C"


def test_whitespace_variant_passes_and_maps_to_original_offsets(b1: ClauseIndex) -> None:
    # In the file this wording spans a line break plus 8 spaces of indentation.
    quote = "Quillhub will notify Harbor Retail's General Counsel within twenty-four (24) hours"
    assert quote not in b1.doc_text
    c = verify_citation(b1, "§5.1", quote)
    assert c.verified and c.match_method == "normalized"
    assert c.clause_id == "B1:5.1"
    exact = b1.doc_text[c.char_start:c.char_end]
    assert exact == c.quote and exact in b1.doc_text        # stored quote is findable by plain search
    assert "Counsel\n        within" in exact


def test_case_and_curly_quote_variants_pass(b1: ClauseIndex) -> None:
    c = verify_citation(b1, "B1:3.1", "THE “HARBOR UPTIME TARGET”")
    assert c.verified and c.match_method == "normalized"
    assert c.quote == 'the "Harbor Uptime\n        Target"'


def test_swapped_quote_marks_pass(b1: ClauseIndex) -> None:
    # Text: (the "Harbor Uptime\n        Target")
    c = verify_citation(b1, "B1:3.1", "not counting Scheduled Maintenance (the 'Harbor Uptime Target')")
    assert c.verified and '"Harbor Uptime' in c.quote          # stored with the file's own characters


def test_added_trailing_period_passes(b1: ClauseIndex) -> None:
    # Text continues "... of the Monthly Fee for that month": the model's period is not in the file.
    c = verify_citation(b1, "B1:3.3", "Quillhub will credit Harbor Retail fifteen percent (15%) of the Monthly Fee.")
    assert c.verified and c.quote.endswith("Monthly Fee")


def test_dropped_words_still_fail(b1: ClauseIndex) -> None:
    # The file says "within forty-five (45) days"; dropping "(45)" is a paraphrase, not a quote.
    c = verify_citation(b1, "B1:3.5", "Harbor Retail must request a service credit in writing within forty-five days")
    assert not c.verified


def test_fabricated_quote_fails(b1: ClauseIndex) -> None:
    c = verify_citation(b1, "B1:3.3", "Quillhub will credit Harbor Retail thirty percent (30%) of the Monthly Fee")
    assert not c.verified and c.match_method == "none"
    assert c.char_start is None and c.clause_id == "B1:3.3"


def test_ellipsis_quote_is_not_verbatim(b1: ClauseIndex) -> None:
    c = verify_citation(b1, "B1:5.1", "Quillhub will notify ... within twenty-four (24) hours")
    assert not c.verified


def test_section_citation_is_refined_to_the_sub_clause(b1: ClauseIndex) -> None:
    c = verify_citation(b1, "Section D", "twenty percent (20%) of the Monthly Fee for that month")
    assert c.verified and c.clause_id == "B1:3.4" and c.clause_ref == "§3.4"


def test_wrong_clause_is_reattributed_when_quote_is_unique(b1: ClauseIndex) -> None:
    c = verify_citation(b1, "B1:3.1", "State of Washington")
    assert c.verified and c.match_method == "reattributed"
    assert c.clause_id == "B1:K" and c.llm_clause_id == "B1:3.1"


def test_reattribution_respects_restriction(b1: ClauseIndex) -> None:
    c = verify_citation(b1, "B1:3.1", "State of Washington", restrict_to={"B1:3.1"})
    assert not c.verified


def test_ambiguous_quote_outside_cited_clause_fails(b1: ClauseIndex) -> None:
    # Occurs in §3.3 and §3.4, not in the cited clause: re-attribution would be a guess.
    c = verify_citation(b1, "B1:K", "of the Monthly Fee for that month")
    assert not c.verified and c.clause_id == "B1:K"


def test_too_short_quote_fails() -> None:
    assert not find_quote("30", "thirty (30) days").found

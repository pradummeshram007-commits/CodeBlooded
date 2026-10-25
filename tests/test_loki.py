"""Loki's code checks on scripted replies (FakeProvider: no real LLM call)."""
from __future__ import annotations

import json

from odin.agents.loki import Loki

from .conftest import doc_id_of, make_llm

AS_OF = "2027-03-15"
REAL = "overdue amounts accrue interest at 1.5% per month"   # A1 §C, verbatim
CAP = "The total Fees paid or payable by Customer in the\n                       twelve (12) months"  # A1 §G


def finding(type_: str, title: str, cites: list[tuple[str, str]], steps: list[str], severity: str = "high",
            readings: list[str] = ()) -> dict:
    return {"type": type_, "title": title, "citations": [{"clause_id": c, "quote": q} for c, q in cites],
            "readings": [{"reading": r, "counterparty_argues": i == 0} for i, r in enumerate(readings)],
            "attack_path": steps, "severity": severity, "severity_reason": "per the scale", "likelihood": "high",
            "likelihood_reason": "routine invoicing", "confidence": 0.8}


def review(store, cfg, findings: list[dict]) -> dict[str, object]:
    def responder(system, messages):
        assert doc_id_of(messages) == "A1"
        return json.dumps({"findings": findings})

    llm, _ = make_llm(cfg, responder)
    [r] = Loki(store, llm, cfg).run(["A1"], AS_OF)
    assert r.status == "complete"
    return {f.title: f for f in store.list_loki_findings("A1", AS_OF)}


def test_fabricated_quote_is_rejected_and_real_quote_accepted(ingested, cfg) -> None:
    replies = [
        finding("hidden_liability", "Late interest starts the day after due date",
                [("A1:C", REAL)], ["Under A1:C StratoNode charges 1.5% per month", "It adds the interest under A1:C"]),
        finding("one_sided", "Weekly fee", [("A1:C", "Monthly Fee: $9,500.00 payable weekly")],
                ["Under A1:C StratoNode bills weekly", "Quillhub overpays under A1:C"]),
    ]
    out = review(ingested, cfg, replies)
    good, bad = out["Late interest starts the day after due date"], out["Weekly fee"]
    assert good.status == "accepted" and good.citations[0].verified
    text = ingested.get_document("A1").text
    assert good.citations[0].quote == REAL == text[good.citations[0].char_start:good.citations[0].char_end]
    assert bad.status == "rejected" and bad.rejection_reason.startswith("no verified citation")
    assert not bad.citations and "quote not found" in bad.notes[0]

    review(ingested, cfg, replies)                    # a re-run for the same document and date replaces, not appends
    assert len(ingested.list_loki_findings("A1", AS_OF)) == 2


def test_invented_clause_id_is_rejected(ingested, cfg) -> None:
    out = review(ingested, cfg, [
        finding("one_sided", "Interest on disputed amounts", [("A1:C", REAL)],
                ["Under A1:Z.9 StratoNode may charge interest", "It collects under A1:C"]),
        finding("one_sided", "Interest from the due date", [("A1:C", REAL)],
                ["Under A1:C interest runs from the due date", "It collects under A1:C"]),
    ])
    assert out["Interest on disputed amounts"].status == "rejected"
    assert "do not exist: A1:Z.9" in out["Interest on disputed amounts"].rejection_reason
    assert out["Interest from the due date"].status == "accepted"


def test_invented_number_is_rejected(ingested, cfg) -> None:
    out = review(ingested, cfg, [
        finding("hidden_liability", "Late interest of 2% per month", [("A1:C", REAL)],
                ["Under A1:C StratoNode charges interest", "It compounds monthly under A1:C"]),
        finding("hidden_liability", "Late interest of 1.5% per month", [("A1:C", REAL)],
                ["Under A1:C StratoNode charges interest", "After 30 days it suspends under A1:C"]),
    ])
    assert out["Late interest of 2% per month"].status == "rejected"
    assert "not in the cited clauses: 2%" in out["Late interest of 2% per month"].rejection_reason
    # "30 days" is not in A1 §C's interest sentence but is in A1 §C ("Payment Period: 30 days"): the whole clause counts.
    assert out["Late interest of 1.5% per month"].status == "accepted"


def test_duplicates_are_merged(ingested, cfg) -> None:
    out = review(ingested, cfg, [
        finding("one_sided", "Cap counts only twelve months of fees", [("A1:G", CAP)],
                ["Under A1:G the cap is the fees of the prior months", "Claims above it fail under A1:G"],
                severity="medium"),
        finding("one_sided", "Liability cap shrinks early in the term", [("A1:G", "immediately preceding the claim")],
                ["Under A1:G an early claim meets a small cap", "StratoNode pays little under A1:G"],
                severity="critical"),
    ])
    kept, merged = out["Liability cap shrinks early in the term"], out["Cap counts only twelve months of fees"]
    assert kept.status == "accepted" and kept.severity == "critical" and kept.rank == 1
    assert {c.quote for c in kept.citations} >= {"immediately preceding the claim"} and len(kept.citations) == 2
    assert merged.status == "rejected" and merged.rejection_reason.startswith("duplicate of")
    status = {w.id: w.agent_status for w in ingested.list_workstreams()}
    assert status.get("ws:A1", {}).get("loki:A1") == "complete"

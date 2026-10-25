"""Norns on a tiny hand-made contract (Z1 + amendment Z2): calendar, rules, ledger, clock, worst case. No LLM."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from odin.effective import effective_clause
from odin.norns.calendar import BusinessCalendar, add_months, month_end, months_between
from odin.norns.engine import Norns
from odin.norns.worst_case import worst_case
from odin.norns.writeup import check_numbers, summary_for_llm, template_writeup
from odin.state.models import (
    Checkpoint,
    Citation,
    Clause,
    DocRelation,
    Document,
    Extraction,
    Holiday,
    LedgerEntry,
)

Z1 = """Z1 TEST AGREEMENT
CONTRACT ID: QH-Z-2027-001
This Agreement is between Vendor Co ("Provider") and Quillhub Inc. ("Customer").

Section B - Term
  Effective Date: January 1, 2027. Initial term 12 months (ending December 31, 2027).
  Renews for 12 months unless notice is given at least 30 calendar days before the end of the term.

Section C - Fees
  Monthly Fee: $1,000.00. Invoices on the first business day of each calendar month.
  Payment Period: 30 days from invoice date. Overdue amounts accrue interest at 1.5% per month.
"""
Z2 = """Z2 AMENDMENT TO Z1 (CONTRACT ID: QH-Z-2027-001)
Section 1 - Notice
  Section B of the Agreement is amended: notice at least 15 calendar days before the end of the term.
AMENDMENT EFFECTIVE DATE: June 1, 2027
"""
HOLIDAYS = [("2027-01-01", "New Year's Day", "All"), ("2027-01-20", "Martin Luther King Jr. Day", "All"),
            ("2027-07-05", "Independence Day (Observed)", "All"), ("2027-12-24", "Christmas Eve", "Quillhub")]


def _clause(doc_id: str, text: str, cid: str, start_marker: str, end_marker: str | None, ordinal: int) -> Clause:
    s = text.index(start_marker)
    e = text.index(end_marker) if end_marker else len(text)
    return Clause(clause_id=f"{doc_id}:{cid}", doc_id=doc_id, number=cid, ref=f"Section {cid}", text=text[s:e],
                  char_start=s, char_end=e, ordinal=ordinal)


def _ex(store, doc_id: str, text: str, clause_id: str, field_type: str, key: str, value: dict, quote: str) -> int:
    s = text.index(quote)
    return store.add_extraction(
        Extraction(doc_id=doc_id, field_type=field_type, field_key=key, value=value, confidence=0.95, status="extracted"),
        [Citation(doc_id=doc_id, clause_id=clause_id, quote=quote, verified=True, char_start=s, char_end=s + len(quote),
                  match_method="exact")])


def build(store, *, amended: bool = True, ledger: bool = True) -> None:
    store.upsert_document(Document(doc_id="Z1", title="Z1", path="Z1.txt", sha256="z1", kind="contract", text=Z1,
                                   external_id="QH-Z-2027-001", status="complete"))
    store.replace_clauses("Z1", [_clause("Z1", Z1, "preamble", "Z1 TEST", "Section B", 0),
                                 _clause("Z1", Z1, "B", "Section B", "Section C", 1), _clause("Z1", Z1, "C", "Section C", None, 2)])
    _ex(store, "Z1", Z1, "Z1:preamble", "party", "party_provider", {"name": "Vendor Co", "role": "Provider"}, "Vendor Co")
    _ex(store, "Z1", Z1, "Z1:preamble", "party", "party_customer", {"name": "Quillhub Inc.", "role": "Customer"}, "Quillhub Inc.")
    _ex(store, "Z1", Z1, "Z1:B", "effective_date", "effective_date", {"raw": "January 1, 2027", "iso": "2027-01-01"},
        "Effective Date: January 1, 2027")
    _ex(store, "Z1", Z1, "Z1:B", "term", "term", {"start_iso": "2027-01-01", "end_iso": "2027-12-31", "duration_months": 12},
        "Initial term 12 months (ending December 31, 2027)")
    _ex(store, "Z1", Z1, "Z1:B", "renewal", "renewal",
        {"auto_renew": True, "renewal_term_months": 12, "notice_period_days": 30,
         "notice_period_raw": "at least 30 calendar days before the end of the term"},
        "notice is given at least 30 calendar days before the end of the term")
    _ex(store, "Z1", Z1, "Z1:C", "payment", "monthly_fee",
        {"item": "Monthly Fee", "amount": 1000.0, "currency": "USD", "payment_period_days": 30,
         "due_rule": "30 days from invoice date", "invoice_rule": "on the first business day of each calendar month",
         "interest_rate_raw": "1.5% per month"},
        "Monthly Fee: $1,000.00. Invoices on the first business day of each calendar month.")
    if amended:
        store.upsert_document(Document(doc_id="Z2", title="Z2", path="Z2.txt", sha256="z2", kind="amendment", text=Z2,
                                       status="complete"))
        store.replace_clauses("Z2", [_clause("Z2", Z2, "1", "Section 1", "AMENDMENT EFFECTIVE", 0)])
        _ex(store, "Z2", Z2, "Z2:1", "renewal", "renewal",
            {"auto_renew": True, "renewal_term_months": 12, "notice_period_days": 15,
             "notice_period_raw": "at least 15 calendar days before the end of the term"},
            "notice at least 15 calendar days before the end of the term")
        quote = "Section B of the Agreement is amended"
        store.add_relation(DocRelation(from_doc="Z2", to_doc="Z1", type="amends", clause_id="Z2:1", raised_by="thor",
                                       verified=True, citation={"clause_id": "Z2:1", "quote": quote, "verified": True,
                                                                "target_clause_id": "Z1:B", "operation": "modify",
                                                                "effective_date": "2027-06-01"}))
    store.add_holidays([Holiday(date=d, name=n, observed_by=o) for d, n, o in HOLIDAYS])
    store.add_checkpoints([Checkpoint(idx=i, date=d, label="start" if i == 0 else "checkpoint")
                           for i, d in enumerate(["2027-01-15", "2027-03-15", "2027-06-01", "2027-09-15"])])
    if ledger:
        rows = [  # (line, date, amount, reference)
            (2, "2027-01-20", 1000.0, "January 2027 fee - QH-Z-2027-001"),      # due 2027-02-03: on time
            (3, "2027-03-10", 1000.0, "February 2027 fee - QH-Z-2027-001"),     # due 2027-03-03: late
            (4, "2027-03-20", 400.0, "March 2027 fee - QH-Z-2027-001"),         # due 2027-03-31: partial
            (5, "2027-04-02", 999.0, "Consulting - QH-Z-2027-001"),              # matches nothing: flagged, kept
        ]                                                                        # April: never paid
        store.add_ledger([LedgerEntry(line_no=n, date=d, from_party="Quillhub Inc.", to_party="Vendor Co", amount=a,
                                      reference=r, status="paid", contract_id="QH-Z-2027-001") for n, d, a, r in rows])


@pytest.fixture
def norns(store, cfg):
    build(store)
    cfg.norns.projection_months = 3
    return Norns(store, None, cfg, contracts=["Z1"])


# --------------------------------------------------------------------------- calendar


def test_business_days_across_a_holiday() -> None:
    cal = BusinessCalendar([Holiday(date=d, name=n, observed_by=o) for d, n, o in HOLIDAYS])
    assert cal.add_business_days(date(2027, 1, 19), 1) == date(2027, 1, 21)                  # Jan 20 is a holiday
    assert cal.first_business_day(2027, 1) == date(2027, 1, 4)                                # Jan 1 holiday + weekend
    assert cal.add_business_days(date(2027, 6, 30), 5, ("All", "Quillhub")) == date(2027, 7, 8)  # Jul 5 skipped
    assert cal.add_business_days(date(2027, 12, 23), 1, ("All", "Quillhub")) == date(2027, 12, 27)  # Quillhub's Dec 24
    assert cal.add_business_days(date(2027, 12, 23), 1, ("All",)) == date(2027, 12, 24)        # not someone else's
    dc = cal.count(date(2027, 1, 4), 30, day_type="unspecified")
    assert dc.calendar == date(2027, 2, 3) and dc.business == date(2027, 2, 16) and dc.chosen == date(2027, 2, 3)
    assert "earlier" in dc.flags[0]


def test_month_end_rollover() -> None:
    assert add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert month_end(date(2028, 2, 10)) == date(2028, 2, 29)
    assert months_between(date(2027, 1, 31), date(2027, 2, 28)) == Decimal(1)
    assert months_between(date(2027, 3, 31), date(2027, 9, 1)) == Decimal(5) + Decimal(1) / Decimal(30)


# --------------------------------------------------------------------------- rules + amendment


def test_renewal_notice_deadline_before_and_after_the_amendment(store, cfg) -> None:
    build(store)
    def notice(day: str) -> int:
        terms = effective_clause("Z1", "Z1:B", day, store=store).terms
        return next(t for t in terms if t.field_type == "renewal").value["notice_period_days"]

    assert notice("2027-05-31") == 30 and notice("2027-06-01") == 15
    t = Norns(store, None, cfg, contracts=["Z1"]).compute("2027-03-15")
    ren = t.renewal_deadlines()["Z1"]
    assert ren["due"] == "2027-12-16"                         # 15 calendar days before 2027-12-31: the amended term
    assert any("version in force on the deadline" in f for f in ren["flags"])


def test_renewal_notice_deadline_without_the_amendment(store, cfg) -> None:
    build(store, amended=False)
    t = Norns(store, None, cfg, contracts=["Z1"]).compute("2027-03-15")
    assert t.renewal_deadlines()["Z1"]["due"] == "2027-12-01"  # 30 calendar days before 2027-12-31


def test_fee_rule_cites_its_extraction(norns) -> None:
    norns.load()
    [fee] = [r for r in norns.rules if r.kind == "payment"]
    assert fee.amount == Decimal("1000.00") and fee.offset_amount == 30 and fee.day_type == "unspecified"
    assert fee.citations[0]["clause_id"] == "Z1:C" and fee.citations[0]["verified"]
    assert {"type": "interest", "rate_per_month": "0.015"}.items() <= next(
        e for e in fee.escalations if e["type"] == "interest").items()


# --------------------------------------------------------------------------- ledger


def test_ledger_matching_on_time_late_partial_missing(norns) -> None:
    t = norns.compute("2027-06-01")
    by = {i.period: i for i in t.payments()}
    assert by["2027-01"].status == "paid_on_time" and by["2027-01"].due == date(2027, 2, 3)
    assert by["2027-02"].status == "paid_late" and by["2027-02"].due == date(2027, 3, 3)
    assert by["2027-02"].interest_to_as_of == Decimal("3.50")    # 1000 x 1.5% x 7/30 month (Mar 3 -> Mar 10)
    assert by["2027-03"].status == "partial" and by["2027-03"].outstanding == Decimal("600.00")
    assert by["2027-04"].status == "unpaid" and by["2027-04"].due == date(2027, 5, 1)
    assert by["2027-05"].status == "upcoming"
    [unmatched] = t.unmatched_ledger
    assert unmatched["line_no"] == 5 and unmatched["amount"] == "999.00"     # kept and flagged, never dropped


# --------------------------------------------------------------------------- clock


def test_no_future_leakage(norns) -> None:
    early = norns.compute("2027-03-05").fingerprint()
    norns.compute("2027-09-15")                                   # moving the clock forward, then back...
    assert norns.compute("2027-03-05").fingerprint() == early     # ...changes nothing in the past
    t = norns.compute("2027-03-05")
    feb = next(i for i in t.payments() if i.period == "2027-02")
    assert feb.status == "unpaid" and feb.paid_amount == 0        # the 2027-03-10 payment is not known yet
    assert norns.compute("2027-03-15").payments()[1].status == "paid_late"


def test_compute_is_deterministic(norns) -> None:
    assert norns.compute("2027-06-01").fingerprint() == norns.compute("2027-06-01").fingerprint()


# --------------------------------------------------------------------------- worst case


def test_worst_case_totals_match_hand_computation(norns) -> None:
    t = norns.compute("2027-06-01")
    wc = worst_case(norns, t)
    assert wc.projection_end == date(2027, 9, 1)
    interest = {a.inputs["from"]: a.amount for a in wc.accruals if a.scenario == "worst_case" and a.category == "late_interest"}
    # principal x 1.5% x months from the due date to 2027-09-01 (part months = days/30)
    assert interest == {
        "2027-03-31": Decimal("45.30"),     # March: 600.00 outstanding, 5 months + 1 day
        "2027-05-01": Decimal("60.00"),     # April: 1000.00, 4 months
        "2027-06-02": Decimal("45.00"),     # May (invoiced Mon 2027-05-03): 2 months + 30 days
        "2027-07-01": Decimal("30.00"),     # June: 2 months
        "2027-07-31": Decimal("15.50"),     # July: 1 month + 1 day
    }
    assert wc.total("worst_case") == Decimal("195.80")
    # Acting on time stops interest on what is already late, but cannot undo what accrued before 2027-06-01:
    # March 600 x 1.5% x (2 months + 1 day) = 18.30; April 1000 x 1.5% x 1 month = 15.00.
    assert wc.total("on_time") == Decimal("33.30") and wc.avoidable == Decimal("162.50")
    assert all(a.citations and a.formula and a.inputs for a in wc.accruals)
    chart = wc.chart_data()
    assert chart["cumulative_exposure"][-1] == {"date": "2027-09-01", "worst_case": "195.80", "on_time": "33.30"}
    assert set(chart) == {"cumulative_exposure", "contract_month_matrix", "deadlines", "breakdown", "kpis"}


def test_writeup_checker_rejects_an_invented_number(norns) -> None:
    wc = worst_case(norns, norns.compute("2027-06-01"))
    summary = summary_for_llm(wc)
    ok = "As of June 1, 2027 the total worst case is $195.80, of which $162.50 is avoidable (Z1:C, interest at 1.5%)."
    assert check_numbers(ok, summary) == []
    bad = "The worst case is $75,000 by June 9, 2027."
    assert set(check_numbers(bad, summary)) == {"$75,000", "June 9, 2027"}
    assert check_numbers(template_writeup(summary), summary) == []

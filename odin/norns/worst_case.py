"""Worst case: nobody acts from as_of on, against the same dates with every action taken on time.

Quantified only where the contracts give the numbers (fees, interest rates, credit
percentages, renewal terms); everything else is an unquantified item with its citation.
Every amount carries its formula, inputs and the clause citations it rests on. The gap
between the two scenarios is the avoidable exposure.

Exposure is Quillhub's: what it pays or loses. Money owed TO Quillhub that is overdue is
reported separately (receivables), not added to the worst-case total.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from odin.norns.calendar import add_months, iso, money, month_end, months_between
from odin.norns.engine import Inst, Norns, Timeline
from odin.norns.rules import US, Family
from odin.state.models import ExposureItem

NOT_IN_TOTAL = {"receivable_overdue"}


def _is_us(name: str | None) -> bool:
    return bool(name) and US.split()[0].lower() in (name or "").lower()


@dataclass
class Accrual:
    """One quantified exposure: a fixed amount on a date, or interest accruing from start to end."""

    scenario: str
    contract: str
    category: str
    description: str
    formula: str
    inputs: dict[str, Any]
    citations: list[dict[str, Any]]
    at: date                                  # fixed amounts: when it materialises; interest: start
    amount: Decimal                           # total within the projection
    end: date | None = None                   # interest: accrues until here
    principal: Decimal | None = None
    rate: Decimal | None = None

    def value_at(self, t: date) -> Decimal:
        if self.rate is not None and self.principal is not None and self.end is not None:
            stop = min(t, self.end)
            return money(self.principal * self.rate * months_between(self.at, stop)) if stop > self.at else Decimal("0.00")
        return self.amount if t >= self.at else Decimal("0.00")


@dataclass
class WorstCase:
    as_of: date
    projection_end: date
    accruals: list[Accrual] = field(default_factory=list)
    unquantified: list[dict[str, Any]] = field(default_factory=list)   # {scenario, contract, category, description, at, citations, ...}
    deadlines: list[dict[str, Any]] = field(default_factory=list)
    receivables: list[dict[str, Any]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def total(self, scenario: str) -> Decimal:
        return money(sum((a.amount for a in self.accruals if a.scenario == scenario and a.category not in NOT_IN_TOTAL),
                         Decimal(0)))

    @property
    def avoidable(self) -> Decimal:
        return money(self.total("worst_case") - self.total("on_time"))

    def items(self) -> list[ExposureItem]:
        out = [ExposureItem(as_of=iso(self.as_of), scenario=a.scenario, contract=a.contract, category=a.category,  # type: ignore[arg-type]
                            amount=a.amount, status="quantified", accrues_on=iso(a.end or a.at), description=a.description,
                            formula=a.formula, inputs=a.inputs, citations=a.citations) for a in self.accruals]
        out += [ExposureItem(as_of=iso(self.as_of), scenario=u["scenario"], contract=u["contract"], category=u["category"],  # type: ignore[arg-type]
                             amount=None, status="unquantified", accrues_on=u.get("at"), description=u["description"],
                             formula=u.get("formula"), inputs=u.get("inputs", {}), citations=u["citations"])
                for u in self.unquantified]
        return out

    def chart_data(self) -> dict[str, Any]:
        points = sorted({self.as_of, self.projection_end}
                        | {self.as_of + timedelta(days=7 * k) for k in range(0, 60) if self.as_of + timedelta(days=7 * k) < self.projection_end}
                        | {month_end(add_months(self.as_of, k)) for k in range(0, 24) if month_end(add_months(self.as_of, k)) <= self.projection_end})
        cumulative = [{"date": iso(p), **{s: str(money(sum((a.value_at(p) for a in self.accruals if a.scenario == s
                                                             and a.category not in NOT_IN_TOTAL), Decimal(0))))
                                          for s in ("worst_case", "on_time")}} for p in points]
        months = []
        m = self.as_of.replace(day=1)
        while m <= self.projection_end:
            months.append(m)
            m = add_months(m, 1)
        contracts = sorted({a.contract for a in self.accruals})
        matrix = []
        for c in contracts:
            row = {"contract": c}
            prev = Decimal("0.00")
            for m in months:
                cut = min(month_end(m), self.projection_end)
                cur = money(sum((a.value_at(cut) for a in self.accruals if a.scenario == "worst_case" and a.contract == c
                                 and a.category not in NOT_IN_TOTAL), Decimal(0)))
                row[f"{m:%Y-%m}"] = str(money(cur - prev))
                prev = cur
            matrix.append(row)
        breakdown: dict[str, Any] = {}
        for s in ("worst_case", "on_time"):
            by_cat: dict[str, Decimal] = {}
            by_contract: dict[str, Decimal] = {}
            for a in self.accruals:
                if a.scenario != s or a.category in NOT_IN_TOTAL:
                    continue
                by_cat[a.category] = by_cat.get(a.category, Decimal(0)) + a.amount
                by_contract[a.contract] = by_contract.get(a.contract, Decimal(0)) + a.amount
            breakdown[s] = {"by_category": {k: str(money(v)) for k, v in sorted(by_cat.items())},
                            "by_contract": {k: str(money(v)) for k, v in sorted(by_contract.items())},
                            "unquantified": sorted({u["category"] for u in self.unquantified if u["scenario"] == s})}
        return {"cumulative_exposure": cumulative,
                "contract_month_matrix": {"months": [f"{m:%Y-%m}" for m in months], "rows": matrix},
                "deadlines": self.deadlines, "breakdown": breakdown, "kpis": self.kpis}

    kpis: dict[str, Any] = field(default_factory=dict)


def worst_case(norns: Norns, t: Timeline) -> WorstCase:
    cfg = norns.cfg.norns
    end = add_months(t.as_of, cfg.projection_months)
    wc = WorstCase(as_of=t.as_of, projection_end=end)
    payments = t.payments()
    suspensions: dict[str, date] = {}

    for c, fam in sorted(t.families.items()):
        mine = [i for i in payments if i.contract == c]
        payable = [i for i in mine if _is_us(i.payer)]
        receivable = [i for i in mine if _is_us(i.payee)]
        _late_interest(wc, fam, payable, end)
        s = _suspension_and_cure(norns, wc, fam, payable, end)
        if s:
            suspensions[c] = s
        _renewal_lock_in(norns, wc, t, fam, end)
        _insurance(wc, t, fam, end)
        _credits_lost(wc, t, fam, end)
        for i in receivable:
            if i.status in ("unpaid", "partial"):
                wc.receivables.append({"contract": c, "period": i.period, "due": iso(i.due), "outstanding": str(i.outstanding),
                                       "interest_receivable_to_as_of": str(i.interest_to_as_of), "debtor": i.payer})
                for s_ in ("worst_case", "on_time"):
                    wc.accruals.append(Accrual(
                        s_, c, "receivable_overdue", f"{i.payer} has not paid {i.period} ({i.outstanding}, due {i.due})",
                        "outstanding = fee - payments received", {"fee": str(i.amount), "paid": str(i.paid_amount),
                                                                    "due": iso(i.due)}, i.citations, i.due, i.outstanding))  # type: ignore[arg-type]
    _cascade(norns, wc, t, suspensions, end)
    _deadlines(wc, t, cfg.due_soon_days)
    wc.kpis = _kpis(wc, t, cfg.due_soon_days)
    return wc


# --------------------------------------------------------------------------- per-contract pieces


def _late_interest(wc: WorstCase, fam: Family, payable: list[Inst], end: date) -> None:
    for i in payable:
        if not i.interest_rate or not i.due or i.due > end:
            continue
        overdue_now = i.status in ("unpaid", "partial") and i.due < wc.as_of
        future = i.status == "upcoming"
        if not (overdue_now or future):
            continue
        principal = i.outstanding if i.outstanding > 0 else (i.amount or Decimal(0))
        months = months_between(i.due, end)
        amount = money(principal * i.interest_rate * months)
        if amount <= 0:
            continue
        cites = i.citations
        inputs = {"principal": str(principal), "rate_per_month": str(i.interest_rate), "from": iso(i.due), "to": iso(end),
                  "months": str(months.quantize(Decimal('0.0001')))}
        desc = f"{fam.contract} {i.period}: {principal} unpaid from {i.due}; interest at {i.interest_rate:%} per month"
        formula = "principal x rate per month x months overdue (part months = days/30)"
        wc.accruals.append(Accrual("worst_case", fam.contract, "late_interest", desc, formula, inputs, cites, i.due,
                                   amount, end=end, principal=principal, rate=i.interest_rate))
        if overdue_now:            # already accrued: paying today stops it, but cannot undo it
            m_now = months_between(i.due, wc.as_of)
            wc.accruals.append(Accrual("on_time", fam.contract, "late_interest", desc + " (accrued up to as_of)", formula,
                                       {**inputs, "to": iso(wc.as_of), "months": str(m_now.quantize(Decimal('0.0001')))},
                                       cites, i.due, money(principal * i.interest_rate * m_now), end=wc.as_of,
                                       principal=principal, rate=i.interest_rate))


def _suspension_and_cure(norns: Norns, wc: WorstCase, fam: Family, payable: list[Inst], end: date) -> date | None:
    """First date the provider may suspend us if we stop paying, and the cure/termination right after it."""
    rule = next((r for r in norns.rules if r.contract == fam.contract and "suspension" in r.rule_id), None)
    unpaid = sorted((i for i in payable if i.due and i.due <= end and i.status in ("unpaid", "partial", "upcoming")),
                    key=lambda i: i.due)  # type: ignore[arg-type, return-value]
    if rule is None or not unpaid:
        return None
    first = unpaid[0]
    right = first.due + timedelta(days=(rule.offset_amount or 30) + 1)  # type: ignore[operator]
    if right > end:
        return None
    # A right that already exists can only be exercised from now on: nothing before as_of is projected.
    s = max(right, wc.as_of)
    since = f" (the right exists since {right})" if right < wc.as_of else ""
    wc.unquantified.append({"scenario": "worst_case", "contract": fam.contract, "category": "suspension_right", "at": iso(s),
                            "description": f"{fam.provider} may suspend the service from {s}{since}: the {first.period} "
                                           f"invoice (due {first.due}) unpaid for more than {rule.offset_amount} days",
                            "formula": f"due date + {rule.offset_amount} days + 1", "citations": rule.citations,
                            "inputs": {"due": iso(first.due), "days": rule.offset_amount}})
    cure = next((r for r in norns.rules if r.contract == fam.contract and r.kind == "cure"
                 and re.search(r"material breach", " ".join(map(str, r.conditions)), re.I)), None)
    if cure:
        t_right = max(first.due + timedelta(days=1 + (cure.offset_amount or 30)), wc.as_of)  # type: ignore[operator]
        wc.unquantified.append({"scenario": "worst_case", "contract": fam.contract, "category": "termination_right",
                                "at": iso(t_right),
                                "description": f"{fam.provider} may terminate for cause from {t_right} if it gives breach "
                                               f"notice the day after {first.due} and the breach is not cured within "
                                               f"{cure.offset_amount} days",
                                "formula": f"notice (due date + 1) + {cure.offset_amount} days", "citations": cure.citations,
                                "inputs": {"due": iso(first.due), "cure_days": cure.offset_amount}})
    return s


def _renewal_lock_in(norns: Norns, wc: WorstCase, t: Timeline, fam: Family, end: date) -> None:
    ren = next((i for i in t.instances if i.contract == fam.contract and i.kind == "renewal"), None)
    fee_rule = next((r for r in norns.rules if r.contract == fam.contract and r.kind == "payment"), None)
    if ren is None or fee_rule is None or not _is_us(fee_rule.payer) or ren.due is None or fam.term_end is None:
        return
    if ren.status == "upcoming" and ren.due > end:
        return
    months = fam.renewal_months or 0
    if not months:
        wc.flags.append(f"{fam.contract}: renewal term length not extracted; lock-in cost not quantified")
        return
    start = fam.term_end + timedelta(days=1)
    total, parts = Decimal(0), []
    for k in range(months):
        fee = norns.fee_for(fee_rule, add_months(start.replace(day=1), k))[0]
        total += fee
        parts.append(str(fee))
    total = money(total)
    desc = (f"{fam.contract}: non-renewal deadline {ren.due} {'passed' if ren.status == 'missed' else 'missed'}; the "
            f"agreement renews for {months} months from {start}")
    inputs = {"renewal_term_months": months, "renewal_start": iso(start), "monthly_fees": parts, "deadline": iso(ren.due)}
    cites = ren.citations + fee_rule.citations
    wc.accruals.append(Accrual("worst_case", fam.contract, "renewal_lock_in", desc, "sum of the monthly fees over the renewal "
                               "term", inputs, cites, ren.due, total))
    if ren.status == "missed":
        wc.accruals.append(Accrual("on_time", fam.contract, "renewal_lock_in", desc + " (already locked in)",
                                   "sum of the monthly fees over the renewal term", inputs, cites, ren.due, total))
    wc.flags.append(f"{fam.contract}: the renewal lock-in counts as avoidable only if Quillhub does not intend to renew")


def _insurance(wc: WorstCase, t: Timeline, fam: Family, end: date) -> None:
    ins = next((i for i in t.instances if i.contract == fam.contract and i.kind == "report" and "insurance" in i.rule_id), None)
    if ins is None or ins.due is None or ins.status == "met" or (ins.status == "upcoming" and ins.due > end):
        return
    scenarios = ["worst_case"] + (["on_time"] if ins.status == "missed" else [])
    cure = next((c for c in ins.flags if "cure" in c), None)
    for s in scenarios:
        wc.unquantified.append({
            "scenario": s, "contract": fam.contract, "category": "insurance_lapse", "at": iso(ins.due),
            "description": f"required insurance expires {ins.anchor_date} with no renewal confirmed; written notice to "
                           f"{fam.customer} due by {ins.due}. A lapse is a material breach and {fam.customer} may terminate "
                           "if it is not cured within the cure period after its written notice",
            "formula": None, "citations": ins.citations, "inputs": {"expiry": iso(ins.anchor_date), "notice_by": iso(ins.due),
                                                                    "note": cure}})


def _credits_lost(wc: WorstCase, t: Timeline, fam: Family, end: date) -> None:
    for i in t.instances:
        if i.contract != fam.contract or i.kind != "credit" or not _is_us(i.payee) or i.amount is None or i.due is None:
            continue
        if i.status == "upcoming" and i.due <= end or i.status == "missed":
            for s in ["worst_case"] + (["on_time"] if i.status == "missed" else []):
                wc.accruals.append(Accrual(s, fam.contract, "credits_lost", f"{fam.contract} credit for {i.period} not claimed "
                                           f"by {i.due}", "credit % x Monthly Fee (capped)", {"period": i.period,
                                                                                              "deadline": iso(i.due)},
                                           i.citations, i.due, i.amount))


def _cascade(norns: Norns, wc: WorstCase, t: Timeline, suspensions: dict[str, date], end: date) -> None:
    """Upstream hosting suspended -> our service down -> credits owed to our customers (+ their termination rights)."""
    context = next(iter(norns.store.list_resources("company_context")), None)
    text = (context.text or "") if context else ""
    host = re.search(r"hosting provider \(currently ([^)]+)\)", text)
    if not host:
        if suspensions:
            wc.flags.append("company/context.txt names no hosting provider; no cross-contract cascade computed")
        return
    host_quote = host.group(0)
    for up, s in suspensions.items():
        up_fam = t.families[up]
        if not up_fam.provider or host.group(1).split()[0].lower() not in up_fam.provider.lower():
            continue
        for down, fam in sorted(t.families.items()):
            if down == up or not _is_us(fam.provider):
                continue
            months, m, total = [], s.replace(day=1), Decimal(0)
            while m <= end:
                start_d, stop_d = max(s, m), min(month_end(m), end)
                minutes = Decimal((stop_d - start_d).days + 1) * 1440
                credit = norns.credit_for(fam, m, minutes)
                if credit and credit["amount"] > 0:
                    months.append(m)
                    total += credit["amount"]
                    cites = [{"doc_id": "company/context.txt", "clause_id": None, "quote": host_quote, "verified": True}] \
                        + credit["citations"]
                    wc.accruals.append(Accrual(
                        "worst_case", down, "service_credits_owed",
                        f"{down} {m:%B %Y}: service down from {start_d} ({up_fam.provider} suspension under {up}); credit "
                        f"{credit['rate']:.0%} of the {credit['fee']} Monthly Fee owed to {fam.customer}",
                        "credit % (tier for the month's uptime) x Monthly Fee, capped as extracted",
                        {"month": f"{m:%Y-%m}", "down_from": iso(start_d), "down_to": iso(stop_d),
                         "uptime_pct": str(credit["uptime"].quantize(Decimal('0.01'))), "rate": str(credit["rate"]),
                         "monthly_fee": str(credit["fee"]), "caps": [c.get("rate") for c in credit["rule"].caps],
                         "flags": credit["flags"]}, cites, month_end(m), credit["amount"]))
                m = add_months(m, 1)
            if months:
                wc.flags.append(f"cascade {up} -> {down}: assumes {up_fam.provider} suspends as soon as it may, the outage "
                                f"lasts to {end}, and {fam.customer} claims every credit in time")
                _liability_cap(norns, wc, fam, total, months[-1])
            term = next((r for r in norns.rules if r.contract == down and r.kind == "penalty_trigger"
                         and "consecutive" in r.name), None)
            if term and len(months) >= 2:
                at = month_end(months[1])
                wc.unquantified.append({"scenario": "worst_case", "contract": down, "category": "termination_right",
                                        "at": iso(at), "description": f"{fam.customer} may terminate {down} after two "
                                        f"consecutive months below the uptime target ({months[0]:%B} and {months[1]:%B %Y}); "
                                        "prorated refund of prepaid Fees", "formula": None, "citations": term.citations,
                                        "inputs": {"months": [f"{x:%Y-%m}" for x in months[:2]]}})
            notify = [r for r in norns.rules if r.contract == down and r.anchor == "event:outage" and r.kind == "report"]
            for r in notify:
                wc.unquantified.append({"scenario": "worst_case", "contract": down, "category": "notice_breach",
                                        "at": iso(s), "description": f"{r.name} ({r.offset_amount} {r.offset_unit} after the "
                                        f"outage begins on {s}) - missed if nobody acts", "formula": None,
                                        "citations": r.citations, "inputs": {}})


def _liability_cap(norns: Norns, wc: WorstCase, fam: Family, total: Decimal, last_month: date) -> None:
    """Fees paid or payable in the 12 months before the claim, if the contract caps liability that way."""
    cap_rows = [e for e in norns.store.current_extractions(fam.contract) if e.field_type == "liability_cap"]
    raw = " ".join(str((e.value or {}).get("cap_raw") or "") for e in cap_rows)
    m = re.search(r"(?:twelve|\b12\b)\s*(?:\(12\))?\s*months", raw, re.I)
    fee_rule = next((r for r in norns.rules if r.contract == fam.contract and r.kind == "payment"), None)
    if not m or fee_rule is None:
        wc.flags.append(f"{fam.contract}: no liability cap of the 'fees in the preceding 12 months' kind extracted")
        return
    cap = money(sum((norns.fee_for(fee_rule, add_months(last_month, -k))[0] for k in range(1, 13)), Decimal(0)))
    binding = total > cap
    wc.flags.append(f"{fam.contract}: liability cap (fees payable in the 12 months before the claim) = {cap}; "
                    f"credits total {money(total)} -> {'CAP BINDING' if binding else 'cap not binding'}")
    if binding:
        excess = total - cap
        for a in sorted((a for a in wc.accruals if a.contract == fam.contract and a.category == "service_credits_owed"
                         and a.scenario == "worst_case"), key=lambda a: a.at, reverse=True):
            cut = min(a.amount, excess)
            a.amount = money(a.amount - cut)
            a.inputs["reduced_by_liability_cap"] = str(cut)
            excess -= cut
            if excess <= 0:
                break


def _deadlines(wc: WorstCase, t: Timeline, due_soon: int) -> None:
    for i in t.instances:
        if i.status in ("upcoming", "unpaid", "partial", "missed") and i.due and i.due <= wc.projection_end:
            wc.deadlines.append({"date": iso(i.due), "contract": i.contract, "name": i.name, "kind": i.kind,
                                 "status": i.status, "severity": i.severity, "days_remaining": i.days_remaining,
                                 "amount": str(i.amount) if i.amount is not None else None})
    for u in wc.unquantified:
        if u["scenario"] == "worst_case" and u.get("at"):
            wc.deadlines.append({"date": u["at"], "contract": u["contract"], "name": u["description"][:120],
                                 "kind": u["category"], "status": "projected", "severity": "critical",
                                 "days_remaining": (date.fromisoformat(u["at"]) - wc.as_of).days, "amount": None})
    wc.deadlines.sort(key=lambda d: (d["date"], d["contract"], d["name"]))


def _kpis(wc: WorstCase, t: Timeline, due_soon: int) -> dict[str, Any]:
    overdue = t.overdue()
    soon = [i for i in t.instances if i.status in ("upcoming", "partial") and i.due and wc.as_of <= i.due <= wc.as_of + timedelta(days=30)]
    critical = next((d for d in wc.deadlines if d["severity"] == "critical" and d["date"] >= iso(wc.as_of)), None)  # type: ignore[operator]
    return {
        "as_of": iso(wc.as_of), "projection_end": iso(wc.projection_end),
        "overdue_now": {"count": len(overdue), "amount": str(money(sum((i.outstanding for i in overdue if i.kind == "payment"), Decimal(0))))},
        "due_in_30_days": {"count": len(soon), "amount": str(money(sum((i.amount or Decimal(0) for i in soon if i.kind == "payment"), Decimal(0))))},
        "next_critical_deadline": critical,
        "total_worst_case": str(wc.total("worst_case")), "total_on_time": str(wc.total("on_time")),
        "total_avoidable": str(wc.avoidable),
        "receivables_overdue": str(money(sum((Decimal(r["outstanding"]) for r in wc.receivables), Decimal(0)))),
        "unquantified_items": len([u for u in wc.unquantified if u["scenario"] == "worst_case"]),
    }

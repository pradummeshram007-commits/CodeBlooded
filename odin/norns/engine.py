"""NORNS: the timeline agent.

    norns = Norns(store, llm, cfg)
    t = norns.compute("2027-03-15", facts=[])      # pure, deterministic, fast

``compute`` rebuilds the whole picture from scratch for one date, using ONLY ledger rows
and facts dated on or before that date (no future leakage). Rules and the undated
instance skeleton are built once from Thor's extractions (``build_rules``) and cached, so
a dashboard slider can call compute() repeatedly.

Facts (the hook Heimdall will use) are dicts with a ``type`` and a ``date``:
  payment_made   {contract, amount, period?}           treated like a paid ledger row
  notice_sent    {contract, notice: non_renewal | insurance_lapse | credit_request, period?}
  insurance_renewed {}                                  cancels the insurance-lapse duty
  outage         {contract, minutes, single_incident_minutes?}  provider downtime in that month
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable

from pydantic import BaseModel, Field

from odin.agents.base import Agent
from odin.config import OdinConfig
from odin.llm import BudgetExceeded, LLMClient, LLMError
from odin.norns.calendar import (
    BusinessCalendar,
    add_months,
    iso,
    money,
    month_end,
    months_between,
    parse_month_year,
    to_date,
)
from odin.norns.rules import Family, RuleBuilder
from odin.state.models import LedgerEntry, ObligationInstance, ObligationRule
from odin.state.store import StateStore

AGENT = "norns"


class NormalizedDueRule(BaseModel):
    """What the LLM may return when Thor's fields leave a due rule open (validated, else flagged)."""

    offset_days: int = Field(ge=0, le=3650)
    day_type: str = Field(pattern="^(business|calendar|unspecified)$")
    anchor: str = Field(description="invoice_date | period_start | period_end | event")


@dataclass
class Inst:
    key: str
    rule_id: str
    contract: str
    kind: str
    name: str
    payer: str | None
    payee: str | None
    period: str | None = None
    anchor_date: date | None = None
    due: date | None = None
    due_calendar: date | None = None
    due_business: date | None = None
    day_type: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    status: str = "upcoming"
    paid_amount: Decimal = Decimal("0.00")
    paid_date: date | None = None
    ledger_lines: list[int] = field(default_factory=list)
    days_remaining: int | None = None
    severity: str | None = None
    flags: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    interest_rate: Decimal | None = None      # per month, for payments
    interest_to_as_of: Decimal = Decimal("0.00")
    outstanding: Decimal = Decimal("0.00")

    def view(self) -> dict[str, Any]:
        return {"key": self.key, "contract": self.contract, "kind": self.kind, "name": self.name, "period": self.period,
                "payer": self.payer, "payee": self.payee, "due": iso(self.due), "amount": str(self.amount) if self.amount
                is not None else None, "status": self.status, "paid_amount": str(self.paid_amount),
                "paid_date": iso(self.paid_date), "outstanding": str(self.outstanding),
                "interest_to_as_of": str(self.interest_to_as_of), "days_remaining": self.days_remaining,
                "severity": self.severity, "day_type": self.day_type, "due_calendar": iso(self.due_calendar),
                "due_business": iso(self.due_business), "ledger_lines": self.ledger_lines, "flags": self.flags,
                "citations": self.citations, "rule_id": self.rule_id}

    def model(self, as_of: date) -> ObligationInstance:
        return ObligationInstance(
            as_of=iso(as_of), instance_key=self.key, rule_id=self.rule_id, contract=self.contract, kind=self.kind,  # type: ignore[arg-type]
            name=self.name, period=self.period, anchor_date=iso(self.anchor_date), due_date=iso(self.due),
            due_date_calendar=iso(self.due_calendar), due_date_business=iso(self.due_business), day_type=self.day_type,
            amount=self.amount, currency=self.currency, payer=self.payer, payee=self.payee, status=self.status,  # type: ignore[arg-type]
            paid_amount=self.paid_amount if self.paid_amount else None, paid_date=iso(self.paid_date),
            ledger_lines=self.ledger_lines, days_remaining=self.days_remaining, severity=self.severity,
            flags=self.flags, citations=self.citations)


@dataclass
class Timeline:
    as_of: date
    contracts: list[str]
    instances: list[Inst]
    penalty_triggers: list[dict[str, Any]]
    unmatched_ledger: list[dict[str, Any]]
    out_of_scope_ledger: list[dict[str, Any]]
    flags: list[str]
    families: dict[str, Family]

    # -------- views
    def payments(self) -> list[Inst]:
        return [i for i in self.instances if i.kind == "payment"]

    def past_commitments(self) -> list[Inst]:
        return [i for i in self.instances if i.due and i.due <= self.as_of or i.status in ("paid_on_time", "paid_late")]

    def overdue(self) -> list[Inst]:
        return [i for i in self.instances if i.status in ("unpaid", "partial") and i.due and i.due < self.as_of
                or i.status == "missed"]

    def due_now(self, days: int) -> list[Inst]:
        return [i for i in self.instances if i.status in ("upcoming", "partial") and i.due
                and self.as_of <= i.due <= self.as_of + timedelta(days=days)]

    def upcoming(self, n: int | None = None) -> list[Inst]:
        out = sorted((i for i in self.instances if i.status == "upcoming" and i.due and i.due >= self.as_of),
                     key=lambda i: (i.due, i.key))
        return out[:n] if n else out

    def renewal_deadlines(self) -> dict[str, dict[str, Any]]:
        out = {}
        for i in sorted(self.instances, key=lambda i: (i.due or date.max, i.key)):
            if i.kind == "renewal" and i.contract not in out:
                out[i.contract] = i.view()
        return out

    def summary(self, due_soon_days: int = 7) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for i in self.instances:
            counts[i.status] = counts.get(i.status, 0) + 1
        return {
            "as_of": iso(self.as_of), "contracts": self.contracts, "status_counts": dict(sorted(counts.items())),
            "overdue": [i.view() for i in self.overdue()], "due_now": [i.view() for i in self.due_now(due_soon_days)],
            "next_deadlines": [i.view() for i in self.upcoming(5)], "renewal_deadlines": self.renewal_deadlines(),
            "penalty_triggers": self.penalty_triggers, "unmatched_ledger": self.unmatched_ledger,
            "out_of_scope_ledger": self.out_of_scope_ledger, "flags": self.flags,
        }

    def fingerprint(self) -> str:
        """Everything compute() decided, serialised canonically (for determinism checks)."""
        return json.dumps({"summary": self.summary(), "instances": [i.view() for i in self.instances]},
                          sort_keys=True, default=str)


def _norm_party(name: str | None) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).strip()


def _same_party(a: str | None, b: str | None) -> bool:
    na, nb = _norm_party(a), _norm_party(b)
    return bool(na and nb) and (na == nb or na.split()[0] == nb.split()[0])


class Norns(Agent):
    name = AGENT
    prompt_files = {"rule": "norns_rule.md", "writeup": "norns_writeup.md"}

    def __init__(self, store: StateStore, llm: LLMClient | None, cfg: OdinConfig, run_id: str | None = None,
                 contracts: list[str] | None = None):
        super().__init__(store, llm, cfg, run_id)
        self.contracts = list(contracts or cfg.norns.contracts)
        self._loaded = False

    # ================================================================== inputs

    def _normalize(self, raw: str, where: str) -> dict[str, Any] | None:
        """LLM fallback (a): a due rule Thor's fields leave open -> NormalizedDueRule, else None (flagged)."""
        if self.llm is None or not raw.strip():
            return None
        try:
            out = self.call_json(self.prompt("rule"), NormalizedDueRule, purpose=f"norns.normalize:{where}", raw=raw)
            return out.model_dump()
        except (LLMError, BudgetExceeded, ValueError) as exc:
            self.log("normalize_failed", where, None, error=f"{type(exc).__name__}: {exc}")
            return None

    def build_rules(self, persist: bool = True) -> list[ObligationRule]:
        """Rebuild every rule of the configured contracts from Thor's current extractions."""
        builder = RuleBuilder(self.store, normalizer=self._normalize)
        rules: list[ObligationRule] = []
        self.families: dict[str, Family] = {}
        with self.step("build_rules", ",".join(self.contracts)) as info:
            for c in self.contracts:
                if self.store.get_document(c, include_text=False) is None:
                    continue
                built, fam = builder.build(c)
                rules += built
                self.families[c] = fam
            if persist:
                self.store.replace_obligation_rules(self.contracts, rules)
            info.update(output_ref=f"{len(rules)} rules", families={c: f.docs for c, f in self.families.items()})
        self.rules = rules
        return rules

    def load(self, rebuild: bool = False, persist: bool = False) -> None:
        if self._loaded and not rebuild:
            return
        self.calendar = BusinessCalendar(self.store.list_holidays())
        self.ledger: list[LedgerEntry] = self.store.list_ledger()
        self.checkpoint_dates = [to_date(p.date) for p in self.store.list_checkpoints()]
        self.build_rules(persist=persist)
        self.horizon = add_months(max(self.checkpoint_dates), self.cfg.norns.horizon_months) if self.checkpoint_dates \
            else add_months(date.today(), self.cfg.norns.horizon_months)
        self.external_ids = {f.external_id: c for c, f in self.families.items() if f.external_id}
        self.skeleton = self._expand()
        self._loaded = True

    def checkpoint(self, n: int) -> date:
        self.load()
        if not 0 <= n < len(self.checkpoint_dates):
            raise ValueError(f"checkpoint {n} does not exist (0..{len(self.checkpoint_dates) - 1}; 0 = start date)")
        return self.checkpoint_dates[n]  # type: ignore[return-value]

    # ================================================================== undated rules -> dated instances

    def _rules_of(self, contract: str, kind: str, name_like: str | None = None) -> list[ObligationRule]:
        return [r for r in self.rules if r.contract == contract and r.kind == kind
                and (name_like is None or name_like in r.rule_id)]

    def _expand(self) -> list[Inst]:
        out: list[Inst] = []
        for c, fam in self.families.items():
            out += self._payment_instances(fam)
            out += self._renewal_instances(fam)
            out += self._fixed_instances(fam)
        return sorted(out, key=lambda i: (i.due or date.max, i.key))

    def fee_for(self, rule: ObligationRule, period_start: date) -> tuple[Decimal, list[str]]:
        amount, flags = rule.amount or Decimal(0), []
        for esc in rule.escalations:
            if esc.get("type") != "percent_on_anniversary":
                continue
            first, step = to_date(esc["first"]), int(esc.get("every_months") or 12)
            k = 0
            while first and add_months(first, step * k) <= period_start:
                k += 1
            for _ in range(k):
                amount = money(amount * (1 + Decimal(esc["rate"])))
            nxt = add_months(first, step * k) if first else None
            if nxt and period_start < nxt <= month_end(period_start):
                flags.append(f"fee changes on {nxt} inside this billing month; the fee in force on the first day of the "
                             f"month ({amount}) is used (no proration rule extracted)")
        return amount, flags

    def _payment_instances(self, fam: Family) -> list[Inst]:
        out = []
        for rule in self._rules_of(fam.contract, "payment"):
            rec = rule.recurrence or {}
            start, end = to_date(rec.get("start")), to_date(rec.get("end"))
            if start is None:
                continue
            interest = next((Decimal(e["rate_per_month"]) for e in rule.escalations if e.get("type") == "interest"), None)
            observers = rec.get("invoice_observers") or ["All"]
            m = start.replace(day=1)
            while m <= self.horizon:
                inv = self.calendar.first_business_day(m.year, m.month, observers)
                flags = list(rule.flags)
                if inv < start:
                    flags.append(f"first month: the first business day ({inv}) is before the Effective Date; the invoice "
                                 f"is dated {start} (the contract states no proration)")
                    inv = start
                if end and m > end:
                    if not rec.get("auto_renew"):
                        break
                    flags.append(f"after the initial term (ends {end}): assumes the agreement auto-renewed")
                cov = self.calendar.coverage_flag(inv)
                if cov:
                    flags.append(cov)
                amount, fee_flags = self.fee_for(rule, m)
                dc = self.calendar.count(inv, rule.offset_amount or 0, day_type=rule.day_type, observers=("All",))
                out.append(Inst(
                    key=f"{rule.rule_id}|{m:%Y-%m}", rule_id=rule.rule_id, contract=fam.contract, kind="payment",
                    name=f"{rule.name} {m:%B %Y}", payer=rule.payer, payee=rule.payee, period=f"{m:%Y-%m}",
                    anchor_date=inv, due=dc.chosen, due_calendar=dc.calendar, due_business=dc.business,
                    day_type=dc.day_type, amount=amount, currency=rule.currency, flags=flags + fee_flags + dc.flags,
                    citations=rule.citations, interest_rate=interest))
                m = add_months(m, 1)
        return out

    def _renewal_instances(self, fam: Family) -> list[Inst]:
        rules = self._rules_of(fam.contract, "renewal")
        if not rules or fam.term_end is None:
            return []
        options = []
        for r in rules:
            dc = self.calendar.count(fam.term_end, r.offset_amount or 0, day_type=r.day_type, direction="before")
            vf, vt = to_date(r.valid_from), to_date(r.valid_to)
            in_force = (vf is None or vf <= dc.chosen) and (vt is None or dc.chosen < vt)
            options.append((r, dc, in_force))
        chosen = [o for o in options if o[2]] or options
        r, dc, _ = min(chosen, key=lambda o: o[1].chosen)
        flags = list(dc.flags) + list(r.flags)
        if len(options) > 1:
            others = [f"{o[0].offset_amount} days -> {o[1].chosen} ({'in force' if o[2] else 'superseded by then'})"
                      for o in options]
            flags.append("the notice period was amended; the version in force on the deadline governs: " + "; ".join(others))
            straddle = [o for o in options if (to_date(o[0].valid_to) and o[1].chosen >= to_date(o[0].valid_to))  # type: ignore[operator]
                        or (to_date(o[0].valid_from) and o[1].chosen < to_date(o[0].valid_from))]  # type: ignore[operator]
            if straddle and len(straddle) == len(options):
                flags.append("edge case: every version's deadline falls outside its own validity period")
        return [Inst(key=f"{r.rule_id}|{fam.term_end}", rule_id=r.rule_id, contract=fam.contract, kind="renewal",
                     name=f"non-renewal notice deadline (term ends {fam.term_end})", payer=None, payee=None,
                     anchor_date=fam.term_end, due=dc.chosen, due_calendar=dc.calendar, due_business=dc.business,
                     day_type=dc.day_type, flags=flags, citations=r.citations)]

    def _fixed_instances(self, fam: Family) -> list[Inst]:
        out = []
        for r in self.rules:
            if r.contract != fam.contract or r.anchor != "fixed" or not r.anchor_date:
                continue
            anchor = to_date(r.anchor_date)
            observers = fam.observers(r.payer)
            dc = self.calendar.count(anchor, r.offset_amount or 0, day_type=r.day_type, observers=observers)  # type: ignore[arg-type]
            out.append(Inst(key=f"{r.rule_id}|{anchor}", rule_id=r.rule_id, contract=fam.contract, kind=r.kind, name=r.name,
                            payer=r.payer, payee=r.payee, anchor_date=anchor, due=dc.chosen, due_calendar=dc.calendar,
                            due_business=dc.business, day_type=dc.day_type, flags=list(r.flags) + dc.flags
                            + [str(c) for c in r.conditions], citations=r.citations))
        return out

    # ================================================================== compute

    def compute(self, as_of: date | str, facts: Iterable[dict[str, Any]] | None = None) -> Timeline:
        """Recompute everything as of one date from scratch; nothing dated after as_of is used."""
        self.load()
        day = to_date(as_of)
        assert day is not None
        visible_facts = sorted((f for f in (facts or []) if to_date(f.get("date")) and to_date(f["date"]) <= day),  # type: ignore[operator]
                               key=lambda f: (str(f["date"]), json.dumps(f, sort_keys=True, default=str)))
        instances = [replace(i, flags=list(i.flags), ledger_lines=[], citations=list(i.citations)) for i in self.skeleton]
        flags: list[str] = []
        for fam in self.families.values():
            flags += fam.flags
        unmatched, out_of_scope = self._match_payments(day, instances, visible_facts)
        instances += self._outage_instances(day, visible_facts)
        for i in instances:
            self._settle(day, i, visible_facts)
        triggers = self._triggers(day, instances)
        instances.sort(key=lambda i: (i.due or date.max, i.key))
        return Timeline(as_of=day, contracts=sorted(self.families), instances=instances, penalty_triggers=triggers,
                        unmatched_ledger=unmatched, out_of_scope_ledger=out_of_scope, flags=sorted(set(flags)),
                        families=self.families)

    def _match_payments(self, day: date, instances: list[Inst], facts: list[dict[str, Any]]) -> tuple[list, list]:
        payments = [i for i in instances if i.kind == "payment"]
        rows: list[dict[str, Any]] = [
            {"line_no": r.line_no, "date": to_date(r.date), "from": r.from_party, "to": r.to_party,
             "amount": money(r.amount), "reference": r.reference, "status": r.status, "contract_id": r.contract_id,
             "source": "ledger"}
            for r in self.ledger if to_date(r.date) <= day]  # type: ignore[operator]
        for f in facts:
            if f.get("type") == "payment_made":
                fam = self.families.get(f.get("contract", ""))
                rows.append({"line_no": None, "date": to_date(f["date"]), "from": f.get("from") or (fam and self._payer(fam)),
                             "to": f.get("to") or (fam and self._payee(fam)), "amount": money(f["amount"]),
                             "reference": f.get("period") or "", "status": "paid", "source": "fact",
                             "contract_id": fam.external_id if fam else None})
        unmatched, out_of_scope = [], []
        for row in sorted(rows, key=lambda r: (r["date"], r["line_no"] or 0)):
            contract = self.external_ids.get(row["contract_id"])
            if contract is None:
                out_of_scope.append({**row, "date": iso(row["date"]), "amount": str(row["amount"]),
                                     "why": f"contract {row['contract_id'] or '(none in reference)'} is not in Norns' scope"})
                continue
            period = parse_month_year(row["reference"]) or (row["reference"] if re.fullmatch(r"\d{4}-\d{2}", row["reference"] or "") else None)
            cands = [i for i in payments if i.contract == contract and _same_party(row["from"], i.payer)
                     and _same_party(row["to"], i.payee)]
            if period:
                cands = [i for i in cands if i.period == period]
            else:
                cands = sorted((i for i in cands if i.anchor_date and i.due and i.anchor_date - timedelta(days=31) <= row["date"]
                                <= i.due + timedelta(days=120) and i.amount == row["amount"]), key=lambda i: abs((i.due - row["date"]).days))  # type: ignore[operator]
            if not cands:
                unmatched.append({**row, "date": iso(row["date"]), "amount": str(row["amount"]),
                                  "why": "no scheduled payment matches its parties, period and amount"})
                continue
            inst = cands[0]
            if row["line_no"]:
                inst.ledger_lines.append(row["line_no"])
            if row["status"] == "paid":
                inst.paid_amount += row["amount"]
                inst.paid_date = max(inst.paid_date or row["date"], row["date"])
                if inst.amount is not None and row["amount"] > inst.amount:
                    inst.flags.append(f"ledger line {row['line_no']}: paid {row['amount']}, more than the {inst.amount} due")
                if re.search(r"prorat", row["reference"], re.I) and inst.amount == row["amount"]:
                    inst.flags.append(f"ledger line {row['line_no']} says 'partial month prorated' but records the full "
                                      f"monthly fee ({row['amount']})")
            else:
                note = f"ledger line {row['line_no']} ({row['date']}) marks this period '{row['status']}' - not a payment"
                if row["status"] == "overdue" and inst.due and row["date"] <= inst.due:
                    note += f"; but the invoice is not due until {inst.due}"
                inst.flags.append(note)
        return unmatched, out_of_scope

    def _payer(self, fam: Family) -> str | None:
        return fam.customer

    def _payee(self, fam: Family) -> str | None:
        return fam.provider

    def _settle(self, day: date, i: Inst, facts: list[dict[str, Any]]) -> None:
        """Status, days remaining, severity, interest to as_of."""
        if i.kind == "payment":
            amount = i.amount or Decimal(0)
            i.outstanding = max(amount - i.paid_amount, Decimal("0.00"))
            if i.paid_amount >= amount and amount > 0:
                i.status = "paid_on_time" if i.paid_date and i.due and i.paid_date <= i.due else "paid_late"
            elif i.paid_amount > 0:
                i.status = "partial"
            else:
                i.status = "upcoming" if i.due and day <= i.due else "unpaid"
            if i.interest_rate and i.due:
                late_end = i.paid_date if i.status == "paid_late" else (day if i.outstanding > 0 else None)
                base = amount if i.status == "paid_late" else i.outstanding
                if late_end and late_end > i.due:
                    i.interest_to_as_of = money(base * i.interest_rate * months_between(i.due, late_end))
        elif i.kind == "renewal":
            sent = [f for f in facts if f.get("type") == "notice_sent" and f.get("notice") == "non_renewal"
                    and f.get("contract") == i.contract]
            if sent and to_date(sent[0]["date"]) <= i.due:  # type: ignore[operator]
                i.status = "met"
            else:
                i.status = "upcoming" if i.due and day <= i.due else "missed"
        elif i.kind == "report" and "insurance" in i.rule_id:
            renewed = any(f.get("type") == "insurance_renewed" for f in facts)
            sent = any(f.get("type") == "notice_sent" and f.get("notice") == "insurance_lapse" for f in facts)
            if renewed or sent:
                i.status = "met"
            else:
                i.status = "upcoming" if i.due and day <= i.due else "missed"
        elif i.kind == "credit":
            claimed = any(f.get("type") == "notice_sent" and f.get("notice") == "credit_request"
                          and f.get("contract") == i.contract and f.get("period") == i.period for f in facts)
            i.status = "met" if claimed else ("upcoming" if i.due and day <= i.due else "missed")
        i.days_remaining = (i.due - day).days if i.due and i.status in ("upcoming", "unpaid", "partial") else None
        i.severity = self._severity(i, day)

    @staticmethod
    def _severity(i: Inst, day: date) -> str | None:
        if i.status in ("paid_on_time", "paid_late", "met"):
            return None
        if i.status == "missed":
            return "critical"
        if i.due is None:
            return "low"
        d = (i.due - day).days
        if i.status in ("unpaid", "partial") and d < 0:
            return "critical" if -d > 30 else "high"
        if i.kind == "renewal":
            return "critical" if d <= 30 else "high" if d <= 90 else "medium" if d <= 180 else "low"
        return "high" if d <= 7 else "medium" if d <= 30 else "low"

    def _outage_instances(self, day: date, facts: list[dict[str, Any]]) -> list[Inst]:
        """Outage facts -> credit owed for the month and the claim deadline (versioned windows, caps)."""
        out = []
        for f in facts:
            if f.get("type") != "outage" or f.get("contract") not in self.families:
                continue
            fam = self.families[f["contract"]]
            when = to_date(f["date"])
            assert when is not None
            m_end = month_end(when)
            credit = self.credit_for(fam, when, Decimal(str(f.get("minutes") or 0)), f.get("single_incident_minutes"))
            window = self.claim_window(fam, m_end)
            if credit is None or window is None:
                continue
            rule, dc, wflags = window
            out.append(Inst(key=f"{rule.rule_id}|{m_end:%Y-%m}|{f['date']}", rule_id=rule.rule_id, contract=fam.contract,
                            kind="credit", name=f"claim service credit for {m_end:%B %Y}", payer=fam.provider,
                            payee=fam.customer, period=f"{m_end:%Y-%m}", anchor_date=m_end, due=dc.chosen,
                            due_calendar=dc.calendar, due_business=dc.business, day_type=dc.day_type,
                            amount=credit["amount"], currency="USD", flags=dc.flags + wflags + credit["flags"],
                            citations=rule.citations + credit["citations"]))
        return out

    def credit_for(self, fam: Family, when: date, minutes: Decimal, single_incident: Any = None) -> dict[str, Any] | None:
        """Credit for one month of provider downtime under the credit rule in force that month."""
        rules = [r for r in self._rules_of(fam.contract, "credit") if r.conditions
                 and (r.valid_from is None or to_date(r.valid_from) <= when) and (r.valid_to is None or when < to_date(r.valid_to))]  # type: ignore[operator]
        if not rules:
            return None
        rule = rules[0]
        fee_rule = next(iter(self._rules_of(fam.contract, "payment")), None)
        fee = self.fee_for(fee_rule, when.replace(day=1))[0] if fee_rule else None
        if fee is None:
            return None
        total_minutes = Decimal((month_end(when) - when.replace(day=1)).days + 1) * 1440
        uptime = (Decimal(1) - minutes / total_minutes) * 100
        rate, flags = Decimal(0), []
        for t in (c for c in rule.conditions if isinstance(c, dict) and c.get("type") == "tier" and c.get("credit")):
            below = Decimal(t["below"]) if t.get("below") else None
            at_least = Decimal(t["at_least"]) if t.get("at_least") else None
            if below is None and uptime > 0:
                flags.append("a credit tier has no extracted threshold; applied only if the service was down all month")
                continue
            if (below is None or uptime < below) and (at_least is None or uptime >= at_least):
                rate = max(rate, Decimal(t["credit"]))
        for t in (c for c in rule.conditions if isinstance(c, dict) and c.get("type") == "additional" and c.get("credit")):
            if single_incident and t.get("minutes") and Decimal(str(single_incident)) > Decimal(t["minutes"]):
                rate += Decimal(t["credit"])
        cap = next((Decimal(c["rate"]) for c in rule.caps if c.get("rate")), None)
        if cap is not None and rate > cap:
            flags.append(f"credit {rate:.0%} capped at {cap:.0%} of the Monthly Fee")
            rate = cap
        return {"amount": money(fee * rate), "rate": rate, "uptime": uptime, "fee": fee, "rule": rule,
                "flags": flags + list(rule.flags), "citations": rule.citations}

    def claim_window(self, fam: Family, m_end: date):
        """The claim deadline for downtime in the month ending m_end; flags a window that straddles an amendment."""
        windows = [r for r in self._rules_of(fam.contract, "credit") if r.offset_amount]
        if not windows:
            return None
        in_force = [r for r in windows if (r.valid_from is None or to_date(r.valid_from) <= m_end)  # type: ignore[operator]
                    and (r.valid_to is None or m_end < to_date(r.valid_to))]  # type: ignore[operator]
        rule = in_force[0] if in_force else windows[0]
        dc = self.calendar.count(m_end, rule.offset_amount or 0, day_type=rule.day_type)
        flags = []
        later = [r for r in windows if r.valid_from and m_end < to_date(r.valid_from) <= dc.chosen]  # type: ignore[operator]
        for r in later:
            alt = self.calendar.count(m_end, r.offset_amount or 0, day_type=r.day_type)
            flags.append(f"edge case: the claim window for {m_end:%B %Y} straddles the amendment of {r.valid_from} "
                         f"({rule.offset_amount} days -> {dc.chosen}; amended {r.offset_amount} days -> {alt.chosen}); the "
                         "earlier date is used")
            if alt.chosen < dc.chosen:
                dc = alt
        return rule, dc, flags

    def _triggers(self, day: date, instances: list[Inst]) -> list[dict[str, Any]]:
        out = []
        susp = {r.contract: r for r in self.rules if r.kind == "penalty_trigger" and "suspension" in r.rule_id}
        for i in instances:
            if i.kind == "payment" and i.status in ("unpaid", "partial") and i.due and i.due < day:
                out.append({"type": "late_interest", "contract": i.contract, "instance": i.key, "date": iso(i.due),
                            "amount": str(i.interest_to_as_of), "creditor": i.payee, "debtor": i.payer,
                            "description": f"interest accruing on {i.outstanding} unpaid since {i.due}", "citations":
                            [c for e in self._rule(i.rule_id).escalations if e.get("type") == "interest" for c in e["citation"]]})
                rule = susp.get(i.contract)
                if rule and day > i.due + timedelta(days=rule.offset_amount or 30):
                    out.append({"type": "suspension_right", "contract": i.contract, "instance": i.key,
                                "date": iso(i.due + timedelta(days=(rule.offset_amount or 30) + 1)), "creditor": i.payee,
                                "debtor": i.payer, "description": f"{i.payee} may suspend {i.payer}: balance outstanding more "
                                f"than {rule.offset_amount} days", "citations": rule.citations})
            elif i.status == "missed" and i.kind == "renewal":
                out.append({"type": "renewal_locked_in", "contract": i.contract, "instance": i.key, "date": iso(i.due),
                            "description": f"non-renewal deadline {i.due} passed: the agreement renews", "citations": i.citations})
            elif i.status == "missed" and i.kind == "report" and "insurance" in i.rule_id:
                out.append({"type": "insurance_lapse_breach", "contract": i.contract, "instance": i.key, "date": iso(i.due),
                            "description": "insurance lapse not notified in time: a lapse is a material breach; the customer "
                                           "may terminate if it is not cured after written notice", "citations": i.citations})
            elif i.status == "missed" and i.kind == "credit":
                out.append({"type": "credit_lost", "contract": i.contract, "instance": i.key, "date": iso(i.due),
                            "amount": str(i.amount), "description": f"credit for {i.period} not claimed in time",
                            "citations": i.citations})
        return sorted(out, key=lambda t: (t["date"] or "", t["type"], t["instance"]))

    def _rule(self, rule_id: str) -> ObligationRule:
        return next(r for r in self.rules if r.rule_id == rule_id)

    # ================================================================== persistence

    def persist(self, t: Timeline, chart_data: dict[str, Any] | None = None) -> None:
        """Store the instances for t.as_of and a snapshot (summary + chart data)."""
        from odin.state.models import TimelineSnapshot

        self.store.replace_obligation_instances(iso(t.as_of), [i.model(t.as_of) for i in t.instances])  # type: ignore[arg-type]
        self.store.add_timeline_snapshot(TimelineSnapshot(as_of=iso(t.as_of), summary=json.loads(json.dumps(  # type: ignore[arg-type]
            t.summary(self.cfg.norns.due_soon_days), default=str)), chart_data=chart_data or {}))


def compute(as_of: date | str, facts: Iterable[dict[str, Any]] | None = None) -> Timeline:
    """Module-level convenience: compute() on the configured runtime (no LLM needed)."""
    from odin.runtime import get_runtime

    rt = get_runtime()
    return Norns(rt.store, None, rt.cfg).compute(as_of, facts)


def instance_dict(i: Inst) -> dict[str, Any]:
    return asdict(i)

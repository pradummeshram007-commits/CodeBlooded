"""Norns rule builder: Thor's current extractions -> dated ObligationRules.

Deterministic. Every rule cites the extraction ids (and their clause quotes) it was built
from; nothing is read from a contract directly. Where a clause has been amended (Thor's
`amends` edges), the rule is built once per version through ``effective_clause``'s
versions, each with valid_from / valid_to. Terms of documents a contract incorporates
(STD, the SLA, the DPA addendum) apply to it unless the contract states its own.

When a due rule cannot be parsed from Thor's fields, an optional LLM normaliser is tried
(validated with pydantic); if that fails too, the rule is flagged and not built (never guessed).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Callable

from odin.agents.thor import BUSINESS_DAYS_RE, CALENDAR_DAYS_RE, DAY_COUNT_RE, find_mentions
from odin.effective import amendments_of, clause_versions
from odin.norns.calendar import add_months, iso, money, parse_long_date, pct, to_date
from odin.state.models import Citation, Extraction, ObligationRule, Resource
from odin.state.store import StateStore

US = "Quillhub Inc."
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?%")
TIER_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)%\s*to\s*<\s*(\d+(?:\.\d+)?)%")
TIER_BELOW_RE = re.compile(r"below\s+(\d+(?:\.\d+)?)%", re.I)
UNIT_RE = re.compile(r"(minute|hour|day|week|month|year)s?", re.I)
EVENT_TYPES = [
    (re.compile(r"security incident", re.I), "security_incident"),
    (re.compile(r"data breach|unauthori[sz]ed access", re.I), "data_breach"),
    (re.compile(r"disruption|downtime|outage|unavailab", re.I), "outage"),
    (re.compile(r"subprocessor", re.I), "subprocessor_change"),
    (re.compile(r"terminat|expir", re.I), "termination"),
    (re.compile(r"insurance|policy", re.I), "insurance_lapse"),
    (re.compile(r"objection|object", re.I), "objection"),
    (re.compile(r"audit", re.I), "audit_request"),
    (re.compile(r"dispute", re.I), "payment_dispute"),
    (re.compile(r"request", re.I), "request"),
]


def first_duration(*texts: str | None) -> tuple[int, str] | None:
    """The first 'N unit' in the texts: 'within fifteen (15) days' -> (15, 'days')."""
    for t in texts:
        if not t:
            continue
        for m in find_mentions("x", str(t)):
            if m.kind == "duration":
                u = UNIT_RE.search(m.raw)
                if u:
                    return int(m.number), u.group(1).lower() + "s"
    return None


def day_type_of(*texts: str | None) -> str | None:
    """'business' / 'calendar' only when those words qualify days; 'unspecified' for a bare day count."""
    joined = " ".join(t for t in texts if t)
    if BUSINESS_DAYS_RE.search(joined):
        return "business"
    if CALENDAR_DAYS_RE.search(joined):
        return "calendar"
    return "unspecified" if DAY_COUNT_RE.search(joined) else None


def event_type(*texts: str | None) -> str:
    joined = " ".join(t for t in texts if t)
    for pattern, name in EVENT_TYPES:
        if pattern.search(joined):
            return name
    return "other"


@dataclass
class Family:
    """A contract with the documents it incorporates or that amend it, and its basic dates."""

    contract: str
    docs: list[str]
    provider: str | None = None
    customer: str | None = None
    external_id: str | None = None
    effective: date | None = None
    term_start: date | None = None
    term_end: date | None = None
    renewal_months: int | None = None
    auto_renew: bool | None = None
    amendments: dict[str, dict[str, Any]] = field(default_factory=dict)   # amending clause -> edge info
    flags: list[str] = field(default_factory=list)
    citations: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def observers(self, party: str | None) -> tuple[str, ...]:
        """Whose holidays count: Quillhub's own list for Quillhub, the shared 'All' list for anyone else."""
        return ("All", "Quillhub") if party and "quillhub" in party.lower() else ("All",)


class RuleBuilder:
    def __init__(self, store: StateStore, *, normalizer: Callable[[str, str], dict[str, Any] | None] | None = None):
        self.store = store
        self.normalizer = normalizer
        self._ex: dict[str, list[Extraction]] = {}
        self._cites: dict[str, dict[int, list[Citation]]] = {}

    # ------------------------------------------------------------------ data access

    def rows(self, doc_id: str, field_type: str | None = None) -> list[Extraction]:
        if doc_id not in self._ex:
            self._ex[doc_id] = [e for e in self.store.current_extractions(doc_id) if e.status != "missing"]
            by: dict[int, list[Citation]] = {}
            for c in self.store.citations_for_document(doc_id):
                by.setdefault(c.extraction_id or 0, []).append(c)
            self._cites[doc_id] = by
        return [e for e in self._ex[doc_id] if field_type is None or e.field_type == field_type]

    def cites(self, e: Extraction) -> list[dict[str, Any]]:
        self.rows(e.doc_id)
        return [{"extraction_id": e.id, "doc_id": e.doc_id, "field_key": e.field_key, "clause_id": c.clause_id,
                 "clause_ref": c.clause_ref, "quote": " ".join(c.quote.split())[:240], "verified": c.verified}
                for c in self._cites[e.doc_id].get(e.id or 0, [])] or \
               [{"extraction_id": e.id, "doc_id": e.doc_id, "field_key": e.field_key, "clause_id": None, "quote": None,
                 "verified": False}]

    def clause_of(self, e: Extraction) -> str | None:
        self.rows(e.doc_id)
        verified = [c for c in self._cites[e.doc_id].get(e.id or 0, []) if c.verified and c.clause_id]
        return verified[0].clause_id if verified else None

    def evidence(self, e: Extraction) -> str:
        v = e.value if isinstance(e.value, dict) else {}
        return " ".join([e.raw_text or ""] + [c["quote"] or "" for c in self.cites(e)] + [str(x) for x in v.values()])

    # ------------------------------------------------------------------ family

    def family(self, contract: str) -> Family:
        docs, frontier = {contract}, [contract]
        rels = self.store.list_relations()
        while frontier:
            d = frontier.pop()
            for r in rels:
                if r.type not in ("incorporates", "amends"):
                    continue
                other = r.to_doc if r.from_doc == d else (r.from_doc if r.to_doc == d else None)
                if other and other not in docs and self.store.get_document(other, include_text=False) is not None:
                    other_doc = self.store.get_document(other, include_text=False)
                    if other_doc and other_doc.kind == "contract" and other != contract:
                        continue           # another primary contract is not part of this family
                    docs.add(other)
                    frontier.append(other)
        fam = Family(contract=contract, docs=sorted(docs, key=lambda x: (x != contract, x)))
        doc = self.store.get_document(contract, include_text=False)
        fam.external_id = doc.external_id if doc else None
        for r in rels:
            if r.type == "amends" and r.from_doc in docs and r.to_doc in docs and r.clause_id:
                fam.amendments[r.clause_id] = {**(r.citation or {}), "from_doc": r.from_doc, "to_doc": r.to_doc}
        for e in self.rows(contract, "party"):
            v = e.value or {}
            role = (v.get("role") or e.field_key).lower()
            if "provider" in role:
                fam.provider = v.get("name")
            elif "customer" in role:
                fam.customer = v.get("name")
        eff = next((e for e in self.rows(contract, "effective_date") if (e.value or {}).get("iso")), None)
        term = next((e for e in self.rows(contract, "term")), None)
        fam.effective = to_date(eff.value["iso"]) if eff else None
        if term:
            tv = term.value or {}
            fam.term_start = to_date(tv.get("start_iso")) or fam.effective
            fam.term_end = to_date(tv.get("end_iso"))
            if fam.term_end is None and fam.term_start and tv.get("duration_months"):
                fam.term_end = add_months(fam.term_start, int(tv["duration_months"])) - timedelta(days=1)
            fam.citations["term"] = self.cites(term)
        if eff:
            fam.citations["effective_date"] = self.cites(eff)
        if not (fam.provider and fam.customer):
            fam.flags.append(f"{contract}: provider/customer not both extracted (provider={fam.provider!r}, "
                             f"customer={fam.customer!r})")
        if fam.term_end is None:
            fam.flags.append(f"{contract}: no term end date extracted; renewal and fee schedules cannot be dated")
        return fam

    # ------------------------------------------------------------------ build

    def build(self, contract: str) -> tuple[list[ObligationRule], Family]:
        fam = self.family(contract)
        self._consumed: set[int] = set()
        rules: list[ObligationRule] = []
        rules += self._renewal_rules(fam)        # sets fam.renewal_months / auto_renew
        rules += self._payment_rules(fam)
        rules += self._credit_rules(fam)
        rules += self._suspension_rules(fam)
        rules += self._termination_rules(fam)
        rules += self._insurance_rules(fam)
        rules += self._event_rules(fam)
        return rules, fam

    def _rule(self, fam: Family, doc_id: str, kind: str, key: str, valid_from: date | None = None, **kw: Any) -> ObligationRule:
        rid = f"{fam.contract}:{doc_id}:{kind}:{key}@{iso(valid_from) or 'start'}"
        return ObligationRule(rule_id=rid, contract=fam.contract, doc_id=doc_id, kind=kind, valid_from=iso(valid_from),  # type: ignore[arg-type]
                              **kw)

    def _versions(self, e: Extraction, pick: Callable[[Extraction], bool] | None = None) -> list[tuple[Any, list[Extraction]]]:
        """[(version, rows of the same field type in force in that version)] for the clause e cites."""
        clause = self.clause_of(e)
        if clause is None or not amendments_of(self.store, e.doc_id, clause):
            return [(None, [e])]
        versions, _notes = clause_versions(self.store, e.doc_id, clause)
        out = []
        for v in versions:
            rows = [e] if v.source == "original" else [t for t in v.terms if t.field_type == e.field_type
                                                         and (pick is None or pick(t))]
            for t in rows:
                self._consumed.add(t.id or 0)
            out.append((v, rows))
        return out

    # ---------------------------------------------------------------- renewal

    def _renewal_rules(self, fam: Family) -> list[ObligationRule]:
        out = []
        row = next((e for e in self.rows(fam.contract, "renewal")), None)
        if row is None:
            fam.flags.append(f"{fam.contract}: no renewal term extracted")
            return out
        self._consumed.add(row.id or 0)
        for d in fam.docs:        # the non-renewal notice duty is this deadline, not a separate event rule
            for e in self.rows(d, "obligation"):
                if re.search(r"non-renewal", str((e.value or {}).get("action") or ""), re.I):
                    self._consumed.add(e.id or 0)
        for version, rows in self._versions(row):
            r = rows[0] if rows else None
            if r is None:
                fam.flags.append(f"{fam.contract}: amended renewal clause has no renewal row in force")
                continue
            v = r.value or {}
            n = v.get("notice_period_days") or (first_duration(v.get("notice_period_raw")) or (None, ""))[0]
            fam.renewal_months = fam.renewal_months or v.get("renewal_term_months")
            fam.auto_renew = v.get("auto_renew") if fam.auto_renew is None else fam.auto_renew
            if n is None:
                fam.flags.append(f"{r.doc_id}/{r.field_key}: renewal notice period not stated as a number of days")
                continue
            start = to_date(version.effective_from) if version and version.effective_from else None
            end = to_date(version.effective_to) if version and version.effective_to else None
            out.append(self._rule(
                fam, r.doc_id, "renewal", "non_renewal_notice", start, name="non-renewal notice deadline",
                payer=None, payee=None, anchor="term_end", anchor_date=iso(fam.term_end), offset_amount=int(n),
                offset_unit="days", offset_direction="before",
                day_type=day_type_of(v.get("notice_period_raw"), r.raw_text) or "unspecified",
                recurrence={"renewal_term_months": v.get("renewal_term_months"), "auto_renew": v.get("auto_renew")},
                formula=f"end of the then-current Subscription Period minus {n} days (notice must be delivered by then)",
                valid_to=iso(end), citations=self.cites(r) + fam.citations.get("term", []),
                flags=[f"version {version.source} from {version.effective_from} (amended by "
                       f"{(version.amended_by or {}).get('doc_id')} {(version.amended_by or {}).get('clause_id')})"]
                if version and version.source != "original" else [],
            ))
        return out

    # ---------------------------------------------------------------- payments

    def _payment_rules(self, fam: Family) -> list[ObligationRule]:
        out = []
        fees = [e for e in self.rows(fam.contract, "payment") if (e.value or {}).get("amount") is not None]
        if not fees:
            fam.flags.append(f"{fam.contract}: no fee with an amount extracted")
        family_rows = [e for d in fam.docs for e in self.rows(d)]
        std_interest = next((e for d in fam.docs if d != fam.contract for e in self.rows(d)
                             if e.field_type in ("payment", "penalty")
                             and PCT_RE.search(str((e.value or {}).get("interest_rate_raw") or "")) is not None), None)
        for e in fees:
            self._consumed.add(e.id or 0)
            v = e.value or {}
            amount = money(v["amount"])
            n = v.get("payment_period_days") or (first_duration(v.get("due_rule"), e.raw_text) or (None, ""))[0]
            flags: list[str] = []
            if n is None and self.normalizer:
                norm = self.normalizer(e.raw_text or v.get("due_rule") or "", f"{e.doc_id}/{e.field_key}")
                n = norm.get("offset_days") if norm else None
                if n:
                    flags.append("payment period normalised by the LLM from the raw due rule")
            if n is None:
                fam.flags.append(f"{e.doc_id}/{e.field_key}: payment period not stated as a number of days; not scheduled")
                continue
            invoice_text = v.get("invoice_rule") or next(
                (t.raw_text or str(t.value) for t in family_rows if "first business day" in self.evidence(t).lower()), "")
            if "first business day" not in invoice_text.lower():
                fam.flags.append(f"{e.doc_id}/{e.field_key}: invoice date rule not recognised ({invoice_text!r}); not scheduled")
                continue
            flags.append("'first business day' invoicing: the contract does not say whose holiday calendar applies; "
                         f"{'Quillhub' if fam.provider and 'quillhub' in fam.provider.lower() else 'the shared (All)'} "
                         "holidays are used for the invoicing party")
            cites = self.cites(e)
            escalations: list[dict[str, Any]] = []
            for adj in self.rows(fam.contract, "payment"):
                raw = str((adj.value or {}).get("adjustment_raw") or "")
                m = PCT_RE.search(raw)
                if m and "anniversar" in raw.lower() and fam.effective:
                    self._consumed.add(adj.id or 0)
                    escalations.append({"type": "percent_on_anniversary", "rate": str(pct(m.group(0))),
                                        "first": iso(add_months(fam.effective, 12)), "every_months": 12,
                                        "citation": self.cites(adj)})
            rate_src = e if PCT_RE.search(str(v.get("interest_rate_raw") or v.get("late_fee_raw") or "")) else std_interest
            if rate_src is not None:
                rv = rate_src.value or {}
                rate = pct(PCT_RE.search(str(rv.get("interest_rate_raw") or rv.get("late_fee_raw"))).group(0))  # type: ignore[union-attr]
                escalations.append({"type": "interest", "rate_per_month": str(rate), "from": "due_date",
                                    "citation": self.cites(rate_src)})
                if rate_src is not e:
                    cites = cites + self.cites(rate_src)
            out.append(self._rule(
                fam, e.doc_id, "payment", e.field_key, fam.effective, name=str(v.get("item") or "fee"),
                payer=fam.customer, payee=fam.provider, anchor="invoice_date", offset_amount=int(n), offset_unit="days",
                offset_direction="after", day_type=day_type_of(v.get("due_rule"), f"{n} days") or "unspecified",
                recurrence={"freq": "monthly", "on": "first_business_day", "start": iso(fam.effective),
                            "end": iso(fam.term_end), "auto_renew": fam.auto_renew,
                            "invoice_observers": list(fam.observers(fam.provider))},
                amount=amount, currency=v.get("currency") or "USD", escalations=escalations,
                formula=f"{amount} per month, invoiced on the first business day of the month, due {n} days after the invoice date",
                citations=cites, flags=flags,
            ))
        return out

    # ---------------------------------------------------------------- service credits

    @staticmethod
    def _tier(e: Extraction, text: str) -> dict[str, Any]:
        v = e.value or {}
        credit = PCT_RE.search(str(v.get("amount_raw") or v.get("formula") or ""))
        tier: dict[str, Any] = {"credit": str(pct(credit.group(0))) if credit else None, "extraction_id": e.id}
        rng = TIER_RANGE_RE.search(text)
        below = TIER_BELOW_RE.search(text)
        if rng:
            tier.update(at_least=rng.group(1), below=rng.group(2))
        elif below:
            tier.update(below=below.group(1))
        trig = str(v.get("trigger") or "")
        if re.search(r"single incident|consecutive minutes", trig, re.I):
            m = first_duration(trig)
            tier.update(type="additional", condition=trig, minutes=m[0] if m and m[1] == "minutes" else None)
        else:
            tier["type"] = "tier"
        return tier

    def _uptime_target(self, fam: Family) -> tuple[str, list[dict[str, Any]]] | None:
        """The uptime commitment's percentage, from its value or its verified quote (e.g. '(99.9%)')."""
        for d in fam.docs:
            for e in self.rows(d, "obligation") + self.rows(d, "compliance"):
                v = e.value or {}
                head = str(v.get("action") or v.get("requirement") or "")
                if not re.search(r"uptime|available", head + " " + e.field_key, re.I):
                    continue
                text = " ".join([head, e.raw_text or ""] + [c["quote"] or "" for c in self.cites(e) if c["verified"]])
                m = PCT_RE.search(text)
                if m:
                    return m.group(1), self.cites(e)
        return None

    def _credit_rules(self, fam: Family) -> list[ObligationRule]:
        out = []
        credit_rows = [e for d in fam.docs for e in self.rows(d, "penalty")
                       if (e.value or {}).get("kind") == "service_credit" and self.clause_of(e) not in fam.amendments]
        by_clause: dict[str, list[Extraction]] = {}
        for e in credit_rows:
            by_clause.setdefault(self.clause_of(e) or e.doc_id, []).append(e)
        for clause, group in by_clause.items():
            prev_caps: list[dict[str, Any]] = []
            for version, rows in self._versions(group[0]):
                rows = group if version is None or version.source == "original" else rows
                for r in rows:
                    self._consumed.add(r.id or 0)
                tiers = [self._tier(r, self.evidence(r)) for r in rows]
                target = self._uptime_target(fam)
                extra_cites: list[dict[str, Any]] = []
                for t in tiers:
                    if t["type"] == "tier" and "below" not in t and target:
                        t["below"], t["threshold_source"] = target[0], "uptime commitment (cited)"
                        extra_cites = target[1]
                caps = []
                for r in rows:
                    cap = PCT_RE.search(str((r.value or {}).get("cap_raw") or ""))
                    if cap and not any(c["rate"] == str(pct(cap.group(0))) for c in caps):
                        caps.append({"type": "percent_of_monthly_fee_per_month", "rate": str(pct(cap.group(0))),
                                     "citation": self.cites(r)})
                flags = []
                if not caps and prev_caps:
                    caps = [{**c, "carried_over": True} for c in prev_caps]
                    flags.append("cap not restated by the amendment; the earlier version's cap is kept")
                if not caps:
                    flags.append(f"no credit cap extracted for {clause}; credits are computed uncapped")
                if any(t["type"] == "tier" and "below" not in t for t in tiers):
                    flags.append("uptime thresholds for a credit tier were not extracted; that tier applies only to "
                                 "months with no service at all")
                prev_caps = caps
                payer = fam.provider
                payee = fam.customer
                doc_id = rows[0].doc_id if rows else group[0].doc_id
                start = to_date(version.effective_from) if version and version.effective_from else None
                end = to_date(version.effective_to) if version and version.effective_to else None
                out.append(self._rule(
                    fam, doc_id, "credit", f"service_credit_{clause.replace(':', '_')}", start, name="service credit",
                    payer=payer, payee=payee, anchor="month_end", currency="USD",
                    formula="credit % of the Monthly Fee for the month, by Monthly Uptime Percentage tier"
                            + (" + additional credit per qualifying incident" if any(t["type"] == "additional" for t in tiers) else ""),
                    conditions=tiers, caps=caps, valid_to=iso(end),
                    citations=[c for r in rows for c in self.cites(r)] + extra_cites, flags=flags,
                ))
        # Claim windows: credit request deadlines, versioned like the credits.
        def is_window(x: Extraction) -> bool:
            """The customer's own credit request with a deadline in days (not 'upon request' duties of the provider)."""
            xv = x.value or {}
            action = str(xv.get("action") or "")
            dur = first_duration(xv.get("deadline_raw"), action)
            return bool(re.search(r"request", action, re.I) and not re.search(r"review|respond|upon\s+(?:\w+\s+)?request",
                                                                                action, re.I)
                        and dur and dur[1] == "days")

        def about_credits(x: Extraction) -> bool:
            clause = self.clause_of(x)
            text = self.store.get_clause(clause).text if clause else ""
            return bool(re.search(r"credit", self.evidence(x) + " " + text, re.I))

        windows = [e for d in fam.docs for e in self.rows(d, "obligation")
                   if is_window(e) and about_credits(e) and self.clause_of(e) not in fam.amendments]
        for e in windows:
            for version, rows in self._versions(e, pick=is_window):
                rows = [e] if version is None or version.source == "original" else rows
                r = rows[0] if rows else None
                if r is None:
                    continue
                self._consumed.add(r.id or 0)
                v = r.value or {}
                dur = first_duration(v.get("deadline_raw"), str(v.get("action") or ""))
                if dur is None:
                    continue
                start = to_date(version.effective_from) if version and version.effective_from else None
                end = to_date(version.effective_to) if version and version.effective_to else None
                out.append(self._rule(
                    fam, r.doc_id, "credit", f"credit_claim_window_{e.field_key}", start, name="credit claim window",
                    payer=v.get("obligor") or fam.customer, payee=v.get("obligee") or fam.provider, anchor="month_end",
                    offset_amount=dur[0], offset_unit=dur[1], offset_direction="after",
                    day_type=day_type_of(v.get("deadline_raw"), str(v.get("action") or "")) or "unspecified",
                    formula=f"written credit request within {dur[0]} {dur[1]} after the end of the month of the downtime",
                    valid_to=iso(end), citations=self.cites(r),
                    flags=[] if self.cites(r)[0]["verified"] else ["citation not verified by Thor"],
                ))
        return out

    # ---------------------------------------------------------------- suspension, termination, cure

    def _suspension_rules(self, fam: Family) -> list[ObligationRule]:
        out = []
        for d in fam.docs:
            for e in self.rows(d, "obligation"):
                v = e.value or {}
                if not re.search(r"suspend", str(v.get("action") or ""), re.I):
                    continue
                m = re.search(r"outstanding[^.;]*?balance[^.;]*?more than\s+(\d+|[a-z-]+)(?:\s*\((\d+)\))?\s+days",
                              str(v.get("trigger") or "") + " " + self.evidence(e), re.I)
                if not m:
                    continue
                self._consumed.add(e.id or 0)
                n = int(m.group(2) or m.group(1)) if (m.group(2) or m.group(1)).isdigit() else None
                if n is None:
                    continue
                out.append(self._rule(
                    fam, d, "penalty_trigger", "suspension_right", None, name="suspension right (unpaid balance)",
                    payer=fam.customer, payee=fam.provider, anchor="due_date", offset_amount=n, offset_unit="days",
                    offset_direction="after", day_type="unspecified",
                    formula=f"provider may suspend once an undisputed balance is outstanding more than {n} days",
                    conditions=[f"balance outstanding for more than {n} days"], citations=self.cites(e),
                    flags=[] if self.cites(e)[0]["verified"] else ["citation not verified by Thor (quote did not match)"],
                ))
        return out

    def _termination_rules(self, fam: Family) -> list[ObligationRule]:
        out = []
        for d in fam.docs:
            for e in self.rows(d, "termination"):
                v = e.value or {}
                trig = str(v.get("trigger") or "")
                if v.get("cure_days") or (v.get("cure_period_raw") and first_duration(v.get("cure_period_raw"))):
                    n = v.get("cure_days") or first_duration(v.get("cure_period_raw"))[0]  # type: ignore[index]
                    if re.search(r"insolvency|bankruptcy|receivership", trig, re.I):
                        continue      # a 60-day proceeding, not a cure period
                    self._consumed.add(e.id or 0)
                    out.append(self._rule(
                        fam, d, "cure", e.field_key, None, name=f"cure period: {trig[:80]}",
                        payer=None, payee=v.get("who_may_terminate"), anchor=f"event:{event_type(trig)}_notice",
                        offset_amount=int(n), offset_unit="days", offset_direction="after",
                        day_type=day_type_of(v.get("cure_period_raw"), f"{n} days") or "unspecified",
                        formula=f"termination right if not cured within {n} days after written notice",
                        conditions=[trig], citations=self.cites(e)))
                elif re.search(r"two\s+(?:\(2\)\s+)?consecutive", trig + " " + self.evidence(e), re.I):
                    self._consumed.add(e.id or 0)
                    notice = v.get("notice_days")
                    out.append(self._rule(
                        fam, d, "penalty_trigger", e.field_key, None, name="termination right: two consecutive months below target",
                        payer=fam.provider, payee=v.get("who_may_terminate") or fam.customer, anchor="month_end",
                        offset_amount=int(notice) if notice else None, offset_unit="days" if notice else None,
                        offset_direction="after", day_type=day_type_of(v.get("notice_period_raw")),
                        formula="customer may terminate after two consecutive months below the uptime target"
                                + (f", on {notice} days' written notice" if notice else ", on written notice")
                                + "; prorated refund of prepaid Fees",
                        conditions=[trig], citations=self.cites(e)))
        return out

    # ---------------------------------------------------------------- insurance (contract duty + company context)

    def _insurance_rules(self, fam: Family) -> list[ObligationRule]:
        lapse = next((e for d in fam.docs for e in self.rows(d, "obligation")
                      if re.search(r"cancel|not renewed|lapse", str((e.value or {}).get("trigger") or ""), re.I)
                      and re.search(r"notif", str((e.value or {}).get("action") or ""), re.I)), None)
        if lapse is None:
            return []
        self._consumed.add(lapse.id or 0)
        v = lapse.value or {}
        dur = first_duration(v.get("deadline_raw")) or (None, None)
        context: Resource | None = next(iter(self.store.list_resources("company_context")), None)
        expiries = sorted({d for d in (parse_long_date(m) for m in re.findall(r"Expiry:\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})",
                                                                               context.text or "")) if d}) if context else []
        if not expiries or dur[0] is None:
            fam.flags.append(f"{lapse.doc_id}/{lapse.field_key}: insurance lapse duty found, but no policy expiry date "
                             "in company/context.txt (or no notice period); not dated")
            return []
        no_renewal = bool(context and re.search(r"No renewal confirmation", context.text or "", re.I))
        quote = re.search(r"Expiry:\s*" + expiries[0].strftime("%B") + r"[^\n]*", context.text or "") if context else None
        return [self._rule(
            fam, lapse.doc_id, "report", "insurance_lapse_notification", None,
            name="notify customer of insurance lapse", payer=v.get("obligor") or US, payee=v.get("obligee") or fam.customer,
            anchor="fixed", anchor_date=iso(expiries[0]), offset_amount=dur[0], offset_unit=dur[1], offset_direction="after",
            day_type=day_type_of(v.get("deadline_raw")) or "unspecified",
            formula=f"if a required policy is not renewed at expiry ({iso(expiries[0])}), written notice within "
                    f"{dur[0]} {'business ' if day_type_of(v.get('deadline_raw')) == 'business' else ''}{dur[1]}",
            conditions=["only if the policy is not renewed"] + (
                ["company/context.txt: no renewal confirmation has been received"] if no_renewal else []),
            citations=self.cites(lapse) + [{"doc_id": "company/context.txt", "clause_id": None, "quote": quote.group(0).strip()
                                            if quote else None, "verified": bool(quote), "extraction_id": None}],
        )]

    # ---------------------------------------------------------------- remaining dated duties (event-driven)

    def _event_rules(self, fam: Family) -> list[ObligationRule]:
        out = []
        amended_docs = {a["from_doc"] for a in fam.amendments.values()}
        for d in fam.docs:
            for e in self.rows(d):
                if e.id in self._consumed or e.field_type not in ("obligation", "compliance"):
                    continue
                v = e.value or {}
                text = " ".join(str(v.get(k) or "") for k in ("deadline_raw", "window_raw", "action", "requirement"))
                dur = first_duration(v.get("deadline_raw"), v.get("window_raw"))
                if dur is None or not re.search(r"\b(?:within|after|before|in advance|prior)\b", text, re.I):
                    continue      # periodic duties ("at least quarterly") and plain restrictions are not dated here
                direction = "before" if re.search(r"\b(?:before|in advance|prior)\b", text, re.I) else "after"
                trigger = str(v.get("trigger") or v.get("action") or v.get("requirement") or "")
                notify = re.search(r"notif|notice|report|inform|provide|deliver|submit", text, re.I)
                start = None
                if d in amended_docs:
                    eff = next((x for x in self.rows(d, "effective_date") if (x.value or {}).get("iso")), None)
                    start = to_date(eff.value["iso"]) if eff else None
                out.append(self._rule(
                    fam, d, "report" if notify else "notice", e.field_key, start,
                    name=str(v.get("action") or v.get("requirement") or e.field_key)[:120],
                    payer=v.get("obligor"), payee=v.get("obligee") or v.get("beneficiary"),
                    anchor=f"event:{event_type(trigger)}", offset_amount=dur[0], offset_unit=dur[1], offset_direction=direction,
                    day_type=day_type_of(v.get("deadline_raw"), v.get("window_raw")) if dur[1] == "days" else None,
                    formula=f"{dur[0]} {dur[1]} {direction} the triggering event ({trigger[:80]})",
                    conditions=[trigger] if trigger else [], citations=self.cites(e),
                    flags=[] if self.cites(e)[0]["verified"] else ["citation not verified by Thor"]))
        return out

"""HEIMDALL: event monitoring and the task board.

    heimdall = Heimdall(store, heimdall_llm(cfg), cfg, files=files)
    result = heimdall.run("drop1", "2027-03-15")

One run = one event drop on one clock date (as_of):
  1. ingest (FR5.1): a drop is read only once it is released (heimdall.drop_release_checkpoints), and
     only its events dated on or before the clock date. An unparseable line is stored with
     status=unparseable and the reason; nothing is dropped and nothing crashes.
  2. map, code first: printed contract ids, counterparty names and e-mail domains, invoice references,
     amounts and dates are matched against the store and Norns' obligation instances, and structured
     messages (a provider's status-page outage, an uptime report, an invoice, a payment confirmation, a
     marketing mail) are classified in code. Only the rest goes to the LLM, up to 10 events per call
     (prompts/heimdall_map.md), within the Groq limits in config.heimdall. Document and clause ids it
     returns must exist in the store; otherwise the event is stored unmapped, with the reason.
  3. exposure: mapped events become Norns facts. norns.compute(as_of) without facts, then adding one
     event's fact at a time, gives the worst-case total before / after and the delta per event and per
     contract. A fact that changes no obligation and no exposure makes its event noise.
  4. alerts (FR5.3): Norns' deadlines, renewals and payments at the clock date, plus events that indicate
     a potential breach, on the fixed SEVERITY_SCALE, one per (contract, clause, kind, due date).
  5. tasks: one card per Norns obligation instance that is overdue, due or upcoming within 60 days.

``reassess(as_of)`` (no LLM) redoes 3-5 from the stored events and the task board's user facts. The
Streamlit page constructs Heimdall without an LLM client and calls it after every tag change.
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, field_validator

from odin.agents.base import Agent
from odin.config import OdinConfig
from odin.ingest.loader import CONTRACT_ID_IN_TEXT_RE, load_clock, parse_events, read_text_exact
from odin.llm import BudgetExceeded, CallRecord, LLMClient, LLMError, LLMTruncated
from odin.norns.calendar import iso, money, parse_long_date, parse_month_year, to_date
from odin.norns.engine import Inst, Norns, Timeline
from odin.norns.worst_case import NOT_IN_TOTAL, WorstCase, worst_case
from odin.state.errors import StoreError
from odin.state.files import FileStore
from odin.state.models import Event, HeimdallAlert, HeimdallEvent, HeimdallTask
from odin.state.store import StateStore

AGENT = "heimdall"
US = "quillhub"

# The fixed alert scale. Applied in build_alerts().
SEVERITY_SCALE = {
    "critical": "a potential breach, a suspension or termination right that is now open, or an overdue payment",
    "high": "due within 7 days, or a renewal-notice deadline within 30 days",
    "medium": "due within 30 days",
    "low": "informational",
}
SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
TASK_STATUSES = ("Not Complete", "In Progress", "Completed")
NORNS_FACTS = ("payment_made", "outage", "notice_sent")
FACT_TYPES = NORNS_FACTS + ("other",)
NOTICE_KINDS = ("non_renewal", "insurance_lapse", "credit_request")
NORNS_DONE = ("paid_on_time", "paid_late", "met")          # Norns' own "done": the card is Completed and locked
BREACH_TRIGGERS = ("suspension_right", "insurance_lapse_breach", "late_interest")

# --------------------------------------------------------------------------- code classification

DURATION_RE = re.compile(r"\bDuration:\s*(\d+)\s*minutes\b", re.I)
INCIDENT_START_RE = re.compile(r"\bIncident start:\s*(\d{4}-\d{2}-\d{2})", re.I)
MAINTENANCE_RE = re.compile(r"\bscheduled maintenance\b", re.I)
NOT_MAINTENANCE_RE = re.compile(r"\bno scheduled maintenance\b|\bnot (?:as )?scheduled maintenance\b", re.I)
UPTIME_LINE_RE = re.compile(r"Uptime target \(([^)]+)\):\s*([\d.]+)%\s*[—–-]+\s*(MET|MISSED)\b", re.I)
INVOICE_RE = re.compile(r"\bInvoice Number:\s*(\S+)", re.I)
AMOUNT_RE = re.compile(r"\bAmount:\s*\$\s?([\d,]+(?:\.\d+)?)", re.I)
DUE_DATE_RE = re.compile(r"\bDue Date:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
PAYMENT_RE = re.compile(r"\bpayment (?:received|confirmation|confirmed)\b|\bremittance advice\b|\bhas been paid\b", re.I)
MARKETING_SENDER_RE = re.compile(r"\b(?:marketing|newsletter|news|promo|promotions)@", re.I)
MARKETING_TEXT_RE = re.compile(r"\bnewsletter\b|\bunsubscribe\b|\bwebinar\b|\bregister here\b", re.I)
EMAIL_DOMAIN_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
CORP_WORDS = {"inc", "llc", "corp", "corporation", "ltd", "co", "group", "solutions", "company", "the"}


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9@. ]", " ", (text or "").lower())).strip()


def _party_key(name: str) -> str | None:
    """The distinctive part of a company name: 'Harbor Retail Group LLC' -> 'harbor'."""
    words = [w for w in _norm(name).replace(".", " ").split() if w not in CORP_WORDS]
    if not words:
        return None
    return words[0] if len(words[0]) >= 5 or len(words) == 1 else " ".join(words[:2])


def _is_us(name: str | None) -> bool:
    return US in (name or "").lower()


def _dec(value: Any) -> Decimal | None:
    try:
        d = Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


# --------------------------------------------------------------------------- LLM reply (lenient; checked in code)


class FactOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str = "other"
    contract: str | None = None
    date: str | None = None
    amount: Any = None
    period: str | None = None
    minutes: Any = None
    single_incident_minutes: Any = None
    notice: str | None = None
    description: str | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event_id: str = ""
    noise: bool = False
    noise_reason: str = ""
    type: str = ""
    doc_ids: list[str] = []
    clause_ids: list[str] = []
    fact: FactOut | None = None
    potential_breach: bool = False
    breach_reason: str = ""
    confidence: float = 0.0

    @field_validator("doc_ids", "clause_ids", mode="before")
    @classmethod
    def _ids(cls, v: Any) -> Any:
        return [v] if isinstance(v, str) else (v or [])

    @field_validator("noise_reason", "type", "breach_reason", mode="before")
    @classmethod
    def _text(cls, v: Any) -> Any:
        return "" if v is None else v

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, v: Any) -> Any:
        try:
            return min(max(float(v), 0.0), 1.0)
        except (TypeError, ValueError):
            return 0.0


class MapOut(BaseModel):
    events: list[EventOut]


# --------------------------------------------------------------------------- working types


@dataclass
class RawEvent:
    drop_name: str
    line_no: int
    raw: str
    event_id: str | None = None
    timestamp: str | None = None
    event_date: str | None = None
    channel: str | None = None
    sender: str | None = None
    recipient: str | None = None
    subject: str | None = None
    body: str | None = None
    parse_error: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(x for x in (self.sender, self.recipient, self.subject, self.body) if x)

    @property
    def label(self) -> str:
        return self.event_id or f"{self.drop_name} line {self.line_no}"


@dataclass
class Mapping:
    status: str                              # mapped | unmapped | noise | unparseable
    reason: str | None = None                # why unmapped / unparseable
    type: str | None = None
    doc_ids: list[str] = field(default_factory=list)
    clause_ids: list[str] = field(default_factory=list)
    fact: dict[str, Any] | None = None
    noise_reason: str | None = None
    mapped_by: str | None = None
    confidence: float | None = None
    potential_breach: bool = False
    breach_reason: str | None = None
    exposure: dict[str, Any] = field(default_factory=dict)

    def to_noise(self, reason: str) -> None:
        self.status, self.noise_reason = "noise", reason


@dataclass
class Live:
    """Worst-case totals on the clock date: no facts, the events' facts, and the events' plus the users' facts."""

    as_of: str
    baseline: Decimal
    after_events: Decimal
    live: Decimal
    by_contract: dict[str, dict[str, str]]
    alerts: list[HeimdallAlert] = field(default_factory=list)
    tasks: list[HeimdallTask] = field(default_factory=list)


@dataclass
class RunResult:
    drop_name: str
    as_of: str
    source: str
    events: list[HeimdallEvent]
    future: int
    live: Live
    llm: dict[str, Any]

    def counts(self) -> dict[str, int]:
        ev = self.events
        return {"total": len(ev), "mapped_by_code": sum(1 for e in ev if e.mapped_by == "code" and e.status == "mapped"),
                "mapped_by_llm": sum(1 for e in ev if e.mapped_by == "llm" and e.status == "mapped"),
                "noise": sum(1 for e in ev if e.status == "noise"), "unmapped": sum(1 for e in ev if e.status == "unmapped"),
                "unparseable": sum(1 for e in ev if e.status == "unparseable"), "not_yet_visible": self.future}


class TokenWindow:
    """Rolling 60-second token budget across calls: waits before a call that would exceed it."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.per_minute, self.clock, self.sleep = per_minute, clock, sleep
        self.spent: deque[tuple[float, int]] = deque()
        self.waited = 0.0

    def used(self) -> int:
        now = self.clock()
        while self.spent and now - self.spent[0][0] >= 60:
            self.spent.popleft()
        return sum(n for _, n in self.spent)

    def wait_for(self, planned: int) -> None:
        while self.spent and self.used() + planned > self.per_minute:
            delay = max(60 - (self.clock() - self.spent[0][0]) + 0.5, 0.5)
            self.sleep(delay)
            self.waited += delay

    def record(self, tokens: int) -> None:
        if tokens:
            self.spent.append((self.clock(), tokens))


def heimdall_llm(cfg: OdinConfig, **kwargs: Any) -> LLMClient:
    """The shared LLM settings with Heimdall's limits: max_tokens, reasoning_effort, call cap, no re-prompts."""
    h = cfg.heimdall
    settings = cfg.llm.model_copy(update={"reasoning_effort": h.reasoning_effort, "max_output_tokens": h.max_tokens})
    limits = cfg.limits.model_copy(update={"max_llm_calls": min(cfg.limits.max_llm_calls, h.max_llm_calls),
                                           "validation_retries": 0})
    return LLMClient(settings=settings, limits=limits, cache_dir=cfg.paths.llm_cache_dir, **kwargs)


def _totals(wc: WorstCase) -> tuple[Decimal, dict[str, Decimal]]:
    by: dict[str, Decimal] = {}
    for a in wc.accruals:
        if a.scenario == "worst_case" and a.category not in NOT_IN_TOTAL:
            by[a.contract] = by.get(a.contract, Decimal(0)) + a.amount
    return wc.total("worst_case"), {c: money(v) for c, v in sorted(by.items())}


def _citation(cites: list[dict[str, Any]]) -> dict[str, Any]:
    """The first clause citation (verified first) of a Norns instance."""
    ranked = sorted((c for c in cites if c.get("clause_id")), key=lambda c: not c.get("verified"))
    if not ranked:
        return {}
    c = ranked[0]
    return {"doc_id": c.get("doc_id") or c["clause_id"].split(":", 1)[0], "clause_id": c["clause_id"],
            "quote": " ".join(str(c.get("quote") or "").split())[:240] or None}


def _fmt_money(amount: Decimal | None) -> str:
    return f"${amount:,.2f}" if amount is not None else "no amount"


def _one_line(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Heimdall(Agent):
    name = AGENT
    prompt_files = {"map": "heimdall_map.md"}

    def __init__(self, store: StateStore, llm: LLMClient | None, cfg: OdinConfig, *, files: FileStore | None = None,
                 norns: Norns | None = None, run_id: str | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        super().__init__(store, llm, cfg, run_id)
        self.files = files
        self.norns = norns or Norns(store, None, cfg)        # Norns never gets an LLM from Heimdall
        self.window = TokenWindow(cfg.heimdall.tokens_per_minute, clock=clock, sleep=sleep)
        self._calls: list[CallRecord] = []
        self._clauses: dict[str, bool] = {}
        self._index_ready = False

    # ================================================================== public API

    def run(self, drop_name: str, as_of: date | str) -> RunResult:
        day = iso(to_date(as_of))
        assert day is not None
        released = self.released_drops(day)
        if drop_name not in released:
            when = self.release_date(drop_name)
            raise ValueError(f"{drop_name} is not released on {day}" + (f" (released {when})" if when else
                                                                         " (not in heimdall.drop_release_checkpoints)"))
        self.log("run_start", f"{drop_name}@{day}", None, model=self.llm.model if self.llm else None)
        with self.step("ingest", f"{drop_name}@{day}") as info:
            events, future, source = self.load_events(drop_name, day)
            info.update(output_ref=f"{len(events)} visible, {future} later", source=source)
        self._build_index()

        mappings: dict[int, Mapping] = {}
        pending: list[RawEvent] = []
        for ev in events:
            if ev.parse_error:
                mappings[ev.line_no] = Mapping("unparseable", reason=ev.parse_error)
                continue
            m = self.code_map(ev, day)
            if m is None:
                pending.append(ev)
            else:
                mappings[ev.line_no] = m
        self.log("code_map", f"{drop_name}@{day}", f"{len(mappings)} by code, {len(pending)} for the LLM",
                 by_code={e.label: mappings[e.line_no].status for e in events if e.line_no in mappings})
        mappings.update(self.llm_map(pending, day))

        with self.step("exposure", f"{drop_name}@{day}") as info:
            info["output_ref"] = self.exposure([(ev, mappings[ev.line_no]) for ev in events], day)
        rows = [self._row(ev, mappings[ev.line_no], day) for ev in events]
        self.store.replace_heimdall_events(day, drop_name, rows)
        live = self.reassess(day)
        usage = self._usage()
        self.log("run_end", f"{drop_name}@{day}", None, **usage)
        return RunResult(drop_name, day, source, rows, future, live, usage)

    # ================================================================== 1. ingest (drop model)

    def checkpoint(self, n: int) -> str:
        points = self.store.list_checkpoints() or load_clock(self.cfg.paths.pack_dir / "clock.json")
        match = next((p for p in points if p.idx == n), None)
        if match is None:
            raise ValueError(f"checkpoint {n} does not exist (0..{max(p.idx for p in points)}; 0 = start date)")
        return match.date

    def release_date(self, drop_name: str) -> str | None:
        idx = self.cfg.heimdall.drop_release_checkpoints.get(drop_name)
        return self.checkpoint(idx) if idx is not None else None

    def released_drops(self, as_of: str) -> list[str]:
        return [d for d in sorted(self.cfg.heimdall.drop_release_checkpoints)
                if (self.release_date(d) or "9999-12-31") <= as_of]

    def _drop_text(self, drop_name: str) -> tuple[str, str]:
        """The drop file: the stored copy (Supabase Storage / local file store) first, else the bundle."""
        rel = f"events/events_{drop_name}.jsonl"
        res = self.store.get_resource(rel)
        if res and res.storage_path and self.files is not None:
            try:
                return self.files.download(res.storage_path).decode("utf-8"), f"storage:{res.storage_path}"
            except (OSError, StoreError, UnicodeDecodeError) as exc:
                self.log("storage_fallback", rel, None, error=f"{type(exc).__name__}: {exc}")
        path = self.cfg.paths.bundle_dir / rel
        if not path.exists():
            raise FileNotFoundError(f"no stored copy and no bundle file for {rel}")
        return read_text_exact(path), f"bundle:{rel}"

    def load_events(self, drop_name: str, as_of: str) -> tuple[list[RawEvent], int, str]:
        """Visible lines of a released drop: events dated on or before as_of, plus unparseable lines."""
        text, source = self._drop_text(drop_name)
        visible, future = [], 0
        for e in parse_events(text, drop_name):
            ev = self._raw(e)
            if ev.parse_error is None and ev.event_date and ev.event_date > as_of:
                future += 1
                continue
            visible.append(ev)
        return visible, future, source

    @staticmethod
    def _raw(e: Event) -> RawEvent:
        ev = RawEvent(drop_name=e.drop, line_no=e.line_no, raw=e.raw, event_id=e.event_id, timestamp=e.timestamp,
                      channel=e.channel, sender=e.from_party, recipient=e.to_party, subject=e.subject, body=e.body,
                      parse_error=e.parse_error)
        if ev.parse_error is None:
            try:
                ev.event_date = datetime.fromisoformat(str(e.timestamp).replace("Z", "+00:00")).date().isoformat()
            except (TypeError, ValueError):
                ev.parse_error = f"no valid timestamp ({e.timestamp!r})"
        return ev

    # ================================================================== 2a. code mapping

    def _build_index(self) -> None:
        """Who each event could be about: printed ids, counterparty names and e-mail domains -> contract."""
        if self._index_ready:
            return
        self.norns.load()
        docs = {d.doc_id: d for d in self.store.list_documents(include_text=False)}
        self.docs = docs
        roots: dict[str, str] = {}
        for c, fam in self.norns.families.items():
            for d in fam.docs:
                if d in docs and docs[d].kind != "standard_terms":
                    roots.setdefault(d, c)
        rels = self.store.list_relations()
        for d, doc in docs.items():
            if d in roots or doc.kind == "standard_terms":
                continue
            host = next((r.from_doc for r in rels if r.type == "incorporates" and r.to_doc == d and r.from_doc in docs
                         and docs[r.from_doc].kind == "contract"), None) \
                or next((r.to_doc for r in rels if r.type == "amends" and r.from_doc == d and r.to_doc in docs), None)
            roots[d] = roots.get(host, host) if host else d
        self.roots = roots
        self.external_ids = {doc.external_id: roots.get(d, d) for d, doc in docs.items() if doc.external_id}
        names: dict[str, tuple[str, str]] = {}
        domains: dict[str, str] = {}
        for d, root in roots.items():
            for e in self.store.current_extractions(d, "thor"):
                v = e.value if isinstance(e.value, dict) else {}
                if e.field_type != "party" or not v.get("name") or _is_us(v["name"]):
                    continue
                key = _party_key(v["name"])
                if key:
                    names.setdefault(key, (root, v["name"]))
                for m in EMAIL_DOMAIN_RE.finditer(" ".join(str(x) for x in v.values())):
                    domains.setdefault(m.group(1).lower(), root)
        for c, fam in self.norns.families.items():
            for party in (fam.provider, fam.customer):
                if party and not _is_us(party) and _party_key(party):
                    names.setdefault(_party_key(party), (c, party))  # type: ignore[arg-type]
        self.names = names
        self.domains = domains
        self._index_ready = True

    def candidates(self, ev: RawEvent) -> list[str]:
        """Contracts the event names: by printed contract id, counterparty name or e-mail domain."""
        found: list[str] = []
        for m in CONTRACT_ID_IN_TEXT_RE.finditer(ev.text):
            root = self.external_ids.get(m.group(0))
            if root and root not in found:
                found.append(root)
        flat = f" {_norm(ev.text)} "
        for key, (root, _name) in self.names.items():
            if f" {key} " in flat and root not in found:
                found.append(root)
        for m in EMAIL_DOMAIN_RE.finditer(ev.text):
            root = self.domains.get(m.group(1).lower())
            if root and root not in found:
                found.append(root)
        return found

    def events_naming(self, drop_name: str, as_of: str, contract: str) -> list[str]:
        """Visible events of a drop that name ``contract`` (printed id, counterparty, e-mail domain): the ones a
        newly extracted contract can change the mapping of."""
        self._build_index()
        events, _future, _source = self.load_events(drop_name, as_of)
        return [ev.label for ev in events if ev.parse_error is None and contract in self.candidates(ev)]

    def _exists(self, clause_id: str) -> bool:
        if clause_id not in self._clauses:
            self._clauses[clause_id] = self.store.get_clause(clause_id) is not None
        return self._clauses[clause_id]

    def _rule_clauses(self, contract: str, kind: str, when: date) -> list[str]:
        """Clause ids cited by the contract's Norns rules of one kind, in force on a date."""
        out: list[str] = []
        for r in self.norns.rules:
            if r.contract != contract or r.kind != kind:
                continue
            if (r.valid_from and to_date(r.valid_from) > when) or (r.valid_to and when >= to_date(r.valid_to)):  # type: ignore[operator]
                continue
            for c in r.citations:
                cid = c.get("clause_id")
                if cid and cid not in out and self._exists(cid):
                    out.append(cid)
        return out

    def _docs_of(self, root: str | None, clause_ids: list[str]) -> list[str]:
        out = [root] if root else []
        for cid in clause_ids:
            d = cid.split(":", 1)[0]
            if d not in out:
                out.append(d)
        return out

    def code_map(self, ev: RawEvent, as_of: str) -> Mapping | None:
        """Structured messages, decided in code; None = code cannot map or classify it (it goes to the LLM)."""
        cands = self.candidates(ev)
        text = ev.text
        if MARKETING_SENDER_RE.search(ev.sender or "") or (MARKETING_TEXT_RE.search(text)
                                                           and not CONTRACT_ID_IN_TEXT_RE.search(text)):
            return Mapping("noise", type="marketing", noise_reason=f"marketing / newsletter from {ev.sender}: no "
                           "contract, clause, obligation or exposure", mapped_by="code", confidence=0.95)

        duration, start = DURATION_RE.search(text), INCIDENT_START_RE.search(text)
        if ev.channel == "status_log" and duration and start and len(cands) == 1 and cands[0] in self.norns.families \
                and (NOT_MAINTENANCE_RE.search(text) or not MAINTENANCE_RE.search(text)):
            root, minutes, when = cands[0], int(duration.group(1)), to_date(start.group(1))
            if when is None or iso(when) > as_of:  # type: ignore[operator]
                return None
            clauses = self._rule_clauses(root, "credit", when)
            fact = {"type": "outage", "date": iso(when), "contract": root, "minutes": minutes,
                    "single_incident_minutes": minutes, "source": "event", "event_id": ev.event_id}
            return Mapping("mapped", type="outage", doc_ids=self._docs_of(root, clauses), clause_ids=clauses, fact=fact,
                           mapped_by="code", confidence=0.95)

        targets = UPTIME_LINE_RE.findall(text)
        if targets and "uptime report" in (ev.subject or "").lower():
            if all(r.upper() == "MET" for _p, _t, r in targets):
                met = ", ".join(f"{p} {t}%" for p, t, _r in targets)
                return Mapping("noise", type="uptime_report", doc_ids=cands,
                               noise_reason=f"uptime report: every target met ({met}); no credit, obligation or exposure "
                                            "changes", mapped_by="code", confidence=0.95)
            return None                              # a missed target: the LLM maps it to the contract and clause

        amount = AMOUNT_RE.search(text)
        if amount and len(cands) == 1 and cands[0] in self.norns.families and (INVOICE_RE.search(text) or PAYMENT_RE.search(text)):
            inst = self._payment_instance(cands[0], _dec(amount.group(1)), text, as_of)
            if inst is None:
                return None
            clauses = [c for c in dict.fromkeys(x.get("clause_id") for x in inst.citations) if c and self._exists(c)]
            docs = self._docs_of(inst.contract, clauses)
            if PAYMENT_RE.search(text):
                fact = {"type": "payment_made", "date": ev.event_date, "contract": inst.contract,
                        "amount": str(_dec(amount.group(1))), "period": inst.period, "source": "event",
                        "event_id": ev.event_id}
                return Mapping("mapped", type="payment_received", doc_ids=docs, clause_ids=clauses, fact=fact,
                               mapped_by="code", confidence=0.9)
            stated = DUE_DATE_RE.search(text)
            stated_due = parse_long_date(stated.group(1)) if stated else None
            if stated_due is not None and stated_due != inst.due:
                # The invoice moves the due date Norns computes: an obligation change Norns has no fact type for.
                fact = {"type": "other", "description": f"invoice states due {stated_due}; Norns computes {inst.due} for "
                                                        f"{inst.name}", "source": "event", "event_id": ev.event_id}
                return Mapping("mapped", type="invoice_issued", doc_ids=docs, clause_ids=clauses, fact=fact,
                               mapped_by="code", confidence=0.9)
            return Mapping("noise", type="invoice_issued", doc_ids=docs, clause_ids=clauses,
                           noise_reason=f"invoice for {inst.name} ({_fmt_money(inst.amount)}), which Norns already "
                                        f"schedules (due {inst.due}); no obligation or exposure changes",
                           mapped_by="code", confidence=0.9)
        return None

    def _payment_instance(self, contract: str, amount: Decimal | None, text: str, as_of: str) -> Inst | None:
        """The Norns payment instance an invoice / payment message is about: contract, amount and billing month."""
        if amount is None:
            return None
        period = parse_month_year(text)
        t = self.norns.compute(as_of)
        hits = [i for i in t.payments() if i.contract == contract and i.amount == money(amount)
                and (period is None or i.period == period)]
        return hits[0] if len(hits) == 1 else None

    # ================================================================== 2b. LLM mapping (batched, budgeted)

    def _on_llm_call(self, rec: CallRecord) -> None:
        self._calls.append(rec)
        super()._on_llm_call(rec)

    def _tokens(self, text: str) -> int:
        return math.ceil(len(text) / self.cfg.heimdall.chars_per_token)

    def _contracts_text(self, roots: list[str]) -> str:
        lines = []
        for root in roots:
            doc = self.docs.get(root)
            fam = self.norns.families.get(root)
            members = sorted(d for d, r in self.roots.items() if r == root)
            party = next((name for _k, (r, name) in self.names.items() if r == root), None)
            role = ""
            if fam:
                role = " (Quillhub is the customer)" if _is_us(fam.customer) else " (Quillhub is the provider)"
            lines.append(f"- {root}: {doc.title if doc else root}; counterparty {party or 'unknown'}{role}; printed ID "
                         f"{doc.external_id if doc and doc.external_id else 'none'}; documents "
                         + ", ".join(f"{d} ({self.docs[d].kind})" for d in members if d in self.docs)
                         + ("; Norns tracks its payments and deadlines" if fam else "; outside Norns' timeline"))
        return "\n".join(lines)

    def _clauses_text(self, roots: list[str]) -> str:
        """Clause ids the model may cite: every clause of the candidate contracts' documents, top-level sections otherwise."""
        verbs = {"replace": "replaced", "modify": "modified", "insert": "inserted into", "delete": "deleted"}
        amended: dict[str, str] = {}
        for r in self.store.list_relations():
            cite = r.citation or {}
            if r.type == "amends" and cite.get("target_clause_id"):
                amended[cite["target_clause_id"]] = (f" [amended: {verbs.get(cite.get('operation') or 'replace', 'replaced')} "
                                                     f"by {r.clause_id} from {cite.get('effective_date') or '?'}]")
        lines = []
        for d in sorted(self.docs):
            if self.docs[d].kind == "standard_terms":
                continue
            detailed = self.roots.get(d, d) in roots
            for c in self.store.list_clauses(d):
                if not detailed and c.level != 1:
                    continue
                words = re.sub(r"[=\-]{3,}", " ", c.heading or c.text).split()
                if words and words[0].rstrip(".") == c.number:
                    words = words[1:]                    # "2.1 Provider will ..." -> "Provider will ..."
                lines.append(f"{c.clause_id} {_one_line(' '.join(words[:8]), 48)}{amended.get(c.clause_id, '')}")
        return "\n".join(lines)

    def _events_text(self, batch: list[RawEvent], limit: int) -> str:
        blocks = []
        for ev in batch:
            body = " ".join((ev.body or "").split())
            if len(body) > limit:
                body = body[:limit] + " …[truncated]"
            hint = ", ".join(self.candidates(ev)) or "none"
            blocks.append(f"[{ev.event_id}] {ev.event_date} · {ev.channel} · from: {ev.sender} · to: {ev.recipient} · "
                          f"subject: {ev.subject} · contracts named in it: {hint}\n{body}")
        return "\n\n".join(blocks)

    def _render(self, batch: list[RawEvent], as_of: str) -> tuple[str, str, int]:
        tpl = self.prompt("map")
        roots = sorted({r for ev in batch for r in self.candidates(ev)})
        all_roots = sorted(set(self.roots.values()))
        user = tpl.render(as_of=as_of, contracts=self._contracts_text(all_roots), clauses=self._clauses_text(roots),
                          count=len(batch), events=self._events_text(batch, self.cfg.heimdall.event_body_chars))
        return tpl.system, user, self._tokens(tpl.system) + self._tokens(user)

    def _plan_batches(self, events: list[RawEvent], as_of: str) -> list[list[RawEvent]]:
        h = self.cfg.heimdall
        batches: list[list[RawEvent]] = []
        current: list[RawEvent] = []
        for ev in events:
            trial = current + [ev]
            if current and (len(trial) > h.llm_batch_size
                            or self._render(trial, as_of)[2] + h.max_tokens > h.max_request_tokens):
                batches.append(current)
                current = [ev]
            else:
                current = trial
        if current:
            batches.append(current)
        return batches

    def llm_map(self, events: list[RawEvent], as_of: str) -> dict[int, Mapping]:
        """Events code could not map or classify, in batches; every reply is checked against the store."""
        out: dict[int, Mapping] = {}
        if not events:
            return out
        if self.llm is None:
            for ev in events:
                out[ev.line_no] = Mapping("unmapped", reason="code could not map or classify it, and no LLM client is "
                                                             "configured for this run")
            return out
        queue = self._plan_batches(events, as_of)
        while queue:
            batch = queue.pop(0)
            replies, error = self._call(batch, as_of)
            if error == "truncated" and len(batch) > 1:
                half = len(batch) // 2
                queue[:0] = [batch[:half], batch[half:]]
                continue
            for ev in batch:
                out[ev.line_no] = self._from_llm(ev, replies.get(ev.event_id or ""), as_of) if error is None else \
                    Mapping("unmapped", reason=f"LLM mapping failed: {error}")
        return out

    def _call(self, batch: list[RawEvent], as_of: str) -> tuple[dict[str, EventOut], str | None]:
        h = self.cfg.heimdall
        system, user, est = self._render(batch, as_of)
        if est + h.max_tokens > h.max_request_tokens:
            return {}, (f"about {est} input tokens + {h.max_tokens} max_tokens is over the {h.max_request_tokens}-token "
                        "request limit")
        self.window.wait_for(est + h.max_tokens)
        purpose = f"heimdall.map:{as_of}:" + ",".join(ev.label for ev in batch)
        start = len(self._calls)
        try:
            reply = self.llm.call_json(user, MapOut, system=system, purpose=purpose, include_schema=False,  # type: ignore[union-attr]
                                       max_tokens=h.max_tokens)
            result: tuple[dict[str, EventOut], str | None] = ({e.event_id.strip(): e for e in reply.events}, None)
        except LLMTruncated:
            result = ({}, "truncated")
        except BudgetExceeded as exc:
            result = ({}, f"BudgetExceeded: {exc}")
        except LLMError as exc:
            result = ({}, f"{type(exc).__name__}: {exc}")
        for rec in self._calls[start:]:
            if not rec.cache_hit and not rec.error:
                self.window.record(rec.input_tokens + rec.output_tokens)
        self.log("llm_batch", purpose, None if result[1] else f"{len(result[0])} result(s)", error=result[1],
                 est_input_tokens=est, max_tokens=h.max_tokens, events=[ev.label for ev in batch])
        return result

    def _from_llm(self, ev: RawEvent, out: EventOut | None, as_of: str) -> Mapping:
        if out is None:
            return Mapping("unmapped", reason="the LLM returned no result for this event")
        doc_ids = list(dict.fromkeys(d.strip() for d in out.doc_ids if d and d.strip()))
        clause_ids = list(dict.fromkeys(c.strip().strip("[]") for c in out.clause_ids if c and c.strip()))
        bad = [d for d in doc_ids if d not in self.docs] + [c for c in clause_ids if not self._exists(c)]
        if bad:
            return Mapping("unmapped", reason=f"the LLM named ids that do not exist in the store: {', '.join(bad)}",
                           type=out.type or None, mapped_by="llm", confidence=out.confidence)
        for c in clause_ids:
            if c.split(":", 1)[0] not in doc_ids:
                doc_ids.append(c.split(":", 1)[0])
        base = dict(type=re.sub(r"[^a-z0-9_]+", "_", out.type.strip().lower()).strip("_") or None, doc_ids=doc_ids,
                    clause_ids=clause_ids, mapped_by="llm", confidence=out.confidence)
        if out.noise:
            return Mapping("noise", noise_reason=_one_line(out.noise_reason or "the LLM marked it noise (no reason given)",
                                                           300), **base)  # type: ignore[arg-type]
        if not doc_ids:
            return Mapping("noise", noise_reason="maps to no contract or clause", **base)  # type: ignore[arg-type]
        fact, error = self._fact(out.fact, ev, as_of, doc_ids)
        if error:
            return Mapping("unmapped", reason=error, **base)  # type: ignore[arg-type]
        return Mapping("mapped", fact=fact, potential_breach=out.potential_breach,
                       breach_reason=_one_line(out.breach_reason, 300) if out.potential_breach and out.breach_reason else None,
                       **base)  # type: ignore[arg-type]

    def _fact(self, raw: FactOut | None, ev: RawEvent, as_of: str, doc_ids: list[str]) -> tuple[dict[str, Any] | None, str | None]:
        """A Norns fact from the LLM's, checked: a known contract, an ISO date on or before as_of, valid amounts."""
        if raw is None:
            return {"type": "other", "description": None, "source": "event", "event_id": ev.event_id}, None
        kind = (raw.type or "other").strip().lower()
        if kind not in FACT_TYPES:
            return None, f"fact type {raw.type!r} is not one of {' | '.join(FACT_TYPES)}"
        if kind == "other":
            return {"type": "other", "description": _one_line(raw.description or "", 200) or None, "source": "event",
                    "event_id": ev.event_id}, None
        contract = (raw.contract or doc_ids[0]).strip()
        if contract not in self.docs:
            return None, f"fact contract {contract!r} is not a document in the store"
        contract = self.roots.get(contract, contract)
        when = to_date(raw.date) if raw.date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw.date.strip()) else None
        if raw.date and when is None:
            return None, f"fact date {raw.date!r} is not YYYY-MM-DD"
        when = when or to_date(ev.event_date)
        if when is None or iso(when) > as_of:  # type: ignore[operator]
            return None, f"fact date {iso(when)} is after the clock date {as_of}"
        fact: dict[str, Any] = {"type": kind, "date": iso(when), "contract": contract, "source": "event",
                                "event_id": ev.event_id}
        period = (raw.period or "").strip() or None
        if period and not re.fullmatch(r"\d{4}-\d{2}", period):
            period = parse_month_year(period)
        if kind == "payment_made":
            amount = _dec(raw.amount)
            if amount is None or amount <= 0:
                return None, f"payment_made needs a positive amount (got {raw.amount!r})"
            fact.update(amount=str(money(amount)), period=period)
        elif kind == "outage":
            try:
                minutes = int(float(str(raw.minutes)))
                single = int(float(str(raw.single_incident_minutes))) if raw.single_incident_minutes not in (None, "") else None
            except (TypeError, ValueError):
                return None, f"outage needs minutes as numbers (got {raw.minutes!r}, {raw.single_incident_minutes!r})"
            if not 0 < minutes <= 44640 or (single is not None and not 0 < single <= minutes):
                return None, f"outage minutes out of range (minutes {minutes}, single incident {single})"
            fact.update(minutes=minutes, single_incident_minutes=single)
        else:
            notice = (raw.notice or "").strip().lower()
            if notice not in NOTICE_KINDS:
                return None, f"notice_sent needs notice: {' | '.join(NOTICE_KINDS)} (got {raw.notice!r})"
            fact.update(notice=notice, period=period)
        return fact, None

    # ================================================================== 3. exposure (Norns before / after)

    def exposure(self, pairs: list[tuple[RawEvent, Mapping]], as_of: str) -> str:
        """One event's fact at a time, in date order: worst case before / after, delta per event and per contract."""
        ordered = sorted(((ev, m) for ev, m in pairs if m.status == "mapped" and m.fact and m.fact["type"] in NORNS_FACTS),
                         key=lambda p: (p[0].event_date or "", p[0].event_id or "", p[0].line_no))
        facts: list[dict[str, Any]] = []
        t_prev = self.norns.compute(as_of, facts)
        wc_prev = worst_case(self.norns, t_prev)
        first, _ = _totals(wc_prev)
        seen: dict[tuple[Any, ...], str] = {}
        for ev, m in ordered:
            f = m.fact or {}
            key = (f["type"], f.get("contract"), f.get("date"), f.get("minutes"), f.get("amount"), f.get("notice"),
                   f.get("period"))
            if key in seen:
                m.to_noise(f"repeats the {f['type']} fact of {seen[key]}")
                continue
            t = self.norns.compute(as_of, facts + [f])
            wc = worst_case(self.norns, t)
            changes, breaches = self._diff(t_prev, t)
            (before, by_before), (after, by_after) = _totals(wc_prev), _totals(wc)
            delta = money(after - before)
            by = {c: str(money(by_after.get(c, Decimal(0)) - by_before.get(c, Decimal(0))))
                  for c in sorted(set(by_before) | set(by_after))
                  if by_after.get(c, Decimal(0)) != by_before.get(c, Decimal(0))}
            m.exposure = {"before": str(before), "after": str(after), "delta": str(delta), "by_contract": by,
                          "changes": changes}
            if delta == 0 and not changes:
                m.to_noise(f"Norns: the {f['type']} fact changes no obligation instance and no worst-case exposure")
                continue
            facts.append(f)
            seen[key] = ev.label
            if breaches:                              # Norns' computed reason replaces the model's wording
                m.potential_breach = True
                m.breach_reason = _one_line("; ".join(breaches), 300)
            t_prev, wc_prev = t, wc
        last, _ = _totals(wc_prev)
        return f"worst case {first} -> {last} with {len(facts)} fact(s)"

    def _diff(self, prev: Timeline, cur: Timeline) -> tuple[list[str], list[str]]:
        """What a fact changed in Norns' instances and triggers, and which of those changes point to a breach."""
        changes: list[str] = []
        breaches: list[str] = []
        before = {i.key: i for i in prev.instances}
        for i in cur.instances:
            p = before.get(i.key)
            if p is None:
                if i.amount is not None and i.amount <= 0:
                    continue                                  # e.g. a 0% credit: nothing owed, nothing to claim
                cite = _citation(i.citations).get("clause_id")
                changes.append(f"new {i.kind}: {i.name} ({i.contract}) {_fmt_money(i.amount)} due {i.due}")
                if i.kind == "credit" and _is_us(i.payer):
                    breaches.append(f"{i.contract}: uptime below the committed target in {i.period}; {i.payee} may "
                                    f"claim {_fmt_money(i.amount)} by {i.due} ({cite})")
            elif (p.status, p.paid_amount, p.amount, p.due) != (i.status, i.paid_amount, i.amount, i.due):
                changes.append(f"{i.name} ({i.contract}): {p.status} -> {i.status}")
        old = {(t["type"], t["instance"]) for t in prev.penalty_triggers}
        for t in cur.penalty_triggers:
            if (t["type"], t["instance"]) not in old:
                changes.append(f"trigger {t['type']} ({t['contract']}): {t['description']}")
                if t["type"] in BREACH_TRIGGERS:
                    breaches.append(f"{t['contract']}: {t['description']}")
        return changes, breaches

    # ================================================================== reassess: facts -> totals, tasks, alerts

    def event_rows(self, as_of: str) -> list[HeimdallEvent]:
        """Events behind the clock date: per drop, the latest run on or before as_of."""
        latest: dict[str, str] = {}
        for run_as_of, drop_name in self.store.heimdall_runs():
            if run_as_of <= as_of:
                latest[drop_name] = run_as_of
        rows: list[HeimdallEvent] = []
        for drop_name, run_as_of in sorted(latest.items()):
            rows += [e for e in self.store.list_heimdall_events(run_as_of, drop_name)
                     if e.event_date is None or e.event_date <= as_of]
        return rows

    @staticmethod
    def event_facts(rows: list[HeimdallEvent]) -> list[dict[str, Any]]:
        return [e.fact for e in rows if e.status == "mapped" and e.fact and e.fact.get("type") in NORNS_FACTS]

    def user_facts(self, as_of: str) -> list[dict[str, Any]]:
        return [t.fact for t in self.store.list_heimdall_tasks(as_of)
                if t.status == "Completed" and t.status_source == "user" and t.fact]

    def _live(self, as_of: str, ev_facts: list[dict[str, Any]], user: list[dict[str, Any]],
              t_e: Timeline | None = None) -> tuple[Live, Timeline]:
        base, _ = _totals(worst_case(self.norns, self.norns.compute(as_of)))
        t_e = t_e or self.norns.compute(as_of, ev_facts)
        t_all = self.norns.compute(as_of, ev_facts + user)
        wc_all = worst_case(self.norns, t_all)
        (after, by_e), (live, by_all) = _totals(worst_case(self.norns, t_e)), _totals(wc_all)
        by = {c: {"after_events": str(by_e.get(c, Decimal(0))), "live": str(by_all.get(c, Decimal(0)))}
              for c in sorted(set(by_e) | set(by_all))}
        return Live(as_of, base, after, live, by), t_all

    def totals(self, as_of: str) -> Live:
        """The worst case on the clock date: no facts, the events' facts, and the events' plus the users' (no writes)."""
        return self._live(as_of, self.event_facts(self.event_rows(as_of)), self.user_facts(as_of))[0]

    def reassess(self, as_of: str) -> Live:
        """Recompute Norns with the stored facts and rewrite the board's tasks and alerts (no LLM)."""
        rows = self.event_rows(as_of)
        ev_facts = self.event_facts(rows)
        t_e = self.norns.compute(as_of, ev_facts)
        tasks = self.sync_tasks(as_of, t_e)
        user = [t.fact for t in tasks if t.status == "Completed" and t.status_source == "user" and t.fact]
        live, t_all = self._live(as_of, ev_facts, user, t_e)
        live.alerts = self.build_alerts(as_of, t_all, rows)
        live.tasks = tasks
        self.store.replace_heimdall_alerts(as_of, live.alerts)
        self.log("reassess", as_of, f"worst case {live.live}", alerts=len(live.alerts), tasks=len(tasks),
                 user_facts=len(user))
        return live

    # ================================================================== 4. alerts

    def severity_for(self, days: int | None, renewal: bool = False) -> str:
        """The fixed scale for a deadline that many days away (overdue, breach and open rights are critical elsewhere)."""
        h = self.cfg.heimdall
        if days is None:
            return "low"
        if days <= h.due_soon_days or (renewal and days <= h.due_month_days):
            return "high"
        if days <= h.due_month_days:
            return "medium"
        return "low"

    def _clause_quote(self, clause_id: str) -> str | None:
        """The first line of a clause, verbatim (findable by plain text search)."""
        clause = self.store.get_clause(clause_id)
        if clause is None:
            return None
        return next((ln.strip() for ln in clause.text.split("\n") if len(ln.strip()) > 8), None)

    def build_alerts(self, as_of: str, t: Timeline, rows: list[HeimdallEvent]) -> list[HeimdallAlert]:
        day = to_date(as_of)
        assert day is not None
        window = day + timedelta(days=self.cfg.heimdall.task_window_days)
        out: dict[str, HeimdallAlert] = {}

        def add(severity: str, kind: str, contract: str | None, cite: dict[str, Any], due: date | str | None,
                message: str, source: str = "norns", event_id: str | None = None, instance_key: str | None = None) -> None:
            due_s = iso(to_date(due)) if due else None
            key = f"{contract or '-'}|{cite.get('clause_id') or '-'}|{kind}|{due_s or '-'}"
            alert = HeimdallAlert(as_of=as_of, alert_key=key, severity=severity, kind=kind, contract=contract,  # type: ignore[arg-type]
                                  clause_id=cite.get("clause_id"), due_date=due_s, message=_one_line(message),
                                  citation=cite, source=source, event_id=event_id, instance_key=instance_key,  # type: ignore[arg-type]
                                  run_id=self.run_id)
            old = out.get(key)
            if old is None or SEVERITY_RANK[severity] > SEVERITY_RANK[old.severity]:
                out[key] = alert

        for i in t.instances:
            if i.due is None:
                continue
            days = (i.due - day).days
            cite, c = _citation(i.citations), i.contract
            if i.kind == "payment":
                if i.status in ("unpaid", "partial") and i.due < day:
                    add("critical", "payment_overdue", c, cite, i.due, f"{c} {i.name}: {_fmt_money(i.outstanding)} overdue "
                        f"since {i.due} ({i.payer} -> {i.payee})", instance_key=i.key)
                elif i.status in ("upcoming", "partial") and i.due <= window:
                    add(self.severity_for(days), "payment_due", c, cite, i.due, f"{c} {i.name}: {_fmt_money(i.amount)} due "
                        f"{i.due} ({days} days; {i.payer} -> {i.payee})", instance_key=i.key)
            elif i.kind == "renewal":
                if i.status == "upcoming":
                    add(self.severity_for(days, renewal=True), "renewal_notice", c, cite, i.due,
                        f"{c} non-renewal notice deadline {i.due} ({days} days) for the term ending {i.anchor_date}",
                        instance_key=i.key)
                elif i.status == "missed":
                    add("low", "renewal_locked_in", c, cite, i.due, f"{c} non-renewal deadline {i.due} passed: the "
                        "agreement renews", instance_key=i.key)
            elif i.kind == "credit":
                ours = _is_us(i.payee)
                if i.status == "upcoming" and i.due <= window:
                    msg = (f"{c} claim the {i.period} service credit ({_fmt_money(i.amount)}) from {i.payer} by {i.due} "
                           f"({days} days)") if ours else (f"{c} {i.payee} may claim a {_fmt_money(i.amount)} credit for "
                                                          f"{i.period} by {i.due} ({days} days)")
                    add(self.severity_for(days), "credit_claim", c, cite, i.due, msg, instance_key=i.key)
                elif i.status == "missed":
                    add("low", "credit_lost" if ours else "credit_window_closed", c, cite, i.due,
                        f"{c} {i.period} credit ({_fmt_money(i.amount)}) not claimed by {i.due}", instance_key=i.key)
            elif i.status in ("upcoming", "missed"):
                if i.status == "missed":
                    add("critical", "potential_breach", c, cite, i.due, f"{c} {i.name}: deadline {i.due} missed",
                        instance_key=i.key)
                elif i.due <= window:
                    add(self.severity_for(days), "deadline", c, cite, i.due, f"{c} {i.name}: due {i.due} ({days} days)",
                        instance_key=i.key)

        for trig in t.penalty_triggers:
            cite = _citation(trig.get("citations") or [])
            if trig["type"] == "suspension_right" and trig.get("date") and trig["date"] <= as_of:
                add("critical", "suspension_right_open", trig["contract"], cite, trig["date"], f"{trig['contract']}: "
                    f"{trig['description']} (from {trig['date']})", instance_key=trig.get("instance"))
            elif trig["type"] == "insurance_lapse_breach":
                add("critical", "potential_breach", trig["contract"], cite, trig.get("date"),
                    f"{trig['contract']}: {trig['description']}", instance_key=trig.get("instance"))
        # A customer's termination right for persistent SLA failure: credits Quillhub owes in two consecutive months.
        for c in sorted({i.contract for i in t.instances}):
            owed = sorted({i.period for i in t.instances if i.contract == c and i.kind == "credit" and _is_us(i.payer)
                           and i.period and (i.amount or 0) > 0})
            pairs = [(a, b) for a, b in zip(owed, owed[1:]) if (int(b[:4]) * 12 + int(b[5:])) - (int(a[:4]) * 12 + int(a[5:])) == 1]
            rule = next((r for r in self.norns.rules if r.contract == c and r.kind == "penalty_trigger"
                         and "consecutive" in r.name.lower() + r.rule_id.lower()), None)
            if pairs and rule:
                a, b = pairs[-1]
                add("critical", "termination_right_open", c, _citation(rule.citations), f"{b}-01",
                    f"{c}: uptime below target in {a} and {b}; the customer may terminate for persistent failure")

        self._build_index()
        for e in rows:
            if e.status != "mapped" or not e.potential_breach:
                continue
            clause = e.clause_ids[0] if e.clause_ids else None
            cite = {"doc_id": clause.split(":", 1)[0], "clause_id": clause, "quote": self._clause_quote(clause)} if clause else {}
            contract = (e.fact or {}).get("contract") or (self.roots.get(e.doc_ids[0], e.doc_ids[0]) if e.doc_ids else None)
            add("critical", "potential_breach", contract, cite, e.event_date,
                f"{e.event_id}: {e.breach_reason or 'possible breach'}", source="event", event_id=e.event_id)
        return sorted(out.values(), key=lambda a: (-SEVERITY_RANK[a.severity], a.due_date or "9999", a.alert_key))

    # ================================================================== 5. task board

    def sync_tasks(self, as_of: str, t: Timeline) -> list[HeimdallTask]:
        """One card per Norns instance overdue, due or upcoming within the window; the users' tags are kept."""
        day = to_date(as_of)
        assert day is not None
        window = day + timedelta(days=self.cfg.heimdall.task_window_days)
        existing = {x.task_id: x for x in self.store.list_heimdall_tasks(as_of)}
        keep: list[HeimdallTask] = []
        for i in t.instances:
            if i.due is None:
                continue
            overdue = (i.status in ("unpaid", "partial") and i.due < day) or i.status == "missed"
            if not (overdue or day <= i.due <= window):
                continue
            old = existing.get(i.key)
            if i.status in NORNS_DONE:
                status, source, fact = "Completed", "norns", None
            elif old is not None and old.status_source == "user":
                status, source, fact = old.status, "user", old.fact
            else:
                status, source, fact = "Not Complete", "user", None
            task = HeimdallTask(as_of=as_of, task_id=i.key, title=i.name, contract=i.contract, kind=i.kind, period=i.period,
                                due_date=iso(i.due), amount=i.amount, citation=_citation(i.citations), status=status,  # type: ignore[arg-type]
                                status_source=source, norns_status=i.status, fact=fact, payer=i.payer, payee=i.payee)  # type: ignore[arg-type]
            same = old is not None and old.model_dump(exclude={"updated_at"}) == task.model_dump(exclude={"updated_at"})
            if same:
                task.updated_at = old.updated_at  # type: ignore[union-attr]
            else:
                self.store.upsert_heimdall_task(task)
            keep.append(task)
        gone = [k for k in existing if k not in {x.task_id for x in keep}]
        if gone:
            self.store.delete_heimdall_tasks(as_of, gone)
        return sorted(keep, key=lambda x: (x.due_date or "", x.task_id))

    def set_task_status(self, as_of: str, task_id: str, status: str) -> tuple[bool, str]:
        """A tag change from the board. Completing a payment records a payment_made fact (source=user) and recomputes."""
        if status not in TASK_STATUSES:
            raise ValueError(f"status must be one of {TASK_STATUSES}")
        task = next((x for x in self.store.list_heimdall_tasks(as_of) if x.task_id == task_id), None)
        if task is None:
            return False, f"no task {task_id!r} on {as_of}"
        if task.status_source == "norns":
            return False, f"Norns marks this {task.norns_status}; it cannot be changed on the board"
        fact = None
        if task.kind == "payment" and status == "Completed":
            inst = next((i for i in self.norns.compute(as_of, self.event_facts(self.event_rows(as_of))).instances
                         if i.key == task_id), None)
            amount = inst.outstanding if inst is not None and inst.outstanding > 0 else task.amount
            fact = {"type": "payment_made", "date": as_of, "contract": task.contract, "amount": str(amount),
                    "period": task.period, "source": "user", "task_id": task_id}
        if not self.store.set_heimdall_task_status(as_of, task_id, status, fact):
            return False, "the task changed meanwhile (Norns now marks it done)"
        self.log("task_status", task_id, status, as_of=as_of, previous=task.status, fact=fact)
        live = self.reassess(as_of)
        return True, f"{task.title}: {task.status} -> {status}; worst case now {_fmt_money(live.live)}"

    def process_label(self, contract: str) -> str:
        """'A1 · StratoNode hosting': the contract, its counterparty, and what it is to Quillhub."""
        self._build_index()
        name = next((n for _k, (r, n) in self.names.items() if r == contract), None)
        short = (name or contract).split()[0].rstrip(",.")
        fam = self.norns.families.get(contract)
        ctx = next(iter(self.store.list_resources("company_context")), None)
        hosting = bool(name and ctx and ctx.text and re.search(rf"hosting provider[^.]*\b{re.escape(short)}\b", ctx.text, re.I))
        role = "hosting" if hosting else ("customer" if fam and _is_us(fam.provider) else "supplier" if fam else "contract")
        return f"{contract} · {short} {role}"

    # ================================================================== bookkeeping

    def _row(self, ev: RawEvent, m: Mapping, as_of: str) -> HeimdallEvent:
        return HeimdallEvent(
            as_of=as_of, drop_name=ev.drop_name, line_no=ev.line_no, event_id=ev.event_id, raw=ev.raw,
            event_date=ev.event_date, channel=ev.channel, sender=ev.sender, recipient=ev.recipient, subject=ev.subject,
            status=m.status, status_reason=m.reason, type=m.type, doc_ids=m.doc_ids, clause_ids=m.clause_ids,  # type: ignore[arg-type]
            fact=m.fact, is_noise=m.status == "noise", noise_reason=m.noise_reason, mapped_by=m.mapped_by,  # type: ignore[arg-type]
            confidence=m.confidence, potential_breach=m.potential_breach and m.status == "mapped",
            breach_reason=m.breach_reason if m.status == "mapped" else None, exposure=m.exposure, run_id=self.run_id,
        )

    def _usage(self) -> dict[str, Any]:
        real = [r for r in self._calls if not r.cache_hit and not r.error]
        return {"llm_calls": len(real), "cache_hits": sum(1 for r in self._calls if r.cache_hit),
                "failed_attempts": sum(1 for r in self._calls if r.error),
                "input_tokens": sum(r.input_tokens for r in real), "output_tokens": sum(r.output_tokens for r in real),
                "rate_wait_s": round(self.window.waited, 1)}

    def report(self, result: RunResult) -> dict[str, Any]:
        live = result.live
        return {
            "drop": result.drop_name, "as_of": result.as_of, "run_id": self.run_id, "source": result.source,
            "counts": result.counts(), "llm": result.llm,
            "worst_case": {"before": str(live.baseline), "after_events": str(live.after_events), "live": str(live.live),
                           "by_contract": live.by_contract},
            "events": [e.model_dump(mode="json") for e in result.events],
            "alerts": [a.model_dump(mode="json") for a in live.alerts],
            "tasks": [t.model_dump(mode="json") for t in live.tasks],
        }

    def write_output(self, result: RunResult) -> Any:
        out_dir = self.cfg.paths.outputs_dir / "heimdall"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{result.drop_name}_{result.as_of}.json"
        path.write_text(json.dumps(self.report(result), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path

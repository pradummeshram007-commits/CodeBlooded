"""LOKI: adversarial review agent.

Reads each contract as the counterparty's lawyer would and reports ambiguous clauses,
one-sided terms and hidden liabilities (FR4.1), each with clause citations, an attack
path, and a severity and likelihood estimate (FR4.3).

    loki = Loki(store, llm, cfg)
    loki.run(["A1", "A2"], "2027-03-15")

Per document:
  1. ``build_review_context(doc_id, as_of)``: read-only, from Thor's output. Every clause in
     force on as_of (``effective_clause``; amended text carries the amendment's own clause
     id), the Standard Terms (all of them when incorporated, only the cited clauses when
     referenced), Thor's open flags and an index of its extractions as hints, and the trimmed
     company context. Only over the input budget (loki.max_input_tokens, or the model's
     max_request_tokens less max_tokens when lower) is the text split by top-level section,
     with incorporated Standard Terms as their own part(s).
  2. one LLM call per document (per part when split; ``prompts/loki_review.md``). With
     ``run(..., parallel=N)`` the documents' calls run at the same time in worker threads, unless
     the model allows one request at a time (Groq). A part the provider refuses as too large
     (413, with retry_413 off) is split in two and each half tried once.
  3. code checks, no LLM: citations verified with Thor's verifier, short clause references in
     the attack path ("2.2", "§D") rewritten as full ids from the cited documents, clause ids
     and figures checked against the store and the cited text, ambiguities need two readings.
     A failing finding is stored as rejected with the reason, never re-prompted. Duplicates are
     merged; impact is looked up in Norns' exposure_items (Loki never computes an amount).
  4. the document's findings for as_of replace any earlier ones; Loki's status per document
     goes to the workstreams, and the result to outputs/loki/<doc_id>_<as_of>.json.

Amendments and standard terms are not reviewed on their own: their text is reviewed inside
the documents they amend or that incorporate them.
"""
from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from odin.agents.base import Agent, PromptTemplate
from odin.agents.thor import word_number
from odin.citations import ClauseIndex, verify_citation
from odin.effective import effective_clause
from odin.ingest.loader import document_text, load_clock, read_text_exact
from odin.ingest.segmenter import DECORATION_RE
from odin.llm import BudgetExceeded, CallRecord, LLMError, LLMTooLarge
from odin.state.models import (
    Clause,
    Document,
    ExposureItem,
    Extraction,
    FindingCitation,
    FindingImpact,
    FindingReading,
    LokiFinding,
    Workstream,
)

AGENT = "loki"
OWN_COMPANY = "Quillhub"
NOT_REVIEWED_KINDS = ("amendment", "standard_terms")   # reviewed inside the documents they amend / that incorporate them

# The fixed scales. prompts/loki_review.md states the same lines word for word (checked when the prompt loads).
FINDING_TYPES = {
    "ambiguity": "wording that supports two or more reasonable readings",
    "one_sided": "a term that favours the counterparty with no matching protection for Quillhub",
    "hidden_liability": "an obligation or exposure that isn't obvious, e.g. buried in incorporated terms, triggered by a "
                        "later event, uncapped, or easy to forfeit",
}
SEVERITY_SCALE = {
    "critical": "gives the counterparty a right to suspend service or terminate, creates regulatory or legal exposure, "
                "or causes an uncapped loss",
    "high": "a recurring financial loss, or the loss of a right or remedy Quillhub relies on (e.g. credits forfeited)",
    "medium": "a bounded one-off loss or an extra operational burden",
    "low": "a wording risk with little practical effect",
}
LIKELIHOOD_SCALE = {
    "high": "triggered by routine operations or by events outside Quillhub's control",
    "medium": "plausible within the next 12 months",
    "low": "needs unusual events",
}
SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
LIKELIHOOD_RANK = {"high": 3, "medium": 2, "low": 1}
MAX_TITLE_WORDS = 15
MIN_STEPS, MAX_STEPS = 2, 5

# company/context.txt sections that say nothing about contract risk; dropped before trimming.
CONTEXT_SKIP_SECTIONS = ("BANK DETAILS",)

# --------------------------------------------------------------------------- figures (title / attack path check)

_NUM_WORD = (r"(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:-(?:one|two|three|four|five|six|seven|eight|nine))?"
             r"|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen"
             r"|seventeen|eighteen|nineteen)")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")
_MONTH_RE = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December"
             r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?")
FIGURE_RE = re.compile(
    rf"(?P<mdy>\b(?P<mdy_m>{_MONTH_RE})\s+(?P<mdy_d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<mdy_y>\d{{4}})\b)"
    rf"|(?P<dmy>\b(?P<dmy_d>\d{{1,2}})\s+(?P<dmy_m>{_MONTH_RE})\s+(?P<dmy_y>\d{{4}})\b)"
    r"|(?P<iso>\b(?P<iso_y>\d{4})-(?P<iso_m>\d{2})-(?P<iso_d>\d{2})\b)"
    rf"|(?P<my>\b(?P<my_m>{_MONTH_RE})\s+(?P<my_y>\d{{4}})\b)"
    r"|(?P<money>\$\s?(?P<money_n>\d[\d,]*(?:\.\d+)?))"
    r"|(?P<money2>\b(?P<money2_n>\d[\d,]*(?:\.\d+)?)\s?(?:USD|U\.S\.\s?Dollars|dollars)\b)"
    rf"|(?P<pct>(?P<pct_n>\b\d+(?:\.\d+)?|\b{_NUM_WORD})\s?(?:%|percent\b|per\s?cent\b))"
    rf"|(?P<dur>(?P<dur_n>\b\d+|\b{_NUM_WORD})(?:\s*\((?P<dur_digits>\d+)\))?(?:\s+|-)"
    r"(?:(?:consecutive|business|calendar|full|working)\s+){0,2}(?P<unit>minute|hour|day|week|month|year)s?\b)",
    re.I,
)
STEP_NUMBER_RE = re.compile(r"^\s*(?:step\s*)?\d+\s*[.):\-]\s*", re.I)

# Short clause references in an attack path: "Section 2.2", "Sec. 2.2", "Clause 4", "§2.2", "§D", and a bare
# dotted number "2.2" that is not an amount, percentage or duration.
SHORT_REF_RE = re.compile(
    r"(?:(?i:\bsections?|\bsec\.|\bclauses?)\s*|§§?\s*)(?P<pref>\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)(?!\w)"
    r"|(?<![\w.,:$§/-])(?P<bare>\d+(?:\.\d+)+)(?![\w%])"
    r"(?!\s*(?i:%|percent|per\s?cent|x\b|times\b|(?:(?:business|calendar|working)\s+)?"
    r"(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\b))"
)


def _number(token: str) -> float:
    token = token.strip()
    return float(token.replace(",", "")) if token[:1].isdigit() else float(word_number(token))


def _month(name: str) -> int:
    name = name.lower().rstrip(".")
    return next(i for i, m in enumerate(_MONTHS, start=1) if m.startswith(name[:3]))


def figures(text: str) -> list[tuple[tuple[Any, ...], str]]:
    """Amounts, percentages, durations and dates written in ``text``: (normalised key, as written)."""
    out: list[tuple[tuple[Any, ...], str]] = []
    flat = re.sub(r"\s+", " ", text)
    for m in FIGURE_RE.finditer(flat):
        raw = m.group(0).strip()
        try:
            if m.group("mdy") or m.group("dmy") or m.group("iso"):
                if m.group("iso"):
                    y, mo, d = int(m.group("iso_y")), int(m.group("iso_m")), int(m.group("iso_d"))
                else:
                    p = "mdy" if m.group("mdy") else "dmy"
                    y, mo, d = int(m.group(f"{p}_y")), _month(m.group(f"{p}_m")), int(m.group(f"{p}_d"))
                out.append((("date", date(y, mo, d).isoformat()), raw))
            elif m.group("my"):
                out.append((("month", f"{int(m.group('my_y')):04d}-{_month(m.group('my_m')):02d}"), raw))
            elif m.group("money") or m.group("money2"):
                out.append((("money", _number(m.group("money_n") or m.group("money2_n"))), raw))
            elif m.group("pct"):
                out.append((("pct", _number(m.group("pct_n"))), raw))
            elif m.group("dur"):
                n = float(m.group("dur_digits")) if m.group("dur_digits") else _number(m.group("dur_n"))
                out.append((("dur", n, m.group("unit").lower()), raw))
        except (ValueError, StopIteration, KeyError):
            continue   # not a real date / number: nothing to check
    return out


def figure_keys(text: str) -> set[tuple[Any, ...]]:
    keys = {k for k, _ in figures(text)}
    keys |= {("month", k[1][:7]) for k in keys if k[0] == "date"}   # "January 2027" matches "January 1, 2027"
    return keys


# --------------------------------------------------------------------------- LLM reply (lenient: checks happen in code)


class CitationOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    clause_id: str = ""
    quote: str = ""


class ReadingOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reading: str = ""
    counterparty_argues: bool = False


class FindingOut(BaseModel):
    """What the model returns per finding. Every rule is checked in code afterwards, so nothing here
    makes the reply invalid (a re-prompt) except a wrong JSON shape."""

    model_config = ConfigDict(extra="ignore")
    type: str = ""
    title: str = ""
    citations: list[CitationOut] = []
    readings: list[ReadingOut] = []
    attack_path: list[str] = []
    severity: str = ""
    severity_reason: str = ""
    likelihood: str = ""
    likelihood_reason: str = ""
    confidence: float = 0.0

    @field_validator("citations", "readings", mode="before")
    @classmethod
    def _one_to_list(cls, v: Any) -> Any:
        return [v] if isinstance(v, dict) else v

    @field_validator("readings", mode="before")
    @classmethod
    def _plain_readings(cls, v: Any) -> Any:
        return [{"reading": r} if isinstance(r, str) else r for r in v] if isinstance(v, list) else v

    @field_validator("attack_path", mode="before")
    @classmethod
    def _steps(cls, v: Any) -> Any:
        return [s for s in v.split("\n") if s.strip()] if isinstance(v, str) else v

    @field_validator("type", "title", "severity", "severity_reason", "likelihood", "likelihood_reason", mode="before")
    @classmethod
    def _text(cls, v: Any) -> Any:
        return "" if v is None else v

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, v: Any) -> Any:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0       # e.g. "high": not a number; the finding keeps confidence 0


class ReviewOut(BaseModel):
    findings: list[FindingOut]


# --------------------------------------------------------------------------- review context


@dataclass
class ContextClause:
    clause_id: str            # the id the model cites: an amendment's own id for amended text
    doc_id: str
    top_id: str               # top-level section it is split with (an amendment rides with the clause it amends)
    group: str                # main (the document, its amendments, cited STD clauses) | std (incorporated STD)
    text: str                 # verbatim own text: a section's text stops at its first sub-clause
    char_start: int           # own-text span in the document's text
    char_end: int
    note: str | None = None   # shown after the marker, e.g. "amendment text in force from 2027-01-01; replaces A2:3.2"
    terms: list[Extraction] = field(default_factory=list)   # Thor's extractions in force for this clause version


@dataclass
class HintLine:
    clause_ids: set[str]      # empty = about the document as a whole
    text: str


@dataclass
class ReviewPart:
    index: int
    total: int
    clause_ids: list[str]
    note: str
    flags: list[str]
    extractions: list[str]
    est_tokens: int = 0
    suffix: str = ""          # "a" / "b": a half of a part the provider refused as too large

    @property
    def label(self) -> str:
        return f"{self.index}{self.suffix}/{self.total}"


@dataclass
class ReviewContext:
    doc: Document
    as_of: str
    title: str
    parties: list[dict[str, str]]             # [{name, role}] from Thor's party fields
    counterparty: str | None                  # the party that isn't Quillhub
    std_doc: str | None
    std_mode: str | None                      # incorporated | referenced | None
    std_relation_clause: str | None           # the clause that incorporates / references the Standard Terms
    clauses: list[ContextClause]
    flags: list[HintLine]                     # Thor's open flags, one line each
    extractions: list[HintLine]               # Thor's extractions in force, one line each: field: value [clause_id]
    company_context: str
    parts: list[ReviewPart] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def ids(self, doc_id: str | None = None) -> set[str]:
        return {c.clause_id for c in self.clauses if doc_id is None or c.doc_id == doc_id}

    def by_id(self) -> dict[str, ContextClause]:
        return {c.clause_id: c for c in self.clauses}


# --------------------------------------------------------------------------- results


@dataclass
class PartResult:
    part: ReviewPart
    purpose: str = ""
    output: ReviewOut | None = None
    error: str | None = None
    calls: list[CallRecord] = field(default_factory=list)
    seconds: float = 0.0
    too_large: bool = False   # the provider refused the request as too large (413)

    @property
    def model(self) -> str | None:
        ok = [r for r in self.calls if not r.error]
        return ok[-1].model if ok else None

    def usage(self) -> dict[str, int]:
        real = [r for r in self.calls if not r.cache_hit and not r.error]
        return {"llm_calls": len(real), "cache_hits": sum(1 for r in self.calls if r.cache_hit),
                "failed_attempts": sum(1 for r in self.calls if r.error),
                "input_tokens": sum(r.input_tokens for r in real), "output_tokens": sum(r.output_tokens for r in real)}


@dataclass
class DocReview:
    doc_id: str
    as_of: str
    status: str                       # complete | partial | failed | skipped (pending: context built, not reviewed yet)
    reason: str | None = None
    context: ReviewContext | None = None
    parts: list[PartResult] = field(default_factory=list)
    findings: list[LokiFinding] = field(default_factory=list)
    stored: bool = False
    seconds: float = 0.0              # wall clock spent on this document: context, LLM call(s), checks
    llm_seconds: float = 0.0          # of which LLM call(s), including client-side rate-limit waits
    output_path: Path | None = None

    @property
    def accepted(self) -> list[LokiFinding]:
        return [f for f in self.findings if f.status == "accepted"]

    @property
    def rejected(self) -> list[LokiFinding]:
        return [f for f in self.findings if f.status == "rejected"]

    def usage(self) -> dict[str, int]:
        total: dict[str, int] = {}
        for p in self.parts:
            for k, v in p.usage().items():
                total[k] = total.get(k, 0) + v
        return total


def _iso(d: date | str) -> str:
    return d.isoformat() if isinstance(d, date) else date.fromisoformat(str(d)[:10]).isoformat()


def _clean(text: str) -> str:
    """Clause text for the prompt: no separator rules or indentation (the verifier ignores whitespace)."""
    lines = [line.strip() for line in text.split("\n") if not DECORATION_RE.match(line)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _own_spans(clauses: list[Clause]) -> dict[str, tuple[int, int]]:
    """Each clause's own text span: a section stops where its first sub-clause starts."""
    ordered = sorted(clauses, key=lambda c: (c.char_start, c.level))
    out = {}
    for k, c in enumerate(ordered):
        nxt = ordered[k + 1].char_start if k + 1 < len(ordered) else None
        out[c.clause_id] = (c.char_start, nxt if nxt is not None and c.char_start < nxt < c.char_end else c.char_end)
    return out


def _compact(value: Any, limit: int = 60) -> str:
    if isinstance(value, dict):
        parts = [f"{k}={_compact(v, limit)}" for k, v in value.items() if v not in (None, "", [], {})]
        return "; ".join(parts)
    if isinstance(value, list):
        return ", ".join(_compact(v, limit) for v in value)
    s = " ".join(str(value).split())
    return s if len(s) <= limit else s[: limit - 3] + "..."


# Extraction keys left out of the hint index: who-is-who boilerplate, and numbers derived from a *_raw wording kept beside them.
_HINT_SKIP = {"recurring", "obligee", "beneficiary", "category", "currency", "to_doc_resolved", "from_doc", "role"}
_DERIVED_SUFFIXES = ("_iso", "_days", "_months", "_amount", "_unit")


def _hint_value(value: dict[str, Any]) -> str:
    raws = {k[: -len("_raw")] for k in value if k.endswith("_raw")} | ({""} if "raw" in value else set())
    keep = {}
    for k, v in value.items():
        if k in _HINT_SKIP or v in (None, "", [], {}):
            continue
        stem = next((k[: -len(s)] for s in _DERIVED_SUFFIXES if k.endswith(s)), None)
        if (stem is not None and (stem in raws or stem.rsplit("_", 1)[0] in raws)) or (k == "iso" and "" in raws):
            continue
        keep[k] = v
    return _compact(keep, 45)


class Loki(Agent):
    name = AGENT
    prompt_files = {"review": "loki_review.md"}

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._calls: list[CallRecord] = []
        self._indexes: dict[str, ClauseIndex] = {}
        self._clause_exists: dict[str, bool] = {}
        self._scales_checked = False
        self._clause_id_re: re.Pattern[str] | None = None

    # ================================================================== public API

    def run(self, doc_ids: list[str], as_of: date | str, parallel: int = 1) -> list[DocReview]:
        """Review each document. With ``parallel`` > 1 the documents' LLM calls run at the same time in worker
        threads; contexts, checks and every store write stay on this thread (as in Thor)."""
        day = _iso(as_of)
        doc_ids = list(dict.fromkeys(doc_ids))
        workers = self.workers(parallel)
        self.log("run_start", ",".join(doc_ids), day, model=self.llm.model if self.llm else None,
                 max_llm_calls=self.llm.limits.max_llm_calls if self.llm else None, parallel=workers)
        if workers <= 1 or len(doc_ids) <= 1:
            reviews = [self.review(doc_id, day) for doc_id in doc_ids]
        else:
            reviews = [self._prepare(doc_id, day) for doc_id in doc_ids]
            pending = [r for r in reviews if r.status == "pending"]
            if pending:
                with ThreadPoolExecutor(max_workers=min(workers, len(pending))) as pool:
                    list(pool.map(self._call_llm, pending))
                self.flush_llm_log()
            reviews = [self._conclude(r) if r.status == "pending" else r for r in reviews]
        self.log("run_end", None, None, llm_calls=self.llm.stats.calls if self.llm else 0,
                 tokens=self.llm.stats.tokens if self.llm else 0,
                 statuses={r.doc_id: r.status for r in reviews})
        return reviews

    def workers(self, parallel: int) -> int:
        """Documents reviewed at the same time: ``parallel``, within the model's max_concurrent (Groq: 1)."""
        limit = self.llm.settings.max_concurrent if self.llm else 0
        return max(1, min(parallel, limit) if limit else parallel)

    def review(self, doc_id: str, as_of: date | str) -> DocReview:
        review = self._prepare(doc_id, _iso(as_of))
        if review.status != "pending":
            return review
        self._call_llm(review)
        return self._conclude(review)

    def _prepare(self, doc_id: str, day: str) -> DocReview:
        """The document's review context ("pending"); a document that can't be reviewed is finished here."""
        t0 = time.monotonic()
        doc = self.store.get_document(doc_id, include_text=False)
        if doc is None:
            return DocReview(doc_id, day, "failed", f"document {doc_id!r} is not in the store")
        if doc.kind in NOT_REVIEWED_KINDS:
            hosts = sorted({r.to_doc if doc.kind == "amendment" else r.from_doc for r in self.store.list_relations(doc_id)
                            if (r.type == "amends" and r.from_doc == doc_id)
                            or (r.type == "incorporates" and r.to_doc == doc_id)})
            why = (f"{doc_id} is {'an amendment' if doc.kind == 'amendment' else 'standard terms'}: not reviewed on its "
                   f"own; its text is reviewed inside {', '.join(hosts) if hosts else 'the documents it applies to'}")
            self.log("skip", doc_id, day, reason=why)
            return DocReview(doc_id, day, "skipped", why)

        try:
            with self.step("context", f"{doc_id}@{day}") as info:
                ctx = self.build_review_context(doc_id, day)
                info.update(output_ref=f"{len(ctx.parts)} part(s)", clauses=len(ctx.clauses), std_mode=ctx.std_mode,
                            counterparty=ctx.counterparty, est_tokens=[p.est_tokens for p in ctx.parts], notes=ctx.notes)
        except (LookupError, ValueError, OSError) as exc:
            return self._finish(DocReview(doc_id, day, "failed", f"review context: {type(exc).__name__}: {exc}"))
        review = DocReview(doc_id, day, "pending", context=ctx, seconds=time.monotonic() - t0)
        if not ctx.parts:
            review.status, review.reason = "failed", "no clause text in force on this date"
            return self._finish(review)
        return review

    def _call_llm(self, review: DocReview) -> None:
        """The document's LLM call(s). No store access, so it can run in a worker thread."""
        ctx = review.context
        assert ctx is not None
        t0 = time.monotonic()
        for part in ctx.parts:
            result = self._review_part(ctx, part)
            halves = self._halves(ctx, part) if result.too_large else []
            if halves:
                # Refused as too large (413): split in two, each half tried once; never retried unchanged.
                ctx.notes.append(f"part {part.label} was refused as too large (413): split into "
                                 f"{' and '.join(f'{h.label} ({h.est_tokens} est. tokens)' for h in halves)}")
                review.parts += [self._review_part(ctx, h) for h in halves]
            else:
                review.parts.append(result)
        review.llm_seconds = time.monotonic() - t0

    def _conclude(self, review: DocReview) -> DocReview:
        """Log the calls, run the code checks, store the findings and set the document's status."""
        t0 = time.monotonic()
        ctx, doc_id, day = review.context, review.doc_id, review.as_of
        assert ctx is not None
        for p in review.parts:
            self.log("review_part", p.purpose, f"{len(p.output.findings)} finding(s)" if p.output else None,
                     error=p.error, est_tokens=p.part.est_tokens, clause_ids=p.part.clause_ids,
                     seconds=round(p.seconds, 1), **p.usage())

        failed = [p for p in review.parts if p.output is None]
        try:
            if len(failed) < len(review.parts):
                with self.step("checks", f"{doc_id}@{day}") as info:
                    review.findings = self.check(ctx, review.parts)
                    info.update(output_ref=f"{len(review.accepted)} accepted / {len(review.rejected)} rejected",
                                rejected={f.title: f.rejection_reason for f in review.rejected})
                self.store.replace_loki_findings(doc_id, day, review.findings)
                review.stored = True
            reasons = [f"part {p.part.label} failed: {p.error}" for p in failed]
            if not failed:
                review.status = "complete"
            elif len(failed) < len(review.parts):
                review.status = "partial"
            else:
                review.status = "failed"
                reasons.append("no call succeeded; earlier findings for this date, if any, were kept")
            review.reason = "; ".join(reasons) or None
        except Exception as exc:  # noqa: BLE001 - reported as the document's status, with the reason
            review.status, review.reason = "failed", f"checks failed: {type(exc).__name__}: {exc}"
            review.findings, review.stored = [], False
        review.seconds += review.llm_seconds + (time.monotonic() - t0)
        return self._finish(review)

    # ================================================================== 1. review context (read-only)

    def build_review_context(self, doc_id: str, as_of: date | str) -> ReviewContext:
        """Everything Loki shows the model for one document on ``as_of`` (no LLM, no writes)."""
        day = _iso(as_of)
        doc = self.store.get_document(doc_id, include_text=False)
        if doc is None:
            raise LookupError(f"document {doc_id!r} is not in the store")
        notes: list[str] = []
        if doc.status != "complete":
            notes.append(f"Thor's status for {doc_id} is {doc.status}: {doc.status_reason or 'no reason given'}")

        tops = self._tops(doc_id)
        clauses = self._in_force(doc, day, "main", tops, notes)
        std_doc, std_mode, std_clause = self._standard_terms(doc_id)
        if std_doc and std_mode == "incorporated":
            std_doc_row = self.store.get_document(std_doc, include_text=False)
            assert std_doc_row is not None
            clauses += self._in_force(std_doc_row, day, "std", self._tops(std_doc), notes)
        elif std_doc and std_mode == "referenced":
            cited = self._cited_std_clauses(doc_id, std_doc, clauses)
            if cited:
                std_doc_row = self.store.get_document(std_doc, include_text=False)
                assert std_doc_row is not None
                clauses += self._in_force(std_doc_row, day, "main", self._tops(std_doc), notes, only=cited)
            notes.append(f"{doc_id} references {std_doc} without incorporating it: "
                         f"{'cited clauses ' + ', '.join(sorted(cited)) if cited else 'no specific clause cited'}")

        parties = self._parties(doc_id)
        counterparty = next((p["name"] for p in parties if OWN_COMPANY.lower() not in p["name"].lower()), None)
        if counterparty is None:
            notes.append("no counterparty among Thor's party fields")
        ctx = ReviewContext(
            doc=doc, as_of=day, title=doc.title, parties=parties, counterparty=counterparty, std_doc=std_doc,
            std_mode=std_mode, std_relation_clause=std_clause, clauses=clauses,
            flags=self._flag_lines(doc_id, {c.clause_id for c in clauses}),
            extractions=self._extraction_lines(clauses), company_context=self._company_context(), notes=notes,
        )
        ctx.parts = self._plan_parts(ctx)
        return ctx

    def _tops(self, doc_id: str) -> dict[str, str]:
        """clause_id -> its top-level section."""
        parents = {c.clause_id: c.parent_id for c in self.store.list_clauses(doc_id)}
        out = {}
        for cid in parents:
            top = cid
            while parents.get(top):
                top = parents[top]  # type: ignore[assignment]
            out[cid] = top
        return out

    def _in_force(self, doc: Document, day: str, group: str, tops: dict[str, str], notes: list[str],
                  only: set[str] | None = None) -> list[ContextClause]:
        """The document's clauses as in force on ``day``; amended text under the amendment's own clause id."""
        clauses = self.store.list_clauses(doc.doc_id)
        if only is not None:
            index = self._index(doc.doc_id)
            wanted: set[str] = set()
            for cid in only:
                wanted |= index.descendants(cid)
            clauses = [c for c in clauses if c.clause_id in wanted]
        spans = _own_spans(self.store.list_clauses(doc.doc_id))
        text = document_text(self.cfg, doc)
        out: list[ContextClause] = []
        shown_amendments: set[str] = set()
        for c in sorted(clauses, key=lambda c: c.ordinal):
            ec = effective_clause(doc.doc_id, c.clause_id, day, store=self.store)
            notes.extend(n for n in ec.notes if n not in notes)
            s, e = spans[c.clause_id]
            original = ContextClause(c.clause_id, doc.doc_id, tops.get(c.clause_id, c.clause_id), group, text[s:e], s, e,
                                     terms=ec.versions[0].terms)
            if ec.source == "original":
                original.terms = ec.terms
                out.append(original)
                continue
            by = ec.version.amended_by or {}
            amending_id, op, since = by.get("clause_id"), by.get("operation") or "replace", ec.version.effective_from
            if ec.source == "deleted":
                notes.append(f"{c.clause_id} deleted by {amending_id} from {since}: not shown")
                continue
            if op in ("modify", "insert"):
                # Only part of the clause changes: the original stays in force alongside the amendment.
                original.note = f"amended from {since} by {amending_id} below; where they differ, {amending_id} controls"
                out.append(original)
            if amending_id and amending_id not in shown_amendments:
                amending = self.store.get_clause(amending_id)
                if amending is None:
                    notes.append(f"{c.clause_id}: amending clause {amending_id} not in the store; original shown")
                    if op not in ("modify", "insert"):
                        out.append(original)
                    continue
                amending_doc = self.store.get_document(amending.doc_id, include_text=False)
                assert amending_doc is not None
                a_text = document_text(self.cfg, amending_doc)
                verb = "replaces" if op == "replace" else f"{op}s" if op != "modify" else "modifies"
                out.append(ContextClause(amending_id, amending.doc_id, tops.get(c.clause_id, c.clause_id), group,
                                         a_text[amending.char_start:amending.char_end], amending.char_start,
                                         amending.char_end, note=f"amendment text in force from {since}; {verb} {c.clause_id}",
                                         terms=ec.terms))
                shown_amendments.add(amending_id)
        return out

    def _standard_terms(self, doc_id: str) -> tuple[str | None, str | None, str | None]:
        """(std doc_id, incorporated | referenced, citing clause) from the document's own relations."""
        std_ids = {d.doc_id for d in self.store.list_documents(include_text=False) if d.kind == "standard_terms"}
        rels = [r for r in self.store.list_relations(doc_id) if r.from_doc == doc_id and r.to_doc in std_ids]
        inc = next((r for r in rels if r.type == "incorporates"), None)
        if inc:
            return inc.to_doc, "incorporated", inc.clause_id
        ref = next((r for r in rels if r.type == "references"), None)
        if ref:
            return ref.to_doc, "referenced", ref.clause_id
        return None, None, None

    _STD_SECTION_RE = re.compile(r"Sections?\s+(\d+(?:\.\d+)*)(?:\s*\([a-z]\))?\s+of\s+the\s+Standard\s+Terms", re.I)
    _STD_TERM_RE = re.compile(r"((?:[A-Z][\w-]*\s+){0,4}[A-Z][\w-]*)\s+as\s+defined\s+in\s+the\s+Standard\s+Terms")

    def _cited_std_clauses(self, doc_id: str, std_doc: str, shown: list[ContextClause]) -> set[str]:
        """Standard Terms clauses the shown text cites: by relation target, by section number, or by a defined term."""
        shown_ids = {c.clause_id for c in shown}
        cited = {(r.citation or {}).get("target_clause_id") for r in self.store.list_relations()
                 if r.to_doc == std_doc and r.clause_id in shown_ids}
        index = self._index(std_doc)
        std_clauses = self.store.list_clauses(std_doc)
        spans = _own_spans(std_clauses)
        std_text = index.doc_text
        for c in shown:
            flat = re.sub(r"\s+", " ", c.text)
            for m in self._STD_SECTION_RE.finditer(flat):
                cited.add(index.resolve(m.group(1)))
            for m in self._STD_TERM_RE.finditer(flat):
                term = m.group(1).split()
                for k in range(len(term)):          # the longest trailing run that STD defines
                    name = " ".join(term[k:])
                    holder = next((sc.clause_id for sc in std_clauses
                                   if f'"{name}"' in std_text[spans[sc.clause_id][0]:spans[sc.clause_id][1]][:200]), None)
                    if holder:
                        cited.add(holder)
                        break
        return {c for c in cited if c and c.startswith(f"{std_doc}:")}

    def _parties(self, doc_id: str) -> list[dict[str, str]]:
        """Thor's party fields for the document, else for a document that incorporates it."""
        sources = [doc_id] + sorted({r.from_doc for r in self.store.list_relations(doc_id)
                                     if r.type == "incorporates" and r.to_doc == doc_id})
        for d in sources:
            parties = []
            for e in self.store.current_extractions(d, "thor"):
                v = e.value if isinstance(e.value, dict) else {}
                if e.field_type == "party" and e.status != "missing" and v.get("name"):
                    parties.append({"name": v["name"], "role": v.get("role") or ""})
            if parties:
                return parties
        return []

    def _flag_lines(self, doc_id: str, shown: set[str]) -> list[HintLine]:
        out = []
        for f in self.store.list_flags(status="open"):
            if f.doc_id == doc_id and f.clause_id is None:
                out.append(HintLine(set(), f"[{f.type}] {doc_id}: {_compact(f.description, 200)}"))
            elif f.clause_id in shown:
                out.append(HintLine({f.clause_id}, f"[{f.type}] {f.clause_id}: {_compact(f.description, 200)}"))  # type: ignore[arg-type]
        return out

    def _extraction_lines(self, clauses: list[ContextClause]) -> list[HintLine]:
        """One line per extraction in force for the shown clauses: field: value [clause_id].

        A section's terms include its sub-clauses' extractions, so an extraction is kept only when one of its
        citations lies in shown text (not in a replaced sub-clause).
        """
        shown = {c.clause_id for c in clauses}
        spans: dict[str, list[tuple[int, int]]] = {}
        for c in clauses:
            spans.setdefault(c.doc_id, []).append((c.char_start, c.char_end))

        def in_force(ct: Any) -> bool:
            if ct.char_start is None or ct.char_end is None:
                return ct.clause_id in shown
            return any(s <= ct.char_start and ct.char_end <= e for s, e in spans.get(ct.doc_id, []))

        lines: dict[int, HintLine] = {}
        for c in clauses:
            for e in c.terms:
                if e.id in lines or e.field_type == "party":
                    continue
                cites = [ct for ct in self.store.citations_for(e.id) if ct.clause_id]  # type: ignore[arg-type]
                where = sorted({ct.clause_id for ct in cites if in_force(ct) and ct.clause_id in shown})
                if not where:
                    continue                      # it cites only text that is not in force on as_of
                status = "" if e.status == "extracted" else f" ({e.status})"
                value = _hint_value(e.value) if isinstance(e.value, dict) else _compact(e.value or e.raw_text, 80)
                text = f"{e.field_type}/{e.field_key}{status}: {value}"
                if len(text) > 120:
                    text = text[:117] + "..."
                lines[e.id] = HintLine(set(where), f"{text} [{', '.join(where)}]")  # type: ignore[index]
        return list(lines.values())

    def _company_context(self) -> str:
        res = next(iter(self.store.list_resources("company_context")), None)
        raw = res.text if res and res.text else None
        if raw is None:
            path = self.cfg.paths.bundle_dir / "company" / "context.txt"
            raw = read_text_exact(path) if path.exists() else ""
        lines: list[str] = []
        skipping = False
        raw_lines = raw.split("\n")
        for i, line in enumerate(raw_lines):
            s = line.strip()
            nxt = raw_lines[i + 1] if i + 1 < len(raw_lines) else ""
            if s and DECORATION_RE.match(nxt):           # a section heading (underlined)
                skipping = s.upper().startswith(CONTEXT_SKIP_SECTIONS)
            if skipping or DECORATION_RE.match(line):
                continue
            if s or (lines and lines[-1]):
                lines.append(s)
        text = "\n".join(lines).strip()
        budget = int(self.cfg.loki.context_tokens * self.cfg.loki.chars_per_token)
        if len(text) > budget:
            cut = text.rfind("\n", 0, budget)
            text = text[: cut if cut > 0 else budget].rstrip() + "\n[trimmed]"
        return text

    # ---------------------------------------------------------------- rendering + splitting

    def _tokens(self, text: str) -> int:
        return math.ceil(len(text) / self.cfg.loki.chars_per_token)

    @staticmethod
    def _block(c: ContextClause) -> str:
        head = f"[[{c.clause_id}]]" + (f" ({c.note})" if c.note else "")
        return f"{head}\n{_clean(c.text)}"

    def _doc_header(self, ctx: ReviewContext) -> str:
        d = ctx.doc
        title = ctx.title + (f" (printed title: {d.text_title})" if d.text_title and d.text_title != ctx.title else "")
        parties = "; ".join(f"{p['name']} ({p['role']})" if p["role"] else p["name"] for p in ctx.parties) or "not extracted"
        lines = [f"doc_id: {d.doc_id}", f"document: {title}", f"document ID printed in the text: {d.external_id or 'none'}",
                 f"parties: {parties}", f"you act for the counterparty: {ctx.counterparty or 'not identified'}"]
        return "\n".join(lines)

    def _role_sentence(self, ctx: ReviewContext) -> str:
        roles = {p["role"].lower(): p["name"] for p in ctx.parties if p["role"]}
        if "provider" in roles and "customer" in roles:
            customer = roles["customer"]
            return (f' In them, "Provider" means {roles["provider"]} and "Customer" means {customer}'
                    + ("" if customer.endswith(".") else "."))
        return ""

    def _part_note(self, ctx: ReviewContext, part_clauses: list[ContextClause], index: int, total: int) -> str:
        doc_id = ctx.doc.doc_id
        if total == 1:
            text = f"This is the complete review text for {doc_id}."
            if ctx.std_mode == "incorporated":
                text += (f" It includes the Standard Terms ({ctx.std_doc}) that {doc_id} incorporates by reference "
                         f"({ctx.std_relation_clause}).{self._role_sentence(ctx)}")
            return text
        if part_clauses and all(c.group == "std" for c in part_clauses):
            tops = [c.top_id for c in part_clauses]
            return (f"Part {index} of {total}: Standard Terms ({ctx.std_doc}) {tops[0]} to {tops[-1]}, incorporated into "
                    f"{doc_id} by reference ({ctx.std_relation_clause}), so they bind Quillhub under {doc_id}."
                    f"{self._role_sentence(ctx)} The other parts hold the rest of {doc_id}; findings from all parts are "
                    "merged, so report only what this part's text supports.")
        extra = []
        if any(c.doc_id not in (doc_id, ctx.std_doc) for c in part_clauses):
            extra.append("the amendment text in force")
        if any(c.doc_id == ctx.std_doc for c in part_clauses):
            extra.append(f"the {ctx.std_doc} clauses it cites")
        return (f"Part {index} of {total} (split by top-level section): {doc_id}'s own clauses"
                + (f", with {' and '.join(extra)}" if extra else "")
                + ". The other parts are reviewed separately and findings from all parts are merged.")

    def _values(self, ctx: ReviewContext, part: ReviewPart) -> dict[str, str]:
        by_id = ctx.by_id()
        return {
            "as_of": ctx.as_of,
            "doc_header": self._doc_header(ctx),
            "part_note": part.note,
            "company_context": ctx.company_context or "(none)",
            "flags": "\n".join(part.flags) or "(none)",
            "extractions": "\n".join(part.extractions) or "(none)",
            "document": "\n\n".join(self._block(by_id[cid]) for cid in part.clause_ids),
        }

    def _template(self) -> PromptTemplate:
        tpl = self.prompt("review")
        if not self._scales_checked:
            system = " ".join(tpl.system.split())
            for scale in (FINDING_TYPES, SEVERITY_SCALE, LIKELIHOOD_SCALE):
                for level, meaning in scale.items():
                    if f"- {level}: {meaning}" not in system:
                        raise ValueError(f"prompts/loki_review.md does not state the scale line '- {level}: {meaning}'")
            self._scales_checked = True
        return tpl

    def _estimate(self, ctx: ReviewContext, part: ReviewPart) -> int:
        tpl = self._template()
        return self._tokens(tpl.system) + self._tokens(tpl.render(**self._values(ctx, part)))

    def _make_part(self, ctx: ReviewContext, ids: list[str], index: int, total: int) -> ReviewPart:
        by_id = ctx.by_id()
        members = [by_id[i] for i in ids]
        shown = set(ids)
        flags = [h.text for h in ctx.flags if (h.clause_ids & shown) or (not h.clause_ids and index == 1)]
        exs = [h.text for h in ctx.extractions if h.clause_ids & shown]
        part = ReviewPart(index, total, ids, self._part_note(ctx, members, index, total), flags, exs)
        part.est_tokens = self._estimate(ctx, part)
        return part

    def _input_budget(self) -> int:
        """Estimated input tokens per call: loki.max_input_tokens, and within the model's per-request cap when it
        has one (input + max_tokens <= max_request_tokens, e.g. Groq's free tier)."""
        budget = self.cfg.loki.max_input_tokens
        s = self.llm.settings if self.llm else None
        if s is not None and s.max_request_tokens:
            budget = min(budget, s.max_request_tokens - s.max_output_tokens)
        return budget

    def _halves(self, ctx: ReviewContext, part: ReviewPart) -> list[ReviewPart]:
        """A part in two, at the top-level section boundary nearest its middle (else the clause boundary); [] for
        a single clause."""
        ids = part.clause_ids
        if len(ids) < 2:
            return []
        by_id = ctx.by_id()
        sizes = [len(self._block(by_id[i])) for i in ids]
        unit = [(by_id[i].group, by_id[i].top_id) for i in ids]
        cuts = [k for k in range(1, len(ids)) if unit[k] != unit[k - 1]] or list(range(1, len(ids)))
        cut = min(cuts, key=lambda k: abs(sum(sizes[:k]) - sum(sizes) / 2))
        halves = []
        for suffix, chunk in (("a", ids[:cut]), ("b", ids[cut:])):
            half = self._make_part(ctx, chunk, part.index, part.total)
            half.suffix = suffix
            halves.append(half)
        return halves

    def _plan_parts(self, ctx: ReviewContext) -> list[ReviewPart]:
        """One part if it fits the input budget; otherwise split by top-level section, incorporated STD apart."""
        if not ctx.clauses:
            return []
        budget = self._input_budget()
        whole = self._make_part(ctx, [c.clause_id for c in ctx.clauses], 1, 1)
        if whole.est_tokens <= budget:
            return [whole]
        units: list[tuple[tuple[str, str], list[str]]] = []   # ((group, top-level section), clause ids)
        for c in ctx.clauses:
            key = (c.group, c.top_id)
            if units and units[-1][0] == key:
                units[-1][1].append(c.clause_id)
            else:
                units.append((key, [c.clause_id]))
        groups: list[list[str]] = []
        for group in ("main", "std"):
            current: list[str] = []
            for (g, _top), ids in units:
                if g != group:
                    continue
                trial = current + ids
                # Estimated as a first part of several (it also carries the document-level flags).
                if current and self._make_part(ctx, trial, 1, 2).est_tokens > budget:
                    groups.append(current)
                    current = list(ids)
                else:
                    current = trial
            if current:
                groups.append(current)
        parts = [self._make_part(ctx, ids, i, len(groups)) for i, ids in enumerate(groups, start=1)]
        for p in parts:
            if p.est_tokens > budget:
                ctx.notes.append(f"part {p.label} is about {p.est_tokens} input tokens (over {budget}): "
                                 "a single top-level section is larger than the budget")
        return parts

    # ================================================================== 2. LLM call per part

    def _on_llm_call(self, rec: CallRecord) -> None:
        self._calls.append(rec)
        super()._on_llm_call(rec)

    def _review_part(self, ctx: ReviewContext, part: ReviewPart) -> PartResult:
        """One part's call, with re-prompts. No store access (worker thread when documents run in parallel)."""
        purpose = f"loki.review:{ctx.doc.doc_id}@{ctx.as_of}:part{part.label}"
        result = PartResult(part, purpose)
        tpl = self._template()
        if self.llm is None:
            raise RuntimeError("Loki was constructed without an LLM client")
        t0 = time.monotonic()
        try:
            # The prompt states the output schema itself, so llm.py does not append the JSON Schema (saves input tokens).
            result.output = self.llm.call_json(tpl.render(**self._values(ctx, part)), ReviewOut, system=tpl.system,
                                               purpose=purpose, include_schema=False)
        except BudgetExceeded as exc:
            result.error = f"BudgetExceeded: {exc}"
        except LLMError as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            result.too_large = isinstance(exc, LLMTooLarge)
        result.seconds = time.monotonic() - t0
        # Matched by purpose (re-prompts add "#v1", ...): other documents' calls may be running at the same time.
        result.calls = [r for r in list(self._calls) if r.purpose.split("#", 1)[0] == purpose]
        return result

    # ================================================================== 3. code checks (no LLM)

    def check(self, ctx: ReviewContext, parts: list[PartResult]) -> list[LokiFinding]:
        """Turn the model's findings into stored ones: verify, reject with reasons, merge duplicates, rank, impact."""
        findings = [self._check_one(ctx, raw, p) for p in parts if p.output is not None for raw in p.output.findings]
        findings = self._merge_duplicates(findings)
        findings = self._rank(findings)
        items = self.store.list_exposure_items(ctx.as_of)
        for f in findings:
            f.impact = self._impact(f, items)
        return findings

    def _check_one(self, ctx: ReviewContext, raw: FindingOut, part: PartResult) -> LokiFinding:
        reasons: list[str] = []
        notes: list[str] = []

        ftype = re.sub(r"[\s-]+", "_", raw.type.strip().lower())
        if ftype not in FINDING_TYPES:
            reasons.append(f"type {raw.type!r} is not one of {' | '.join(FINDING_TYPES)}")
        title = " ".join(raw.title.split())
        words = len(title.split())
        if not title:
            reasons.append("no title")
        elif words > MAX_TITLE_WORDS:
            reasons.append(f"title has {words} words (at most {MAX_TITLE_WORDS})")
        severity, likelihood = raw.severity.strip().lower(), raw.likelihood.strip().lower()
        if severity not in SEVERITY_SCALE:
            reasons.append(f"severity {raw.severity!r} is not on the scale")
        if likelihood not in LIKELIHOOD_SCALE:
            reasons.append(f"likelihood {raw.likelihood!r} is not on the scale")
        steps = [" ".join(s.split()) for s in raw.attack_path if s and s.strip()]
        if not MIN_STEPS <= len(steps) <= MAX_STEPS:
            reasons.append(f"attack path has {len(steps)} step(s) (needs {MIN_STEPS} to {MAX_STEPS})")

        cites, dropped = self._verify_citations(ctx, raw.citations)
        notes += [f"dropped citation {d}" for d in dropped]
        if not cites:
            reasons.append("no verified citation" + (f" ({len(dropped)} dropped)" if dropped else ""))

        steps, ref_notes = self._normalise_refs(steps, cites)
        notes += ref_notes
        unknown = [cid for cid in self._clause_ids_in(steps) if not self._exists(cid)]
        if unknown:
            reasons.append(f"attack path names clause id(s) that do not exist: {', '.join(unknown)}")

        if cites:
            invented = self._invented_figures(ctx, title, steps, cites)
            if invented:
                reasons.append(f"title or attack path states figure(s) not in the cited clauses: {', '.join(invented)}")

        readings = [FindingReading(reading=" ".join(r.reading.split()), counterparty_argues=r.counterparty_argues)
                    for r in raw.readings if r.reading.strip()]
        if ftype == "ambiguity":
            if len(readings) < 2:
                reasons.append(f"ambiguity with {len(readings)} reading(s) (needs at least 2)")
            elif sum(r.counterparty_argues for r in readings) != 1:
                notes.append("the counterparty's reading is not marked exactly once")
        elif readings:
            notes.append(f"{len(readings)} reading(s) dropped: readings are for ambiguities only")
            readings = []

        confidence = min(max(float(raw.confidence), 0.0), 1.0)
        if confidence != raw.confidence:
            notes.append(f"confidence {raw.confidence} clamped to {confidence}")
        return LokiFinding(
            doc_id=ctx.doc.doc_id, as_of=ctx.as_of, run_id=self.run_id, model=part.model or (self.llm.model if self.llm else None),
            type=ftype if ftype in FINDING_TYPES else None, title=title, exploited_by=ctx.counterparty,  # type: ignore[arg-type]
            citations=cites, readings=readings, attack_path=steps,
            severity=severity if severity in SEVERITY_SCALE else None,  # type: ignore[arg-type]
            severity_reason=" ".join(raw.severity_reason.split()),
            likelihood=likelihood if likelihood in LIKELIHOOD_SCALE else None,  # type: ignore[arg-type]
            likelihood_reason=" ".join(raw.likelihood_reason.split()), confidence=confidence,
            status="rejected" if reasons else "accepted", rejection_reason="; ".join(reasons) or None,
            part=part.part.label, notes=notes,
        )

    def _index(self, doc_id: str) -> ClauseIndex:
        if doc_id not in self._indexes:
            doc = self.store.get_document(doc_id)
            if doc is None:
                raise LookupError(f"document {doc_id!r} is not in the store")
            self._indexes[doc_id] = ClauseIndex(doc_id, self.store.list_clauses(doc_id), document_text(self.cfg, doc))
        return self._indexes[doc_id]

    def _exists(self, clause_id: str) -> bool:
        if clause_id not in self._clause_exists:
            self._clause_exists[clause_id] = self.store.get_clause(clause_id) is not None
        return self._clause_exists[clause_id]

    def _clause_ids_in(self, steps: list[str]) -> list[str]:
        if self._clause_id_re is None:
            ids = sorted((d.doc_id for d in self.store.list_documents(include_text=False)), key=len, reverse=True)
            self._clause_id_re = re.compile(
                rf"(?<![\w:])(?:{'|'.join(map(re.escape, ids)) or '(?!)'}):[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?")
        found: list[str] = []
        for s in steps:
            found += [m.group(0) for m in self._clause_id_re.finditer(s) if m.group(0) not in found]
        return found

    def _normalise_refs(self, steps: list[str], cites: list[FindingCitation]) -> tuple[list[str], list[str]]:
        """Short clause references in the steps rewritten as full clause ids ("2.2" -> "STD:2.2").

        A reference is looked up in the documents the finding cites and rewritten only when exactly one of them
        has that clause in the store; anything else stays as written (it is then not a clause id to check).
        """
        docs = list(dict.fromkeys(c.doc_id for c in cites if c.doc_id))
        read_as: dict[str, str] = {}
        unclear: dict[str, list[str]] = {}

        def full_id(m: re.Match[str]) -> str:
            ref = m.group("pref") or m.group("bare")
            hits = sorted({cid for d in docs if (cid := self._index(d).resolve(ref)) and self._exists(cid)})
            if len(hits) == 1:
                read_as[m.group(0)] = hits[0]
                return hits[0]
            if hits:
                unclear[m.group(0)] = hits
            return m.group(0)

        out = [SHORT_REF_RE.sub(full_id, s) for s in steps]
        notes = [f"attack path: {ref!r} read as {cid}" for ref, cid in read_as.items()]
        notes += [f"attack path: {ref!r} left as written (matches {' and '.join(ids)})" for ref, ids in unclear.items()]
        return out, notes

    def _verify_citations(self, ctx: ReviewContext, raw: list[CitationOut]) -> tuple[list[FindingCitation], list[str]]:
        """Thor's verifier, limited to the clauses shown (in force on as_of). Unverified citations are dropped."""
        docs = {d.doc_id for d in self.store.list_documents(include_text=False)}
        out: list[FindingCitation] = []
        dropped: list[str] = []
        seen: set[tuple[Any, ...]] = set()
        for rc in raw:
            ref = rc.clause_id.strip().strip("[]")
            prefix = ref.split(":", 1)[0].strip() if ":" in ref else ""
            doc_id = prefix if prefix in docs else ctx.doc.doc_id
            allowed = ctx.ids(doc_id)
            label = ref or "(no clause id)"
            if not allowed:
                dropped.append(f"{label}: not in the review text")
                continue
            index = self._index(doc_id)
            c = verify_citation(index, ref, rc.quote, restrict_to=allowed)
            if not c.verified:
                where = "clause id not in the review text" if index.resolve(ref) not in allowed else "quote not found in the clause"
                dropped.append(f"{label}: {where}: {rc.quote[:80]!r}")
                continue
            if not self._in_force_span(ctx, doc_id, c.char_start, c.char_end):  # type: ignore[arg-type]
                dropped.append(f"{label}: quote is from text that is not in force on {ctx.as_of}")
                continue
            key = (c.clause_id, c.char_start, c.char_end)
            if key in seen:
                continue
            seen.add(key)
            out.append(FindingCitation(
                doc_id=doc_id, clause_id=c.clause_id, clause_ref=c.clause_ref, quote=c.quote, char_start=c.char_start,
                char_end=c.char_end, verified=True, match_method=c.match_method,
                llm_quote=rc.quote if rc.quote != c.quote else None, llm_clause_id=ref if ref != c.clause_id else None,
            ))
        return out, dropped

    @staticmethod
    def _in_force_span(ctx: ReviewContext, doc_id: str, start: int, end: int) -> bool:
        """The quote lies inside the own text of shown clauses: never in a replaced or unshown sub-clause."""
        spans = sorted((c.char_start, c.char_end) for c in ctx.clauses if c.doc_id == doc_id)
        pos = start
        for s, e in spans:
            if s <= pos < e:
                pos = e
                if pos >= end:
                    return True
        return False

    def _invented_figures(self, ctx: ReviewContext, title: str, steps: list[str], cites: list[FindingCitation]) -> list[str]:
        """Amounts, percentages, durations and dates in the title / attack path that the cited clauses do not state."""
        strip = self._clause_id_re.sub(" ", "\n".join([title] + [STEP_NUMBER_RE.sub("", s) for s in steps])) \
            if self._clause_id_re else title
        by_id = ctx.by_id()
        source: list[str] = []
        for cid in {c.clause_id for c in cites if c.clause_id}:
            index = self._index(cid.split(":", 1)[0])
            family = index.descendants(cid)               # a section's sub-clauses ...
            parent = index.by_id[cid].parent_id if cid in index.by_id else None
            while parent:                                 # ... and, for a quote narrowed to a sub-clause, its sections
                family.add(parent)
                parent = index.by_id[parent].parent_id
            source += [by_id[x].text for x in family if x in by_id]
        known = figure_keys("\n".join(source)) | {("date", ctx.as_of), ("month", ctx.as_of[:7])}
        out: list[str] = []
        for key, raw in figures(strip):
            if key not in known and raw not in out:
                out.append(raw)
        return out

    @staticmethod
    def _score(f: LokiFinding) -> tuple[int, int, float]:
        return SEVERITY_RANK.get(f.severity or "", 0), LIKELIHOOD_RANK.get(f.likelihood or "", 0), f.confidence

    def _merge_duplicates(self, findings: list[LokiFinding]) -> list[LokiFinding]:
        """Same type and the same set of cited clauses: one finding, the higher severity kept."""
        kept: dict[tuple[Any, ...], LokiFinding] = {}
        for f in findings:
            if f.status != "accepted":
                continue
            key = (f.type, frozenset(c.clause_id for c in f.citations))
            other = kept.get(key)
            if other is None:
                kept[key] = f
                continue
            winner, loser = (f, other) if self._score(f) > self._score(other) else (other, f)
            have = {(c.clause_id, c.char_start, c.char_end) for c in winner.citations}
            extra = [c for c in loser.citations if (c.clause_id, c.char_start, c.char_end) not in have]
            winner.citations += extra
            winner.notes.append(f"merged duplicate {loser.title!r} (severity {loser.severity})"
                                + (f", adding {len(extra)} citation(s)" if extra else ""))
            loser.status = "rejected"
            loser.rejection_reason = (f"duplicate of {winner.title!r}: same type and cited clauses; "
                                      f"merged into it, keeping the higher severity ({winner.severity})")
            kept[key] = winner
        return findings

    def _rank(self, findings: list[LokiFinding]) -> list[LokiFinding]:
        """Accepted first, most severe first, at most max_findings_per_doc; then the rejected, in reply order."""
        limit = self.cfg.loki.max_findings_per_doc
        order = {id(f): i for i, f in enumerate(findings)}
        accepted = sorted((f for f in findings if f.status == "accepted"),
                          key=lambda f: (tuple(-x for x in self._score(f)), order[id(f)]))
        for n, f in enumerate(accepted[limit:], start=limit + 1):
            f.status = "rejected"
            f.rejection_reason = f"over the limit of {limit} findings per document (ranked {n})"
        final = accepted[:limit] + [f for f in findings if f.status == "rejected"]
        for rank, f in enumerate(final, start=1):
            f.rank = rank
        return final

    @staticmethod
    def _impact(f: LokiFinding, items: list[ExposureItem]) -> FindingImpact | Literal["unquantified"]:
        """A Norns exposure item at the same as_of that cites one of the finding's clauses (copied, never computed)."""
        clause_ids = {c.clause_id for c in f.citations if c.clause_id}
        matches = []
        for it in items:
            hit = next((c.get("clause_id") for c in it.citations if c.get("clause_id") in clause_ids), None)
            if hit:
                matches.append((it, hit))
        if not matches:
            return "unquantified"
        matches.sort(key=lambda m: (m[0].scenario != "worst_case", m[0].amount is None, -(m[0].amount or 0), m[0].id or 0))
        best, clause_id = matches[0]
        return FindingImpact(exposure_item_id=best.id, amount=best.amount, status=best.status, scenario=best.scenario,  # type: ignore[arg-type]
                             category=best.category, clause_id=clause_id,
                             other_exposure_ids=[m[0].id for m in matches[1:] if m[0].id is not None])

    # ================================================================== 4. bookkeeping

    def _finish(self, review: DocReview) -> DocReview:
        self.transition(f"loki:{review.doc_id}@{review.as_of}", None, review.status, review.reason)
        self.update_workstreams(review)
        review.output_path = self.write_output(review)
        return review

    def update_workstreams(self, review: DocReview) -> None:
        """Loki's status for the document, merged into each workstream that has it as a member."""
        workstreams = [w for w in self.store.list_workstreams()
                       if review.doc_id in w.members and w.scope != "cross_contract"]
        if not workstreams:
            workstreams = [Workstream(id=f"ws:{review.doc_id}", scope=review.doc_id, members=[review.doc_id])]
        docs = {d.doc_id: d for d in self.store.list_documents(include_text=False)}
        entry = {"status": review.status, "as_of": review.as_of, "run_id": self.run_id, "reason": review.reason,
                 "accepted": len(review.accepted), "rejected": len(review.rejected)}
        for ws in workstreams:
            try:
                notes = json.loads(ws.notes) if ws.notes else {}
            except ValueError:
                notes = {"text": ws.notes}
            if not isinstance(notes, dict):
                notes = {"text": notes}
            loki_notes = dict(notes.get(AGENT) or {})
            loki_notes[review.doc_id] = entry
            notes[AGENT] = loki_notes
            status = {**ws.agent_status, f"{AGENT}:{review.doc_id}": review.status}
            reviewable = [m for m in ws.members if m in docs and docs[m].kind not in NOT_REVIEWED_KINDS]
            states = {status.get(f"{AGENT}:{m}") for m in reviewable}
            if states == {"complete"}:
                status[AGENT] = "complete"
            elif states & {"partial", "failed"}:
                status[AGENT] = "partial" if states & {"complete", "partial"} else "failed"
            else:
                status[AGENT] = "in_progress"
            self.store.upsert_workstream(Workstream(id=ws.id, scope=ws.scope, members=ws.members,
                                                    agent_status=status, notes=json.dumps(notes)))
        self.log("update_workstreams", review.doc_id, ",".join(w.id for w in workstreams), status=review.status)

    def report(self, review: DocReview) -> dict[str, Any]:
        ctx = review.context
        return {
            "doc_id": review.doc_id, "as_of": review.as_of, "run_id": self.run_id, "status": review.status,
            "reason": review.reason, "stored": review.stored,
            "provider": self.llm.settings.provider if self.llm else None, "model": self.llm.model if self.llm else None,
            "counterparty": ctx.counterparty if ctx else None, "standard_terms": ctx.std_mode if ctx else None,
            "context_notes": ctx.notes if ctx else [],
            "parts": [{"part": p.part.label, "clause_ids": p.part.clause_ids, "est_input_tokens": p.part.est_tokens,
                       "status": "ok" if p.output is not None else "failed", "error": p.error, "model": p.model,
                       "seconds": round(p.seconds, 1), **p.usage()} for p in review.parts],
            "llm": review.usage(),
            "seconds": round(review.seconds, 1), "llm_seconds": round(review.llm_seconds, 1),
            "findings": [f.model_dump(mode="json") for f in review.findings],
        }

    def write_output(self, review: DocReview) -> Path:
        out_dir = self.cfg.paths.outputs_dir / "loki"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{review.doc_id}_{review.as_of}.json"
        path.write_text(json.dumps(self.report(review), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path

    def checkpoint(self, n: int) -> str:
        """Checkpoint n as a date (0 = start date), from the store, else from clock.json."""
        points = self.store.list_checkpoints() or load_clock(self.cfg.paths.pack_dir / "clock.json")
        match = next((p for p in points if p.idx == n), None)
        if match is None:
            raise ValueError(f"checkpoint {n} does not exist (0..{max(p.idx for p in points)}; 0 = start date)")
        return match.date


def as_of_label(value: str) -> str:
    """ISO date check for command-line input."""
    return datetime.strptime(value, "%Y-%m-%d").date().isoformat()

"""Shared state schemas for all Odin agents.

Row models mirror the tables one-to-one (SQLite schema in ``store.py``, Postgres schema in
``supabase/migrations``). Value models describe the
JSON stored in ``extractions.value`` per ``field_type`` so downstream agents (Norns, Loki,
Heimdall, Tyr) and the dashboard can rely on stable keys. Value models are permissive
(every key optional, unknown keys kept) because absent facts must stay absent, not be
invented to satisfy a schema.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --------------------------------------------------------------------------- enums

DocKind = Literal["contract", "standard_terms", "amendment", "addendum"]
DocStatus = Literal["pending", "extracting", "complete", "partial", "failed"]
TextSource = Literal["txt", "pdf_extracted"]
# parsed = clause numbering recognised; fallback = paragraph chunks; unparseable = no text (e.g. scanned PDF)
ParseStatus = Literal["parsed", "fallback", "unparseable"]
FileRole = Literal["text_source", "original", "attachment"]
ExtractionStatus = Literal["extracted", "ambiguous", "missing", "contradictory"]
SourceKind = Literal["sourced", "analysis"]  # sourced = read from a clause (Thor); analysis = derived by a later agent
FlagType = Literal[
    "ambiguous",
    "missing",
    "contradictory",
    "unparseable",
    "cross_reference",
    "unverified_citation",  # a quote that could not be found in its clause
]
FlagStatus = Literal["open", "resolved", "superseded"]
RelationType = Literal["incorporates", "amends", "supersedes", "references", "conflicts"]
MessageType = Literal["clarification_request", "clarification_response", "claim", "verification", "ruling", "alert"]
MessageStatus = Literal["pending", "processing", "done", "failed"]
DayType = Literal["business", "calendar", "unspecified"]
AgentName = Literal["odin", "thor", "norns", "loki", "heimdall", "tyr"]

FieldType = Literal[
    "party",
    "effective_date",
    "term",
    "renewal",
    "payment",
    "obligation",
    "penalty",
    "compliance",
    "termination",
    "governing_law",
    "liability_cap",
    "indemnity",
    "cross_reference",
]
FIELD_TYPES: tuple[str, ...] = FieldType.__args__  # type: ignore[attr-defined]

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- value models


class _Value(BaseModel):
    model_config = ConfigDict(extra="allow")

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("*")
    @classmethod
    def _iso_dates(cls, v: Any, info: Any) -> Any:
        if info.field_name and info.field_name.endswith("iso") and v is not None:
            if not isinstance(v, str) or not ISO_DATE_RE.match(v):
                raise ValueError(f"{info.field_name} must be YYYY-MM-DD or null, got {v!r}")
            datetime.strptime(v, "%Y-%m-%d")
        return v


class PartyValue(_Value):
    name: str | None = None
    role: str | None = None             # as the document labels it: provider, customer, company, contractor
    address: str | None = None
    notice_address: str | None = None
    notice_email: str | None = None
    contact: str | None = None
    entity_type: str | None = None
    jurisdiction: str | None = None


class DateValue(_Value):
    raw: str | None = None
    iso: str | None = None              # only when the text states an absolute date
    rule: str | None = None             # relative/conditional definition, never computed


class TermValue(_Value):
    duration_raw: str | None = None
    duration_months: int | None = None
    start_raw: str | None = None
    start_iso: str | None = None
    end_raw: str | None = None
    end_iso: str | None = None
    rule: str | None = None


class RenewalValue(_Value):
    auto_renew: bool | None = None
    renewal_term_raw: str | None = None
    renewal_term_months: int | None = None
    notice_period_raw: str | None = None
    notice_period_days: int | None = None
    day_type: DayType | None = None
    notice_method: str | None = None
    notice_recipient: str | None = None
    rule: str | None = None


class PaymentValue(_Value):
    item: str | None = None
    amount: float | None = None
    currency: str | None = None
    frequency: str | None = None
    due_rule: str | None = None
    payment_period_days: int | None = None
    day_type: DayType | None = None
    invoice_rule: str | None = None
    late_fee_raw: str | None = None
    interest_rate_raw: str | None = None
    adjustment_raw: str | None = None


class ObligationValue(_Value):
    obligor: str | None = None
    obligee: str | None = None
    action: str | None = None
    trigger: str | None = None
    deadline_raw: str | None = None
    deadline_amount: float | None = None
    deadline_unit: str | None = None    # minutes | hours | days | months | ...
    day_type: DayType | None = None
    recurring: bool | None = None
    condition: str | None = None


class PenaltyValue(_Value):
    kind: str | None = None             # service_credit | interest | fee | refund | liquidated_damages | other
    trigger: str | None = None
    amount_raw: str | None = None
    formula: str | None = None
    cap_raw: str | None = None
    payer: str | None = None
    beneficiary: str | None = None
    claim_window_raw: str | None = None
    claim_window_days: int | None = None
    day_type: DayType | None = None
    # true / false only when the text says so plainly; a qualified rule keeps its words verbatim,
    # e.g. "sole and exclusive remedy … except as otherwise provided in the Agreement".
    sole_remedy: bool | str | None = None


class ComplianceValue(_Value):
    category: str | None = None         # data_protection | security | breach_notification | audit | insurance | subprocessor | data_location | retention | standard | other
    requirement: str | None = None
    obligor: str | None = None
    beneficiary: str | None = None
    standard: str | None = None
    window_raw: str | None = None
    window_amount: float | None = None
    window_unit: str | None = None
    day_type: DayType | None = None


class TerminationValue(_Value):
    kind: str | None = None             # for_cause | for_convenience | persistent_failure | insolvency | force_majeure | non_renewal | other
    who_may_terminate: str | None = None
    trigger: str | None = None
    notice_period_raw: str | None = None
    notice_days: int | None = None
    cure_period_raw: str | None = None
    cure_days: int | None = None
    day_type: DayType | None = None
    consequences: str | None = None


class GoverningLawValue(_Value):
    law: str | None = None
    courts: str | None = None


class LiabilityValue(_Value):
    cap_raw: str | None = None
    cap_formula: str | None = None
    cap_amount: float | None = None
    exclusions: list[str] | None = None
    damages_waiver_raw: str | None = None


class IndemnityValue(_Value):
    indemnitor: str | None = None
    indemnitee: str | None = None
    scope: str | None = None
    conditions: str | None = None


RefType = Literal["incorporates", "amends", "references", "precedence", "notwithstanding"]
# Names used before step 2B; still accepted on input.
LEGACY_REF_TYPES = {"incorporation": "incorporates", "amendment": "amends", "reference": "references"}


class CrossReferenceValue(_Value):
    # incorporates / amends / references become doc_relations edges; precedence and
    # notwithstanding stay extractions (priority rules, not links).
    ref_type: RefType | None = None
    from_doc: str | None = None         # the document that incorporates / amends / refers
    to_doc: str | None = None           # the document incorporated / amended / referred to (bundle doc_id when resolvable)
    target_doc: str | None = None       # same as to_doc; the name the amendment contract uses
    to_doc_resolved: bool | None = None
    target_clause: str | None = None    # clause reference as written in the target, e.g. "Section 3.2"
    operation: Literal["replace", "insert", "delete", "modify"] | None = None
    new_text: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    controlling_doc: str | None = None
    subordinate_doc: str | None = None
    scope: str | None = None
    effective_raw: str | None = None
    effective_iso: str | None = None
    effective_date: str | None = None   # ISO, same as effective_iso

    @field_validator("ref_type", mode="before")
    @classmethod
    def _legacy_ref_type(cls, v: Any) -> Any:
        return LEGACY_REF_TYPES.get(v, v) if isinstance(v, str) else v

    @field_validator("effective_date")
    @classmethod
    def _effective_date_iso(cls, v: Any) -> Any:
        if v is not None and (not isinstance(v, str) or not ISO_DATE_RE.match(v)):
            raise ValueError(f"effective_date must be YYYY-MM-DD or null, got {v!r}")
        return v

    @model_validator(mode="after")
    def _sync_aliases(self) -> "CrossReferenceValue":
        self.to_doc = self.to_doc or self.target_doc
        self.target_doc = self.target_doc or (self.to_doc if self.ref_type == "amends" else None)
        self.effective_date = self.effective_date or self.effective_iso
        self.effective_iso = self.effective_iso or self.effective_date
        return self


FIELD_VALUE_MODELS: dict[str, type[_Value]] = {
    "party": PartyValue,
    "effective_date": DateValue,
    "term": TermValue,
    "renewal": RenewalValue,
    "payment": PaymentValue,
    "obligation": ObligationValue,
    "penalty": PenaltyValue,
    "compliance": ComplianceValue,
    "termination": TerminationValue,
    "governing_law": GoverningLawValue,
    "liability_cap": LiabilityValue,
    "indemnity": IndemnityValue,
    "cross_reference": CrossReferenceValue,
}


def validate_value(field_type: str, value: Any) -> dict[str, Any] | None:
    """Validate an extraction value against its field-type model; returns a clean dict."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"value for {field_type} must be a JSON object or null")
    model = FIELD_VALUE_MODELS[field_type]
    return model.model_validate(value).model_dump(exclude_none=True)


# --------------------------------------------------------------------------- row models


class Document(BaseModel):
    doc_id: str
    title: str                          # manifest title
    text_title: str | None = None       # title banner inside the .txt (can differ from the manifest)
    path: str                           # relative to the bundle dir
    sha256: str
    kind: DocKind
    status: DocStatus = "pending"
    status_reason: str | None = None
    coverage: float | None = None       # % of leaf clauses processed by Thor
    external_id: str | None = None      # "CONTRACT ID" / "DOCUMENT ID" printed in the document
    source: str = "bundle"              # bundle | upload | drop1 | drop2 ...: where the document arrived from
    extracted_sha256: str | None = None # sha256 of the text Thor last finished extracting
    text: str | None = None             # full text; clause offsets index into it. None only for pre-2A rows
    text_source: TextSource | None = None
    parse_status: ParseStatus | None = None
    storage_path: str | None = None     # viewable original in the file store: {doc_id}/{sha256}/{filename}
    original_filename: str | None = None
    mime_type: str | None = None
    uploaded_at: str | None = None
    ingested_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class DocumentFile(BaseModel):
    """Every file stored for a document (the .txt text source, the .pdf original, ...)."""

    id: int | None = None
    doc_id: str
    role: FileRole
    sha256: str
    storage_path: str
    original_filename: str
    mime_type: str
    size_bytes: int
    similarity: float | None = None     # PDF text vs the .txt text source, when both exist
    uploaded_at: str = Field(default_factory=utcnow)


class Clause(BaseModel):
    clause_id: str                      # "A1:4.2", "B1:3.1", "A1:I.1", "D1:ExA.M1", "A1:signatures"
    doc_id: str
    number: str
    ref: str                            # as the contracts cite it: "§3.1", "Section 4.2", "Section C"
    heading: str | None = None
    text: str                           # exactly document_text[char_start:char_end]
    char_start: int
    char_end: int
    level: int = 1
    parent_id: str | None = None
    ordinal: int = 0
    kind: str = "clause"


class Reading(BaseModel):
    interpretation: str
    value: Any = None


class Extraction(BaseModel):
    id: int | None = None
    doc_id: str
    field_type: FieldType
    field_key: str                      # stable key within the doc, e.g. "monthly_fee"; versions share it
    value: Any = None                   # JSON, shape per FIELD_VALUE_MODELS
    readings: list[Reading] = []        # populated when status == "ambiguous"
    raw_text: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    status: ExtractionStatus
    source_kind: SourceKind = "sourced"
    agent: str = "thor"
    version: int = 1
    is_current: bool = True
    supersedes_id: int | None = None
    run_id: str | None = None
    notes: str | None = None
    created_at: str = Field(default_factory=utcnow)


class Citation(BaseModel):
    id: int | None = None
    extraction_id: int | None = None
    doc_id: str
    clause_id: str | None
    clause_ref: str | None = None       # "§3.1" etc., per format_spec "Clause Reference"
    quote: str                          # exact substring of the .txt when verified
    llm_quote: str | None = None        # what the model wrote, if it differs
    llm_clause_id: str | None = None    # what the model cited, if it differs
    char_start: int | None = None
    char_end: int | None = None
    verified: bool = False
    match_method: str = "none"          # exact | normalized | reattributed | none
    source_type: str = "clause"         # clause | event | ledger | context (later agents)


class Flag(BaseModel):
    id: int | None = None
    doc_id: str | None
    clause_id: str | None = None
    type: FlagType
    description: str
    raised_by: str
    extraction_id: int | None = None
    evidence: str | None = None         # verbatim quote supporting the flag
    evidence_verified: bool | None = None
    status: FlagStatus = "open"
    run_id: str | None = None
    created_at: str = Field(default_factory=utcnow)


class DocRelation(BaseModel):
    id: int | None = None
    from_doc: str
    to_doc: str                         # doc_id, or a bundle data path such as "data/holidays.csv"
    type: RelationType
    clause_id: str | None = None        # the citing clause
    citation: dict[str, Any] = {}       # {clause_id, clause_ref, quote, verified, char_start, char_end}
    extraction_id: int | None = None
    raised_by: str = "thor"
    verified: bool = False
    created_at: str = Field(default_factory=utcnow)


class Message(BaseModel):
    id: int | None = None
    from_agent: str
    to_agent: str
    type: MessageType
    payload: dict[str, Any] = {}
    status: MessageStatus = "pending"
    in_reply_to: int | None = None
    workstream_id: str | None = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class Workstream(BaseModel):
    id: str                             # "ws:A1", "ws:cross_contract"
    scope: str                          # a contract doc_id or "cross_contract"
    members: list[str] = []             # documents discovered to belong to this contract family
    agent_status: dict[str, str] = {}   # {"thor": "complete", "loki": "pending", ...}
    notes: str | None = None
    updated_at: str = Field(default_factory=utcnow)


class TraceEntry(BaseModel):
    id: int | None = None
    ts: str = Field(default_factory=utcnow)
    run_id: str | None = None
    agent: str
    action: str
    input_ref: str | None = None
    output_ref: str | None = None
    tokens: int = 0
    duration_ms: int = 0
    error: str | None = None
    meta: dict[str, Any] = {}


# Inputs the later agents consume. Tables exist now so they plug in without schema changes.


class Resource(BaseModel):
    path: str                           # relative to the bundle dir (or pack dir for clock.json)
    kind: str                           # manifest | company_context | ledger | holidays | events | clock
    title: str | None = None
    sha256: str
    storage_path: str | None = None     # copy in the file store (events drops live only there until Heimdall reads them)
    mime_type: str | None = None
    size_bytes: int | None = None
    text: str | None = None             # full text for small text resources (company context)
    loaded_at: str = Field(default_factory=utcnow)


class Event(BaseModel):
    id: int | None = None
    event_id: str | None                # None when the line could not be parsed
    drop: str                           # "drop1" | "drop2"
    line_no: int
    timestamp: str | None = None
    channel: str | None = None
    from_party: str | None = None
    to_party: str | None = None
    subject: str | None = None
    body: str | None = None
    raw: str
    parse_error: str | None = None
    processed_by: dict[str, str] = {}   # {"heimdall": "2027-03-15"} when handled


class LedgerEntry(BaseModel):
    id: int | None = None
    line_no: int
    date: str
    from_party: str
    to_party: str
    amount: float
    reference: str
    status: str
    contract_id: str | None = None      # parsed from the reference, e.g. QH-STRATO-2026-001


class Holiday(BaseModel):
    date: str
    name: str
    observed_by: str


class Checkpoint(BaseModel):
    idx: int                            # 0 = start_date
    date: str
    label: str                          # start | checkpoint


# --------------------------------------------------------------------------- Norns (timeline agent)

RuleKind = Literal["payment", "notice", "renewal", "report", "cure", "penalty_trigger", "credit"]
InstanceStatus = Literal["paid_on_time", "paid_late", "partial", "unpaid", "upcoming", "met", "missed", "triggered"]


class ObligationRule(BaseModel):
    """A dated duty or right derived from Thor's extractions (never read from a contract directly)."""

    rule_id: str                        # "A1:payment:monthly_fee@2026-08-01"
    contract: str                       # root contract of the family ("A1", "B1")
    doc_id: str                         # document whose clause states the term
    kind: RuleKind
    name: str
    payer: str | None = None
    payee: str | None = None
    anchor: str                         # invoice_date | term_end | month_end | due_date | fixed | event:<type>
    anchor_date: str | None = None
    offset_amount: int | None = None
    offset_unit: str | None = None      # days | hours | months
    offset_direction: str | None = None # after | before
    day_type: DayType | None = None
    recurrence: dict[str, Any] | None = None
    amount: Decimal | None = None
    formula: str | None = None
    currency: str | None = None
    escalations: list[dict[str, Any]] = []
    caps: list[dict[str, Any]] = []
    conditions: list[Any] = []          # text conditions, or structured ones (credit tiers by uptime)
    valid_from: str | None = None       # ISO; the version of the term in force from this date
    valid_to: str | None = None         # ISO, exclusive
    citations: list[dict[str, Any]] = []   # {extraction_id, doc_id, clause_id, clause_ref, quote, verified}
    flags: list[str] = []
    source_kind: SourceKind = "analysis"
    built_at: str = Field(default_factory=utcnow)


class ObligationInstance(BaseModel):
    id: int | None = None
    as_of: str
    instance_key: str
    rule_id: str
    contract: str
    kind: str
    name: str
    period: str | None = None
    anchor_date: str | None = None
    due_date: str | None = None
    due_date_calendar: str | None = None
    due_date_business: str | None = None
    day_type: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    payer: str | None = None
    payee: str | None = None
    status: InstanceStatus
    paid_amount: Decimal | None = None
    paid_date: str | None = None
    ledger_lines: list[int] = []
    days_remaining: int | None = None
    severity: str | None = None
    flags: list[str] = []
    citations: list[dict[str, Any]] = []


class ClockState(BaseModel):
    id: int = 1
    current_as_of: str
    updated_at: str = Field(default_factory=utcnow)


class ClockEvent(BaseModel):
    id: int | None = None
    ts: str = Field(default_factory=utcnow)
    action: str
    from_as_of: str | None = None
    to_as_of: str
    note: str | None = None


class TimelineSnapshot(BaseModel):
    id: int | None = None
    as_of: str
    created_at: str = Field(default_factory=utcnow)
    summary: dict[str, Any] = {}
    chart_data: dict[str, Any] = {}


class ExposureItem(BaseModel):
    id: int | None = None
    as_of: str
    scenario: Literal["worst_case", "on_time"]
    contract: str
    category: str
    amount: Decimal | None = None       # None = the contract gives no number (status unquantified)
    status: Literal["quantified", "unquantified"]
    accrues_on: str | None = None
    description: str
    formula: str | None = None
    inputs: dict[str, Any] = {}
    citations: list[dict[str, Any]] = []
    source_kind: SourceKind = "analysis"
    created_at: str = Field(default_factory=utcnow)


class Writeup(BaseModel):
    id: int | None = None
    as_of: str
    label: str                          # "AI-generated analysis" / "Template writeup (...)"
    generated_by: Literal["llm", "template"]
    text: str
    model: str | None = None
    prompt_hash: str | None = None
    check_passed: bool | None = None
    meta: dict[str, Any] = {}
    created_at: str = Field(default_factory=utcnow)

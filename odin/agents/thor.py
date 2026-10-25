"""THOR: extraction agent.

For each document (STD first, once, as its own document):
  1. render the clause-marked text (chunked by top-level section when long)
  2. one LLM extraction call per chunk (prompts/thor_extract.md)
  3. verify every citation in code (odin.citations); unverified -> confidence <= 0.3 + flag
  4. store versioned extractions, citations, flags and doc_relations
  5. mark the document complete / partial / failed with a coverage %

``reextract(doc_id, clause_id, question)`` re-reads one clause only and writes new
versions of the affected extractions; Loki reaches it through the messages table
(``handle_messages``).
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from odin.agents.base import Agent
from odin.citations import ClauseIndex, verify_citation
from odin.ingest.loader import document_text, registry
from odin.ingest.segmenter import DECORATION_RE
from odin.llm import BudgetExceeded, LLMError, LLMTruncated
from odin.state.models import (
    FIELD_TYPES,
    Citation,
    Clause,
    DocRelation,
    Document,
    Extraction,
    ExtractionStatus,
    FieldType,
    Flag,
    Message,
    Reading,
    Workstream,
    validate_value,
)

AGENT = "thor"
CONFIDENCE_CAP_UNVERIFIED = 0.3
# Fields whose absence is worth a flag on a primary contract. Supplementary documents
# (standard terms, SLAs, amendments, addenda) normally inherit these from elsewhere.
CORE_FIELDS = ("party", "effective_date", "term", "payment", "termination", "governing_law")
RELATION_FOR_REF = {"incorporation": "incorporates", "amendment": "amends", "reference": "references"}

# Deterministic pre-scan for wording that signals a cross-document link. It only tells the
# model where to look and checks that it looked; what is amended or incorporated, and how,
# is still read from the text by the model and verified by citation.
CUE_PATTERNS = {
    "amendment": re.compile(
        r"\bamends\b|\b(?:is|are)\s+(?:hereby\s+)?(?:amended|deleted|replaced|inserted)\b"
        r"|\bdeleted in its entirety\b|\bis changed from\b", re.I),
    "precedence": re.compile(
        r"\bconflict\b[^.]{0,160}?\b(?:controls?|prevails?|governs?)\b|\bcontrols?\b[^.]{0,80}?\bconflict\b"
        r"|\bnotwithstanding\b|\btakes?\s+precedence\b", re.I),
    "incorporation": re.compile(
        r"\bincorporat\w*\s+(?:\w+\s+){0,3}?by reference\b|\bincorporated\s+into\s+(?:this|the)\s+(?:Agreement|Cover Page)\b"
        r"|\bforms?\s+part\s+of\b|\bsupplements\s+the\b", re.I),
}
CUE_REF_TYPES = {"amendment": {"amendment"}, "precedence": {"precedence", "notwithstanding"},
                 "incorporation": {"incorporation"}}

# Grammar of incorporation wording, used to check edge direction against the quote.
PASSIVE_INTO_OTHER_RE = re.compile(r"\bincorporated\b[^.]{0,40}?\binto\s+(?:the|an?)\b|\bforms?\s+part\s+of\b|\bsupplements\b")
PASSIVE_INTO_THIS_RE = re.compile(r"\bincorporated\b[^.]{0,40}?\binto\s+this\b")
ACTIVE_INCORPORATES_RE = re.compile(r"\bincorporates\b")
# A target_clause that is a clause reference ("Section 3.2", "§5.1", "Section B"), not a document name.
CLAUSE_REF_RE = re.compile(r"^(?:section|sec\.|clause|§|exhibit)?\s*[A-Z0-9]{1,3}(?:\.[A-Z0-9]{1,3})*$", re.I)


@dataclass(frozen=True)
class Cue:
    clause_id: str
    kind: str
    snippet: str


# --------------------------------------------------------------------------- LLM I/O schemas


class CitationIn(BaseModel):
    clause_id: str = Field(description="Clause marker id exactly as shown, e.g. 'B1:3.1'")
    quote: str = Field(description="Verbatim substring of that clause's text")


class ReadingIn(BaseModel):
    interpretation: str
    value: Any = None


class FieldIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field_type: FieldType
    key: str = Field(description="Stable snake_case id, unique within the document")
    status: ExtractionStatus
    value: Any = None
    readings: list[ReadingIn] = []
    raw_text: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[CitationIn] = []
    notes: str | None = None

    @field_validator("key", mode="before")
    @classmethod
    def _slug_key(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = re.sub(r"[^a-z0-9]+", "_", v.strip().lower()).strip("_")[:80]
        return v

    @model_validator(mode="after")
    def _check(self) -> "FieldIn":
        if not self.key:
            raise ValueError("key must be a non-empty snake_case identifier")
        if self.status == "missing":
            self.value = None
            return self
        if self.value is not None:
            self.value = validate_value(self.field_type, self.value)
        for r in self.readings:
            if isinstance(r.value, dict):
                r.value = validate_value(self.field_type, r.value)
        if not self.citations:
            raise ValueError(f"field {self.key!r} has status {self.status!r} but no citations")
        if self.status == "extracted" and self.value is None:
            raise ValueError(f"field {self.key!r} is 'extracted' but value is null (use 'missing' or 'ambiguous')")
        if self.status == "ambiguous" and len(self.readings) < 2:
            raise ValueError(f"field {self.key!r} is 'ambiguous' but has fewer than 2 readings")
        if self.status == "contradictory" and len(self.citations) < 2:
            raise ValueError(f"field {self.key!r} is 'contradictory' but cites fewer than 2 passages")
        return self


class IssueIn(BaseModel):
    type: Literal["ambiguous", "missing", "contradictory", "cross_reference"]
    clause_id: str | None = None
    quote: str | None = None
    description: str


class ExtractionOut(BaseModel):
    fields: list[FieldIn]
    issues: list[IssueIn] = []


class ReextractFieldIn(FieldIn):
    replaces_extraction_id: int | None = Field(
        default=None, description="id of the current extraction this corrects; null for a new field"
    )


class ReextractOut(BaseModel):
    answer: str = Field(description="Direct answer to the question, grounded in the clause text")
    fields: list[ReextractFieldIn] = []


# --------------------------------------------------------------------------- run bookkeeping


@dataclass
class Chunk:
    doc_id: str
    index: int
    total: int
    top_ids: list[str]
    clause_ids: list[str]
    chars: int


@dataclass
class ChunkResult:
    chunk: Chunk
    output: ExtractionOut | None = None
    error: str | None = None
    budget_exceeded: bool = False
    subchunks: int = 1
    unresolved_cues: list[Cue] = field(default_factory=list)


@dataclass
class DocResult:
    doc_id: str
    status: str
    clauses: int = 0
    fields: int = 0
    ambiguous: int = 0
    missing: int = 0
    contradictory: int = 0
    citations_verified: int = 0
    citations_failed: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    tokens: int = 0
    coverage: float = 0.0
    reason: str | None = None
    skipped: bool = False


@dataclass
class ReextractResult:
    request: dict[str, Any]
    answer: str
    new_ids: list[int] = field(default_factory=list)
    superseded_ids: list[int] = field(default_factory=list)
    unchanged_ids: list[int] = field(default_factory=list)
    unverified: int = 0


def _norm_ref(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


class Thor(Agent):
    name = AGENT
    prompt_files = {"extract": "thor_extract.md", "reextract": "thor_reextract.md", "crossref": "thor_crossref.md"}

    # ================================================================== public API

    def run(self, doc_ids: list[str] | None = None, *, force: bool = False, workers: int = 4) -> list[DocResult]:
        docs = self._ordered_documents(doc_ids)
        self.log("run_start", ",".join(d.doc_id for d in docs), None, force=force, workers=workers,
                 model=self.llm.model if self.llm else None)
        results: dict[str, DocResult] = {}
        todo: list[Document] = []
        for doc in docs:
            if not force and not self.store.needs_extraction(doc.doc_id):
                self.log("skip_unchanged", doc.doc_id, doc.sha256[:12], reason="sha256 unchanged and status complete")
                results[doc.doc_id] = self._summarise(doc.doc_id, skipped=True)
                continue
            todo.append(doc)

        # Plan chunks for every document, run all LLM calls (in parallel), then persist
        # document by document on the main thread.
        plans: dict[str, tuple[Document, str, list[Clause], list[Chunk]]] = {}
        for doc in todo:
            text = document_text(self.cfg, doc)
            clauses = self.store.list_clauses(doc.doc_id)
            chunks = self._plan_chunks(doc.doc_id, clauses)
            plans[doc.doc_id] = (doc, text, clauses, chunks)
            self.transition(f"document:{doc.doc_id}", doc.status, "extracting", f"{len(chunks)} chunk(s)")
            self.store.set_document_status(doc.doc_id, "extracting", f"{len(chunks)} chunk(s) planned")

        reg = registry(self.store)
        jobs = [(plans[d][0], plans[d][1], plans[d][2], ch, reg) for d in plans for ch in plans[d][3]]
        chunk_results: dict[str, list[ChunkResult]] = {d: [] for d in plans}
        if jobs:
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                for res in pool.map(lambda job: self._extract_chunk(*job), jobs):
                    chunk_results[res.chunk.doc_id].append(res)
            self.flush_llm_log()

        budget_hit = False
        for doc_id, (doc, text, clauses, chunks) in plans.items():
            res_list = sorted(chunk_results[doc_id], key=lambda r: r.chunk.index)
            budget_hit = budget_hit or any(r.budget_exceeded for r in res_list)
            self._persist_document(doc, text, clauses, res_list)
            results[doc_id] = self._summarise(doc_id)

        self.update_workstreams()
        self.log("run_end", None, None, budget_exceeded=budget_hit,
                 llm_calls=self.llm.stats.calls if self.llm else 0,
                 tokens=self.llm.stats.tokens if self.llm else 0)
        return [results[d.doc_id] for d in docs if d.doc_id in results]

    def reextract(self, doc_id: str, clause_id: str, question: str, *, request_id: int | None = None) -> ReextractResult:
        """Re-read ONE clause and write new versions of the extractions it affects."""
        clause = self.store.get_clause(clause_id)
        if clause is None or clause.doc_id != doc_id:
            raise ValueError(f"clause {clause_id!r} not found in document {doc_id!r}")
        doc = self.store.get_document(doc_id)
        assert doc is not None
        text = document_text(self.cfg, doc)
        index = ClauseIndex(doc_id, self.store.list_clauses(doc_id), text)
        allowed = index.descendants(clause_id)  # the clause and its own sub-clauses, nothing else
        current = self.store.current_extractions_citing(allowed)
        current_view = [
            {"id": e.id, "field_type": e.field_type, "key": e.field_key, "status": e.status, "value": e.value,
             "raw_text": e.raw_text, "confidence": e.confidence}
            for e in current
        ]
        tpl = self.prompt("reextract")
        purpose = f"thor.reextract:{clause_id}"
        with self.step("reextract", clause_id) as info:
            out = self.call_json(
                tpl, ReextractOut, purpose=purpose,
                doc_header=self._doc_header(doc),
                clause_ref=clause.ref,
                clause_block=self._render(index.clauses, sorted(allowed)),
                question=question,
                current_extractions=json.dumps(current_view, ensure_ascii=False, indent=2),
            )
            current_by_id = {e.id: e for e in current}
            result = ReextractResult(
                request={"doc_id": doc_id, "clause_id": clause_id, "question": question, "message_id": request_id},
                answer=out.answer,
            )
            used_keys = {e.field_key for e in self.store.current_extractions(doc_id)}
            with self.store.transaction():
                for f in out.fields:
                    old = current_by_id.get(f.replaces_extraction_id) if f.replaces_extraction_id else None
                    if old is not None and self._same_as(old, f):
                        result.unchanged_ids.append(old.id)  # type: ignore[arg-type]
                        continue
                    if old is not None:
                        key, version, supersedes = old.field_key, old.version + 1, old.id
                    else:
                        key = self._unique_key(f.key, used_keys)
                        prev = self.store.latest_version(doc_id, AGENT, key)
                        version, supersedes = (prev.version + 1, prev.id) if prev else (1, None)
                    used_keys.add(key)
                    new_id, unverified = self._store_field(
                        doc, index, f, key=key, version=version, supersedes_id=supersedes,
                        restrict_to=allowed, allow_reattribution=True,
                    )
                    if old is not None:
                        self.store.retire_extraction(old.id)  # type: ignore[arg-type]
                        result.superseded_ids.append(old.id)  # type: ignore[arg-type]
                    result.new_ids.append(new_id)
                    result.unverified += unverified
            info.update(output_ref=",".join(map(str, result.new_ids)) or None,
                        superseded=result.superseded_ids, unchanged=result.unchanged_ids, unverified=result.unverified)
        return result

    def handle_messages(self) -> list[int]:
        """Answer pending clarification_request messages addressed to Thor (from Loki)."""
        handled: list[int] = []
        for msg in self.store.pending_messages(AGENT, "clarification_request"):
            assert msg.id is not None
            self.store.set_message_status(msg.id, "processing")
            self.transition(f"message:{msg.id}", "pending", "processing")
            p = msg.payload
            try:
                res = self.reextract(p["doc_id"], p["clause_id"], p["question"], request_id=msg.id)
                payload = {
                    "doc_id": p["doc_id"], "clause_id": p["clause_id"], "answer": res.answer,
                    "new_extraction_ids": res.new_ids, "superseded_extraction_ids": res.superseded_ids,
                    "unchanged_extraction_ids": res.unchanged_ids, "unverified_citations": res.unverified,
                }
                status = "done"
            except (LLMError, BudgetExceeded, ValueError, KeyError) as exc:
                payload = {"error": f"{type(exc).__name__}: {exc}", "request": p}
                status = "failed"
            self.store.post_message(Message(from_agent=AGENT, to_agent=msg.from_agent, type="clarification_response",
                                            payload=payload, in_reply_to=msg.id, workstream_id=msg.workstream_id))
            self.store.set_message_status(msg.id, status)
            self.transition(f"message:{msg.id}", "processing", status)
            handled.append(msg.id)
        return handled

    # ================================================================== planning + rendering

    def _ordered_documents(self, doc_ids: list[str] | None) -> list[Document]:
        docs = self.store.list_documents()
        if doc_ids:
            wanted = set(doc_ids)
            docs = [d for d in docs if d.doc_id in wanted]
        std = self.cfg.thor.std_doc_id
        return sorted(docs, key=lambda d: (d.doc_id != std and d.kind != "standard_terms", d.doc_id))

    def _plan_chunks(self, doc_id: str, clauses: list[Clause]) -> list[Chunk]:
        tops = [c for c in clauses if c.level == 1]
        children: dict[str, list[str]] = {}
        for c in clauses:
            if c.parent_id:
                children.setdefault(c.parent_id, []).append(c.clause_id)
        groups: list[list[Clause]] = []
        size = 0
        for c in tops:
            n = len(c.text)
            if groups and size + n <= self.cfg.thor.chunk_max_chars:
                groups[-1].append(c)
                size += n
            else:
                groups.append([c])
                size = n
        # A tiny tail (e.g. a signature block) rides along with the previous part instead of costing a call.
        if len(groups) > 1:
            tail = sum(len(c.text) for c in groups[-1])
            prev = sum(len(c.text) for c in groups[-2])
            if tail < self.cfg.thor.min_split_chars and prev + tail <= self.cfg.thor.chunk_max_chars * 1.1:
                groups[-2].extend(groups.pop())
        chunks = []
        for i, g in enumerate(groups, start=1):
            ids = []
            for c in g:
                ids.append(c.clause_id)
                ids.extend(children.get(c.clause_id, []))
            chunks.append(Chunk(doc_id, i, len(groups), [c.clause_id for c in g], ids, sum(len(c.text) for c in g)))
        return chunks

    @staticmethod
    def _clean(text: str) -> str:
        """Drop decorative separator lines; everything else stays verbatim."""
        return "\n".join(line for line in text.split("\n") if not DECORATION_RE.match(line)).strip()

    @staticmethod
    def _own_texts(clauses: list[Clause], ids: list[str]) -> list[tuple[Clause, str]]:
        """Each selected clause with only its own text (a section's text stops at its first sub-clause)."""
        wanted = set(ids)
        selected = sorted((c for c in clauses if c.clause_id in wanted), key=lambda c: (c.char_start, c.level))
        out = []
        for k, c in enumerate(selected):
            nxt = selected[k + 1].char_start if k + 1 < len(selected) else None
            own_end = nxt if nxt is not None and nxt < c.char_end else c.char_end
            out.append((c, c.text[: own_end - c.char_start]))
        return out

    def _render(self, clauses: list[Clause], ids: list[str]) -> str:
        """Linear document text with a [[clause_id]] marker at the start of every clause."""
        return "\n\n".join(f"[[{c.clause_id}]]\n{self._clean(own)}" for c, own in self._own_texts(clauses, ids))

    def _scan_cues(self, clauses: list[Clause], ids: list[str]) -> list[Cue]:
        cues = []
        for c, own in self._own_texts(clauses, ids):
            flat = re.sub(r"\s+", " ", own)
            for kind, pattern in CUE_PATTERNS.items():
                m = pattern.search(flat)
                if m:
                    cues.append(Cue(c.clause_id, kind, m.group(0)[:80]))
        return cues

    @staticmethod
    def _cues_text(cues: list[Cue]) -> str:
        if not cues:
            return "Pre-scan found no amendment, precedence or incorporation wording in this text."
        by_clause: dict[str, list[str]] = {}
        for cue in cues:
            by_clause.setdefault(cue.clause_id, []).append(f'{cue.kind} ("{cue.snippet}")')
        lines = [f"- {cid}: " + "; ".join(kinds) for cid, kinds in by_clause.items()]
        return ("A deterministic pre-scan found wording that usually signals a cross-document link in these "
                "clauses. Cover each one with cross_reference rows of the matching ref_type (one row per link or "
                "amendment operation), or add an issue for the clause if it is not actually such a link:\n"
                + "\n".join(lines))

    @staticmethod
    def _unresolved_cues(index: ClauseIndex, cues: list[Cue], out: ExtractionOut,
                         excusing_issues: list[IssueIn] | None = None) -> list[Cue]:
        """Cues not covered by a cross_reference row of their kind citing that clause.

        Only ``excusing_issues`` (the follow-up's answers to "explain if this is not a link")
        can excuse a cue; an unrelated issue raised on the same clause does not.
        """

        def related(cid: str) -> set[str]:
            rel = index.descendants(cid)
            parent = index.by_id[cid].parent_id if cid in index.by_id else None
            while parent:
                rel.add(parent)
                parent = index.by_id[parent].parent_id if parent in index.by_id else None
            return rel

        def where(clause_ref: str | None, quote: str | None) -> str | None:
            if quote:
                v = verify_citation(index, clause_ref, quote)
                if v.verified:
                    return v.clause_id
            return index.resolve(clause_ref)

        cited: dict[str, set[str]] = {}
        for f in out.fields:
            if f.field_type == "cross_reference" and isinstance(f.value, dict):
                for c in f.citations:
                    cid = where(c.clause_id, c.quote)
                    if cid:
                        cited.setdefault(cid, set()).add(f.value.get("ref_type") or "")
        explained = {where(i.clause_id, i.quote) for i in (excusing_issues or [])}
        missing = []
        for cue in cues:
            rel = related(cue.clause_id)
            types = set().union(*(cited.get(x, set()) for x in rel))
            if not (types & CUE_REF_TYPES[cue.kind] or rel & explained):
                missing.append(cue)
        return missing

    def _followup_cues(self, doc: Document, clauses: list[Clause], reg: list[dict[str, Any]], missing: list[Cue],
                       purpose: str) -> ExtractionOut:
        """One small call over only the uncovered clauses, asking only for the missing links.

        Re-sending the whole conversation would double the tokens and can exceed low per-minute
        provider limits; this call carries just those clauses.
        """
        ids = sorted({c.clause_id for c in missing})
        lines = [f'- {c.clause_id}: {c.kind} wording ("{c.snippet}"); expected ref_type '
                 f'{" or ".join(sorted(CUE_REF_TYPES[c.kind]))}' for c in missing]
        return self.call_json(
            self.prompt("crossref"), ExtractionOut, purpose=f"{purpose}:crossref",
            system=self.prompt("extract").system,
            doc_header=self._doc_header(doc),
            registry=self._registry_text(reg, doc.doc_id),
            gaps="\n".join(lines),
            document=self._render(clauses, ids),
        )

    @staticmethod
    def _doc_header(doc: Document) -> str:
        bits = [f"doc_id: {doc.doc_id}", f"kind: {doc.kind}", f"title in text: {doc.text_title or '(none)'}"]
        if doc.external_id:
            bits.append(f"document's own ID: {doc.external_id}")
        return "\n".join(bits)

    @staticmethod
    def _registry_text(reg: list[dict[str, Any]], doc_id: str) -> str:
        lines = []
        for r in reg:
            if r["doc_id"] == doc_id:
                continue
            lines.append(
                f"- doc_id {r['doc_id']} | file {r['file']} | kind {r['kind']} | own ID: {r['external_id'] or 'none'}"
                f" | title in text: {r['title_in_text'] or 'none'}"
            )
        lines.append("- bundle data files: data/holidays.csv, data/payments_ledger.csv, company/context.txt")
        return "\n".join(lines)

    # ================================================================== extraction (worker threads: no DB writes)

    def _extract_chunk(self, doc: Document, text: str, clauses: list[Clause], chunk: Chunk,
                       reg: list[dict[str, Any]]) -> ChunkResult:
        tpl = self.prompt("extract")
        purpose = f"thor.extract:{doc.doc_id}:part{chunk.index}/{chunk.total}"
        part_note = (
            "This is the complete document."
            if chunk.total == 1
            else f"This is part {chunk.index} of {chunk.total} of the document (split by top-level section). "
                 "Extract only from this part; field types absent from this part get status 'missing' "
                 "(the system merges parts)."
        )
        cues = self._scan_cues(clauses, chunk.clause_ids)
        try:
            out = self.call_json(
                tpl, ExtractionOut, purpose=purpose,
                doc_header=self._doc_header(doc),
                registry=self._registry_text(reg, doc.doc_id),
                part_note=part_note,
                cues=self._cues_text(cues),
                document=self._render(clauses, chunk.clause_ids),
            )
            index = ClauseIndex(doc.doc_id, clauses, text)
            missing = self._unresolved_cues(index, cues, out)
            budget_hit = False
            if missing:
                # A failed follow-up never discards the valid main answer: leftovers become flags.
                try:
                    extra = self._followup_cues(doc, clauses, reg, missing, purpose)
                    out.fields += [f for f in extra.fields if f.field_type == "cross_reference" and f.status != "missing"]
                    out.issues += extra.issues
                    missing = self._unresolved_cues(index, cues, out, excusing_issues=extra.issues)
                except BudgetExceeded:
                    budget_hit = True
                except LLMError:
                    pass
            return ChunkResult(chunk, out, budget_exceeded=budget_hit, unresolved_cues=missing)
        except LLMTruncated as exc:
            # Too much output for one call: split the chunk's top-level sections in two.
            if len(chunk.top_ids) > 1 and chunk.chars > self.cfg.thor.min_split_chars:
                half = len(chunk.top_ids) // 2
                merged = ExtractionOut(fields=[], issues=[])
                leftover: list[Cue] = []
                n = 0
                for part_tops in (chunk.top_ids[:half], chunk.top_ids[half:]):
                    ids = [c.clause_id for c in clauses
                           if c.clause_id in part_tops or (c.parent_id in part_tops)]
                    sub = Chunk(doc.doc_id, chunk.index, chunk.total, part_tops, ids,
                                sum(len(c.text) for c in clauses if c.clause_id in part_tops))
                    r = self._extract_chunk(doc, text, clauses, sub, reg)
                    if r.output is None:
                        return ChunkResult(chunk, None, r.error, r.budget_exceeded, n + r.subchunks)
                    merged.fields += r.output.fields
                    merged.issues += r.output.issues
                    leftover += r.unresolved_cues
                    n += r.subchunks
                return ChunkResult(chunk, merged, subchunks=n, unresolved_cues=leftover)
            return ChunkResult(chunk, None, f"LLMTruncated: {exc}")
        except BudgetExceeded as exc:
            return ChunkResult(chunk, None, f"BudgetExceeded: {exc}", budget_exceeded=True)
        except LLMError as exc:
            return ChunkResult(chunk, None, f"{type(exc).__name__}: {exc}")

    # ================================================================== persistence (main thread)

    def _persist_document(self, doc: Document, text: str, clauses: list[Clause], results: list[ChunkResult]) -> None:
        index = ClauseIndex(doc.doc_id, clauses, text)
        ok = [r for r in results if r.output is not None]
        failed = [r for r in results if r.output is None]
        fields = self._merge_fields([f for r in ok for f in r.output.fields])  # type: ignore[union-attr]
        issues = [i for r in ok for i in r.output.issues]  # type: ignore[union-attr]

        with self.step("persist_extractions", doc.doc_id) as info, self.store.transaction():
            retired = self.store.retire_current(doc.doc_id, AGENT)
            self.store.supersede_flags(doc.doc_id, AGENT)
            self.store.delete_relations(doc.doc_id, AGENT)
            used: set[str] = set()
            unverified_total = 0
            if ok:
                for f in fields:
                    key = self._unique_key(f.key, used)
                    used.add(key)
                    prev = self.store.latest_version(doc.doc_id, AGENT, key)
                    version, supersedes = (prev.version + 1, prev.id) if prev else (1, None)
                    _, unverified = self._store_field(doc, index, f, key=key, version=version, supersedes_id=supersedes)
                    unverified_total += unverified
                present = {f.field_type for f in fields if f.status != "missing"}
                if doc.kind == "contract":
                    for ft in CORE_FIELDS:
                        if ft not in present:
                            self.store.add_flag(Flag(doc_id=doc.doc_id, type="missing", raised_by=AGENT, run_id=self.run_id,
                                                     description=f"No {ft.replace('_', ' ')} found in this contract"))
                for issue in issues:
                    self._store_issue(doc, index, issue)
                for cue in (c for r in ok for c in r.unresolved_cues):
                    self.store.add_flag(Flag(
                        doc_id=doc.doc_id, clause_id=cue.clause_id, type="cross_reference", raised_by=AGENT,
                        run_id=self.run_id,
                        description=f'{cue.kind} wording ("{cue.snippet}") but no {cue.kind} cross-reference was '
                                    f"extracted from this clause, even after a re-check",
                    ))
            info.update(output_ref=f"{len(fields)} fields", retired_previous=retired, unverified_citations=unverified_total)

        # Status + coverage
        leaves = self._leaf_ids(clauses)
        done_tops = {t for r in ok for t in r.chunk.top_ids}
        parent_of = {c.clause_id: c.parent_id for c in clauses}
        covered = [lid for lid in leaves if (parent_of.get(lid) or lid) in done_tops]
        coverage = round(100.0 * len(covered) / len(leaves), 1) if leaves else 0.0
        if not failed and coverage == 100.0:
            status, reason = "complete", None
        elif ok:
            status = "partial"
            reason = "; ".join(f"part {r.chunk.index}/{r.chunk.total} failed: {r.error}" for r in failed)
        else:
            status = "failed"
            reason = "; ".join(f"part {r.chunk.index}/{r.chunk.total}: {r.error}" for r in failed) or "no output"
        self.store.set_document_status(
            doc.doc_id, status, reason, coverage, extracted_sha256=doc.sha256 if status == "complete" else None
        )
        self.transition(f"document:{doc.doc_id}", "extracting", status, reason)
        self.log("document_status", doc.doc_id, status, coverage=coverage, reason=reason,
                 chunks=len(results), failed_chunks=len(failed))

    @staticmethod
    def _leaf_ids(clauses: list[Clause]) -> list[str]:
        parents = {c.parent_id for c in clauses if c.parent_id}
        return [c.clause_id for c in clauses if c.clause_id not in parents]

    @staticmethod
    def _merge_fields(fields: list[FieldIn]) -> list[FieldIn]:
        """Combine chunk outputs: a type is 'missing' only if no part found it."""
        found = {f.field_type for f in fields if f.status != "missing"}
        out: list[FieldIn] = []
        missing_seen: set[str] = set()
        for f in fields:
            if f.status == "missing":
                if f.field_type in found or f.field_type in missing_seen:
                    continue
                missing_seen.add(f.field_type)
            out.append(f)
        for ft in FIELD_TYPES:
            if ft not in found and ft not in missing_seen:
                out.append(FieldIn(field_type=ft, key=f"{ft}_missing", status="missing", confidence=0.5,  # type: ignore[arg-type]
                                   notes="The model returned nothing for this field type; recorded as missing by Thor."))
        return out

    @staticmethod
    def _unique_key(key: str, used: set[str]) -> str:
        if key not in used:
            return key
        n = 2
        while f"{key}_{n}" in used:
            n += 1
        return f"{key}_{n}"

    @staticmethod
    def _same_as(old: Extraction, f: FieldIn) -> bool:
        return old.status == f.status and old.value == f.value and old.raw_text == f.raw_text

    def _store_field(
        self,
        doc: Document,
        index: ClauseIndex,
        f: FieldIn,
        *,
        key: str,
        version: int,
        supersedes_id: int | None,
        restrict_to: set[str] | None = None,
        allow_reattribution: bool = True,
    ) -> tuple[int, int]:
        """Verify citations, cap confidence, store the extraction + flags + relations."""
        cites: list[Citation] = []
        seen: set[tuple[Any, ...]] = set()
        for c in f.citations:
            v = verify_citation(index, c.clause_id, c.quote, allow_reattribution=allow_reattribution, restrict_to=restrict_to)
            sig = (v.clause_id, v.char_start, v.char_end, v.quote if not v.verified else None)
            if sig in seen:
                continue
            seen.add(sig)
            cites.append(v)
        unverified = [c for c in cites if not c.verified]
        confidence = f.confidence
        if f.status != "missing" and (unverified or not cites):
            confidence = min(confidence, CONFIDENCE_CAP_UNVERIFIED)

        ex = Extraction(
            doc_id=doc.doc_id, field_type=f.field_type, field_key=key, value=f.value,
            readings=[Reading(interpretation=r.interpretation, value=r.value) for r in f.readings],
            raw_text=f.raw_text, confidence=confidence, status=f.status, source_kind="sourced", agent=AGENT,
            version=version, supersedes_id=supersedes_id, run_id=self.run_id, notes=f.notes,
        )
        ex_id = self.store.add_extraction(ex, cites)
        first_ok = next((c for c in cites if c.verified), None)
        anchor = first_ok.clause_id if first_ok else (cites[0].clause_id if cites else None)

        for c in unverified:
            self.store.add_flag(Flag(
                doc_id=doc.doc_id, clause_id=c.clause_id, type="unverified_citation", raised_by=AGENT,
                extraction_id=ex_id, evidence=c.quote, evidence_verified=False, run_id=self.run_id,
                description=f"{f.field_type}/{key}: quote not found in {c.llm_clause_id or 'the cited clause'}; "
                            f"confidence capped at {CONFIDENCE_CAP_UNVERIFIED}",
            ))
        if f.status == "ambiguous":
            readings = " | ".join(f"({i + 1}) {r.interpretation}" for i, r in enumerate(f.readings))
            self.store.add_flag(Flag(doc_id=doc.doc_id, clause_id=anchor, type="ambiguous", raised_by=AGENT,
                                     extraction_id=ex_id, run_id=self.run_id, evidence=first_ok.quote if first_ok else None,
                                     evidence_verified=bool(first_ok),
                                     description=f"{f.field_type}/{key}: two readings: {readings}"))
        if f.status == "contradictory":
            where = ", ".join(sorted({c.clause_id or "?" for c in cites}))
            self.store.add_flag(Flag(doc_id=doc.doc_id, clause_id=anchor, type="contradictory", raised_by=AGENT,
                                     extraction_id=ex_id, run_id=self.run_id, evidence=first_ok.quote if first_ok else None,
                                     evidence_verified=bool(first_ok),
                                     description=f"{f.field_type}/{key}: clauses disagree ({where}). {f.notes or ''}".strip()))
        if f.field_type == "cross_reference" and isinstance(f.value, dict):
            self._store_relation(doc, index, f, ex_id, first_ok or (cites[0] if cites else None))
        return ex_id, len(unverified)

    # ---------------------------------------------------------------- cross references

    def _resolve_doc(self, raw: str | None) -> str | None:
        if not raw:
            return None
        r = raw.strip()
        docs = self.store.list_documents()
        by_id = {d.doc_id: d.doc_id for d in docs}
        if r in by_id:
            return r
        low = r.lower()
        for d in docs:
            names = {d.doc_id.lower(), d.path.lower(), d.path.split("/")[-1].lower()}
            if d.external_id:
                names.add(d.external_id.lower())
            if low in names or low.removesuffix(".txt") == d.doc_id.lower():
                return d.doc_id
        # An ID or file name embedded in a longer description.
        for d in docs:
            if d.external_id and re.search(rf"\b{re.escape(d.external_id)}\b", r, re.I):
                return d.doc_id
            if re.search(rf"\b{re.escape(d.doc_id)}\.txt\b", r, re.I):
                return d.doc_id
        for res in ("data/holidays.csv", "data/payments_ledger.csv", "company/context.txt"):
            if res in low or res.split("/")[-1] == low:
                return res
        return None

    def _aliases(self, target: str) -> list[str]:
        """How a document can be identified in another document's text: file name, printed ID,
        or (for a document without an ID) the name its own title gives it, e.g. "Standard Terms"."""
        doc = self.store.get_document(target)
        if doc is None:  # a bundle data file such as data/holidays.csv
            return [target, target.split("/")[-1]]
        aliases = [doc.path.split("/")[-1]]
        if doc.external_id:
            aliases.append(doc.external_id)
        elif doc.text_title and "—" in doc.text_title:
            tail = doc.text_title.split("—")[-1].strip()
            if len(tail.split()) >= 2:
                aliases.append(tail)
        return aliases

    def _identified(self, target: str, citing: Document, text: str) -> bool:
        if target == citing.doc_id:
            return True
        flat = re.sub(r"\s+", " ", text).lower()
        return any(re.sub(r"\s+", " ", a).lower() in flat for a in self._aliases(target))

    def _checked_target_clause(self, to_doc: str, target_raw: str | None, index: ClauseIndex,
                               cite: Citation | None) -> Clause | None:
        if not target_raw or not CLAUSE_REF_RE.match(target_raw.strip()) or cite is None or not cite.verified:
            return None
        if self.store.get_document(to_doc) is None:
            return None
        target_clauses = self.store.list_clauses(to_doc)
        target_id = ClauseIndex(to_doc, target_clauses, "").resolve(target_raw)
        if target_id is None:
            return None
        target = next(c for c in target_clauses if c.clause_id == target_id)
        citing = index.by_id.get(cite.clause_id or "")
        citing_text = re.sub(r"\s+", " ", citing.text if citing else cite.quote)
        named = re.search(rf"(?:section|§)\s*{re.escape(target.number)}\b", citing_text, re.I)
        return target if named else None

    def _store_relation(self, doc: Document, index: ClauseIndex, f: FieldIn, ex_id: int, cite: Citation | None) -> None:
        v: dict[str, Any] = f.value  # type: ignore[assignment]
        rel_type = RELATION_FOR_REF.get(v.get("ref_type") or "")
        if rel_type is None:
            return  # precedence / notwithstanding stay as extractions only
        from_doc = self._resolve_doc(v.get("from_doc")) or doc.doc_id
        to_raw = v.get("to_doc")
        to_doc = self._resolve_doc(to_raw)

        def flag(description: str) -> None:
            self.store.add_flag(Flag(
                doc_id=doc.doc_id, clause_id=cite.clause_id if cite else None, type="cross_reference", raised_by=AGENT,
                extraction_id=ex_id, evidence=cite.quote if cite else None,
                evidence_verified=cite.verified if cite else None, run_id=self.run_id, description=description,
            ))

        if to_doc is None:
            flag(f"{v.get('ref_type')} reference to {to_raw!r} does not match any document in the bundle")
            return
        if to_doc == from_doc:
            return  # internal reference (e.g. to an exhibit of the same document)
        # Never assume a link: both ends must be identified in this document's own text.
        unidentified = [d for d in (from_doc, to_doc) if not self._identified(d, doc, index.doc_text)]
        if unidentified:
            flag(f"{v.get('ref_type')} link {from_doc} -> {to_doc} not recorded: {', '.join(unidentified)} is never "
                 f"identified in {doc.doc_id} by file name, printed ID or own name (model wrote to_doc={to_raw!r})")
            return
        # Both ends stay as stated: a document may describe a link between two others
        # (A3's preamble states that the SLA is incorporated into the cover page). Only the
        # direction of the citing document's own incorporation is checked against the
        # grammar of the verified quote ("this Addendum is incorporated into the Agreement").
        direction_corrected = False
        if rel_type == "incorporates" and cite is not None and cite.verified:
            q = re.sub(r"\s+", " ", cite.quote).lower()
            passive_other = PASSIVE_INTO_OTHER_RE.search(q) and not PASSIVE_INTO_THIS_RE.search(q)
            active_self = ACTIVE_INCORPORATES_RE.search(q)
            if (passive_other and from_doc == doc.doc_id and to_doc != doc.doc_id) or (
                active_self and to_doc == doc.doc_id and from_doc != doc.doc_id
            ):
                from_doc, to_doc = to_doc, from_doc
                direction_corrected = True
        # A target clause is kept only if it exists in the target document ("Section J" is not
        # in STD) and the citing clause itself names it (B2 §5.1 never says "Section 5.1").
        target_raw = v.get("target_clause")
        target = self._checked_target_clause(to_doc, target_raw, index, cite)
        if target_raw and target is None and CLAUSE_REF_RE.match(target_raw.strip()):
            flag(f"{v.get('ref_type')} {from_doc} -> {to_doc}: target clause {target_raw!r} is not a clause of {to_doc} "
                 f"named in the citing clause; link kept at document level")
        citation = {}
        if cite is not None:
            citation = {"clause_id": cite.clause_id, "clause_ref": cite.clause_ref, "quote": cite.quote,
                        "verified": cite.verified, "char_start": cite.char_start, "char_end": cite.char_end,
                        "target_clause": target.ref if target else None,
                        "target_clause_id": target.clause_id if target else None, "target_clause_raw": target_raw,
                        "operation": v.get("operation"), "direction_corrected": direction_corrected}
        self.store.add_relation(DocRelation(
            from_doc=from_doc, to_doc=to_doc, type=rel_type, clause_id=cite.clause_id if cite else f"{doc.doc_id}:?",  # type: ignore[arg-type]
            citation=citation, extraction_id=ex_id, raised_by=AGENT, verified=bool(cite and cite.verified),
        ))

    def _store_issue(self, doc: Document, index: ClauseIndex, issue: IssueIn) -> None:
        cite = verify_citation(index, issue.clause_id, issue.quote) if issue.quote else None
        clause_id = cite.clause_id if cite else index.resolve(issue.clause_id)
        self.store.add_flag(Flag(
            doc_id=doc.doc_id, clause_id=clause_id, type=issue.type, raised_by=AGENT, run_id=self.run_id,
            description=issue.description, evidence=cite.quote if cite else None,
            evidence_verified=cite.verified if cite else None,
        ))

    # ================================================================== workstreams + reports

    def update_workstreams(self) -> None:
        """One workstream per contract family (discovered from relations) plus cross_contract."""
        docs = {d.doc_id: d for d in self.store.list_documents()}
        adj: dict[str, set[str]] = {d: set() for d in docs}
        for rel in self.store.list_relations():
            if rel.type in ("incorporates", "amends") and rel.from_doc in docs and rel.to_doc in docs:
                adj[rel.from_doc].add(rel.to_doc)
                adj[rel.to_doc].add(rel.from_doc)
        claimed: set[str] = set()

        def family(root: str) -> list[str]:
            seen, stack = {root}, [root]
            while stack:
                for nxt in adj[stack.pop()]:
                    # Stop at other contracts and at shared standard terms (members, not bridges).
                    if nxt in seen or docs[nxt].kind == "contract":
                        continue
                    seen.add(nxt)
                    if docs[nxt].kind != "standard_terms":
                        stack.append(nxt)
            return sorted(seen, key=lambda x: (x != root, x))

        def status_of(members: list[str]) -> str:
            states = {docs[m].status for m in members}
            if states == {"complete"}:
                return "complete"
            if "failed" in states and len(states) == 1:
                return "failed"
            if states & {"partial", "failed"}:
                return "partial"
            if "complete" in states:
                return "in_progress"   # some members done, others not run yet
            return "pending"

        roots = [d for d in docs.values() if d.kind == "contract"]
        for root in sorted(roots, key=lambda d: d.doc_id):
            members = family(root.doc_id)
            claimed.update(members)
            self.store.upsert_workstream(Workstream(
                id=f"ws:{root.doc_id}", scope=root.doc_id, members=members,
                agent_status={AGENT: status_of(members)},
                notes=json.dumps({m: docs[m].status for m in members}),
            ))
        for d in sorted(docs.values(), key=lambda d: d.doc_id):
            if d.doc_id not in claimed and d.kind != "standard_terms":
                self.store.upsert_workstream(Workstream(
                    id=f"ws:{d.doc_id}", scope=d.doc_id, members=[d.doc_id], agent_status={AGENT: status_of([d.doc_id])},
                    notes=json.dumps({"orphan": True, d.doc_id: d.status}),
                ))
        all_ids = sorted(docs)
        self.store.upsert_workstream(Workstream(
            id="ws:cross_contract", scope="cross_contract", members=all_ids,
            agent_status={AGENT: status_of(all_ids)} if all_ids else {},
            notes=json.dumps({d: docs[d].status for d in all_ids}),
        ))
        self.log("update_workstreams", None, f"{len(roots)} families")

    def _summarise(self, doc_id: str, skipped: bool = False) -> DocResult:
        doc = self.store.get_document(doc_id)
        assert doc is not None
        exs = self.store.current_extractions(doc_id, AGENT)
        cites = [c for e in exs for c in self.store.citations_for(e.id)]  # type: ignore[arg-type]
        calls = hits = tokens = 0
        for t in self.store.trace(agent=AGENT):
            if t.action == "llm_call" and t.input_ref and t.input_ref.startswith(f"thor.extract:{doc_id}:"):
                if t.run_id != self.run_id:
                    continue
                if t.meta.get("cache_hit"):
                    hits += 1
                elif not t.error:
                    calls += 1
                    tokens += t.tokens
                else:
                    calls += 1
        return DocResult(
            doc_id=doc_id, status=doc.status, clauses=len(self.store.list_clauses(doc_id)),
            fields=sum(1 for e in exs if e.status != "missing"),
            ambiguous=sum(1 for e in exs if e.status == "ambiguous"),
            missing=sum(1 for e in exs if e.status == "missing"),
            contradictory=sum(1 for e in exs if e.status == "contradictory"),
            citations_verified=sum(1 for c in cites if c.verified),
            citations_failed=sum(1 for c in cites if not c.verified),
            llm_calls=calls, cache_hits=hits, tokens=tokens, coverage=doc.coverage or 0.0,
            reason=doc.status_reason, skipped=skipped,
        )

    def document_report(self, doc_id: str) -> dict[str, Any]:
        """Everything Thor knows about one document (written to outputs/thor/<doc_id>.json)."""
        doc = self.store.get_document(doc_id)
        assert doc is not None
        exs = self.store.current_extractions(doc_id, AGENT)
        return {
            "document": doc.model_dump(),
            "clauses": [c.model_dump(exclude={"text"}) for c in self.store.list_clauses(doc_id)],
            "extractions": [
                {**e.model_dump(), "citations": [c.model_dump() for c in self.store.citations_for(e.id)]}  # type: ignore[arg-type]
                for e in exs
            ],
            "flags": [f.model_dump() for f in self.store.list_flags(doc_id)],
            "relations": [r.model_dump() for r in self.store.list_relations(doc_id)],
        }

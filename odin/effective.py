"""Which version of a clause is in force on a date, following Thor's `amends` relations.

    effective_clause(doc_id, clause_id, as_of) -> EffectiveClause

Before an amendment's effective date the original clause (and the extractions citing it)
is in force; from that date on, the amended version (the amendment's new text and the
extractions citing the amending clause). Several amendments of one clause apply in
date order. An amendment whose effective date is not stated as a date is not applied;
the result says so in ``notes``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from odin.state.models import DocRelation, Extraction
from odin.state.store import StateStore


@dataclass
class ClauseVersion:
    text: str
    source: str                          # original | amended | deleted
    effective_from: str | None           # ISO date; None = from the start of the document
    effective_to: str | None             # ISO date, exclusive; None = open-ended
    terms: list[Extraction] = field(default_factory=list)
    amended_by: dict[str, Any] | None = None   # relation id, amending doc/clause, operation, old/new value


@dataclass
class EffectiveClause:
    doc_id: str
    clause_id: str
    as_of: str
    text: str
    source: str
    terms: list[Extraction]
    version: ClauseVersion
    versions: list[ClauseVersion]
    notes: list[str] = field(default_factory=list)


def _iso(d: date | str) -> str:
    return d.isoformat() if isinstance(d, date) else date.fromisoformat(str(d)[:10]).isoformat()


def _terms(store: StateStore, clause_ids: set[str]) -> list[Extraction]:
    return [e for e in store.current_extractions_citing(clause_ids) if e.field_type != "cross_reference"]


def _descendants(store: StateStore, doc_id: str, clause_id: str) -> set[str]:
    clauses = store.list_clauses(doc_id)
    out, changed = {clause_id}, True
    while changed:
        changed = False
        for c in clauses:
            if c.parent_id in out and c.clause_id not in out:
                out.add(c.clause_id)
                changed = True
    return out


def amendments_of(store: StateStore, doc_id: str, clause_id: str) -> list[DocRelation]:
    """`amends` edges whose target is this clause or one of its ancestors, oldest first."""
    clause = store.get_clause(clause_id)
    targets, p = {clause_id}, clause.parent_id if clause else None
    while p:
        targets.add(p)
        parent = store.get_clause(p)
        p = parent.parent_id if parent else None
    rels = [r for r in store.list_relations(doc_id)
            if r.type == "amends" and r.to_doc == doc_id and (r.citation or {}).get("target_clause_id") in targets]
    return sorted(rels, key=lambda r: ((r.citation or {}).get("effective_date") or "9999-12-31", r.id or 0))


def clause_versions(store: StateStore, doc_id: str, clause_id: str) -> tuple[list[ClauseVersion], list[str]]:
    clause = store.get_clause(clause_id)
    if clause is None or clause.doc_id != doc_id:
        raise LookupError(f"no clause {clause_id!r} in document {doc_id!r}")
    notes: list[str] = []
    versions = [ClauseVersion(text=clause.text, source="original", effective_from=None, effective_to=None,
                              terms=_terms(store, _descendants(store, doc_id, clause_id)))]
    for rel in amendments_of(store, doc_id, clause_id):
        cite = rel.citation or {}
        start = cite.get("effective_date")
        if not start:
            notes.append(f"{rel.from_doc} amends {clause_id} (via {rel.clause_id}) but states no effective date "
                         f"({cite.get('effective_raw')!r}); not applied")
            continue
        op = cite.get("operation") or "replace"
        amending = store.get_clause(rel.clause_id) if rel.clause_id else None
        if op == "delete":
            text, source = "", "deleted"
        else:
            text = cite.get("new_text") or (amending.text if amending else "")
            source = "amended"
        versions[-1].effective_to = start
        versions.append(ClauseVersion(
            text=text, source=source, effective_from=start, effective_to=None,
            terms=_terms(store, {rel.clause_id}) if rel.clause_id else [],
            amended_by={"relation_id": rel.id, "doc_id": rel.from_doc, "clause_id": rel.clause_id, "operation": op,
                        "old_value": cite.get("old_value"), "new_value": cite.get("new_value"),
                        "target_clause_id": cite.get("target_clause_id"), "quote": cite.get("quote")},
        ))
    return versions, notes


def effective_clause(doc_id: str, clause_id: str, as_of: date | str, *, store: StateStore | None = None) -> EffectiveClause:
    """The clause text and terms in force on ``as_of``."""
    if store is None:
        from odin.runtime import get_runtime

        store = get_runtime().store
    day = _iso(as_of)
    versions, notes = clause_versions(store, doc_id, clause_id)
    current = versions[0]
    for v in versions:
        if (v.effective_from is None or v.effective_from <= day) and (v.effective_to is None or day < v.effective_to):
            current = v
    return EffectiveClause(doc_id=doc_id, clause_id=clause_id, as_of=day, text=current.text, source=current.source,
                           terms=current.terms, version=current, versions=versions, notes=notes)

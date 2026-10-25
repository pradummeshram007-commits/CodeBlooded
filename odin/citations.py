"""Citation verification, done in code (never by the LLM).

A quote is verified when it is found inside the text of the clause it cites, comparing
after normalising whitespace, quote characters, dashes and case. The stored quote is
then replaced by the exact substring of the .txt at the matched offsets, so it stays
findable by plain text search (format_spec "Verbatim Quote").

If the quote is not in the cited clause but occurs exactly once elsewhere in the same
document, the citation is re-attributed to the clause that really contains it (the
model's clause id is kept in ``llm_clause_id``). Anything else is unverified.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from odin.state.models import Citation, Clause

MIN_QUOTE_CHARS = 8

# Quotation marks (single, double, curly, guillemets, backticks) are ignored when matching:
# models routinely swap " for ' to avoid JSON escaping, or drop the marks around a defined
# term. Words, numbers and the rest of the punctuation must still match.
_CHAR_MAP = str.maketrans(
    {
        "“": None, "”": None, "„": None, "‟": None, "″": None, "«": None,
        "»": None, '"': None, "'": None, "‘": None, "’": None, "‚": None, "‛": None,
        "′": None, "`": None,
        "—": "-", "–": "-", "‑": "-", "‒": "-", "−": "-",
        " ": " ", " ": " ", " ": " ",
    }
)
_EDGE_PUNCT = ".,;:"


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Normalised text plus, for every normalised char, its index in the original."""
    out: list[str] = []
    idx: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        ch = ch.translate(_CHAR_MAP)
        if not ch:
            continue  # ignored character (quotation mark): leaves the whitespace state untouched
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                idx.append(i)
            prev_space = True
            continue
        for c in ch.casefold():
            out.append(c)
            idx.append(i)
        prev_space = False
    if out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def normalize(text: str) -> str:
    return normalize_with_map(text)[0]


@dataclass
class QuoteMatch:
    found: bool
    start: int | None = None
    end: int | None = None
    method: str = "none"          # exact | normalized | none
    reason: str | None = None


def _quote_variants(quote: str) -> list[str]:
    q = quote.strip()
    variants = [q]
    # Models sometimes wrap the whole quote in quotation marks...
    if len(q) >= 2 and q[0] in "\"'“‘" and q[-1] in "\"'”’":
        variants.append(q[1:-1].strip())
    # ...or end a mid-sentence excerpt with a period the text does not have there.
    for v in list(variants):
        trimmed = v.strip(_EDGE_PUNCT + " ")
        if trimmed and trimmed != v:
            variants.append(trimmed)
    seen: set[str] = set()
    return [v for v in variants if v and not (v in seen or seen.add(v))]


def _balance_quotes(text: str, start: int, end: int) -> tuple[int, int]:
    """Quote marks are ignored when matching, so a span can stop right inside `"Term"`: take the mark too."""
    if sum(text[start:end].count(m) for m in '"“”') % 2:
        if end < len(text) and text[end] in '"”':
            end += 1
        elif start > 0 and text[start - 1] in '"“':
            start -= 1
    return start, end


def find_quote(quote: str, text: str) -> QuoteMatch:
    """Locate ``quote`` inside ``text``; offsets are relative to ``text``."""
    if not quote or not quote.strip():
        return QuoteMatch(False, reason="empty quote")
    for q in _quote_variants(quote):
        i = text.find(q)
        if i >= 0 and len(normalize(q)) >= MIN_QUOTE_CHARS:
            return QuoteMatch(True, i, i + len(q), "exact")
    norm_text, mapping = normalize_with_map(text)
    for q in _quote_variants(quote):
        nq = normalize(q)
        if len(nq) < MIN_QUOTE_CHARS:
            return QuoteMatch(False, reason=f"quote shorter than {MIN_QUOTE_CHARS} characters")
        j = norm_text.find(nq)
        if j >= 0:
            start, end = _balance_quotes(text, mapping[j], mapping[j + len(nq) - 1] + 1)
            return QuoteMatch(True, start, end, "normalized")
    return QuoteMatch(False, reason="quote not found")


def find_all(quote: str, text: str) -> list[tuple[int, int]]:
    """Every (start, end) occurrence of the normalised quote in ``text``."""
    norm_text, mapping = normalize_with_map(text)
    hits: list[tuple[int, int]] = []
    for q in _quote_variants(quote):
        nq = normalize(q)
        if len(nq) < MIN_QUOTE_CHARS:
            continue
        for m in re.finditer(re.escape(nq), norm_text):
            hits.append(_balance_quotes(text, mapping[m.start()], mapping[m.end() - 1] + 1))
        if hits:
            break
    return hits


class ClauseIndex:
    """Resolves the clause identifiers a model writes ("§3.1", "Section C", "3.1") to clause ids."""

    def __init__(self, doc_id: str, clauses: Sequence[Clause], doc_text: str):
        self.doc_id = doc_id
        self.doc_text = doc_text
        self.clauses = sorted(clauses, key=lambda c: c.ordinal)
        self.by_id = {c.clause_id: c for c in self.clauses}
        self._lookup: dict[str, str] = {}
        for c in self.clauses:
            for key in (c.clause_id, c.number, c.ref, f"{doc_id} {c.ref}", f"{doc_id} {c.number}"):
                self._lookup.setdefault(self._key(key), c.clause_id)
            if c.heading:
                self._lookup.setdefault(self._key(c.heading), c.clause_id)

    @staticmethod
    def _key(s: str) -> str:
        s = s.strip().lower().replace("§", "§")
        s = re.sub(r"^(section|sec\.|clause)\s+", "", s)
        s = s.replace("§", "").strip()
        return re.sub(r"\s+", " ", s)

    def resolve(self, raw: str | None) -> str | None:
        if not raw:
            return None
        raw = raw.strip().strip("[]")
        if raw in self.by_id:
            return raw
        if ":" in raw:
            prefix, rest = raw.split(":", 1)
            if prefix.strip() != self.doc_id:
                return None  # a clause of another document: not verifiable here
            raw = rest
        return self._lookup.get(self._key(raw))

    def deepest_containing(self, start: int, end: int, within: Iterable[str] | None = None) -> Clause | None:
        allowed = set(within) if within is not None else None
        best: Clause | None = None
        for c in self.clauses:
            if allowed is not None and c.clause_id not in allowed:
                continue
            if c.char_start <= start and end <= c.char_end:
                if best is None or (c.char_end - c.char_start) < (best.char_end - best.char_start):
                    best = c
        return best

    def descendants(self, clause_id: str) -> set[str]:
        out = {clause_id}
        changed = True
        while changed:
            changed = False
            for c in self.clauses:
                if c.parent_id in out and c.clause_id not in out:
                    out.add(c.clause_id)
                    changed = True
        return out


def verify_citation(
    index: ClauseIndex,
    clause_ref: str | None,
    quote: str,
    *,
    allow_reattribution: bool = True,
    restrict_to: Iterable[str] | None = None,
) -> Citation:
    """Verify one model citation and return a Citation row (not yet linked to an extraction).

    ``restrict_to`` limits which clauses may hold the quote (re-extraction of a single clause).
    """
    allowed = set(restrict_to) if restrict_to is not None else None
    cited_id = index.resolve(clause_ref)
    if allowed is not None and cited_id not in allowed:
        cited_id = None
    base = dict(doc_id=index.doc_id, llm_quote=quote, llm_clause_id=clause_ref)

    if cited_id is not None:
        clause = index.by_id[cited_id]
        m = find_quote(quote, clause.text)
        if m.found:
            start, end = clause.char_start + m.start, clause.char_start + m.end  # type: ignore[operator]
            # Prefer the most specific sub-clause that contains the quote.
            precise = index.deepest_containing(start, end, within=index.descendants(cited_id)) or clause
            return Citation(
                **base,
                clause_id=precise.clause_id,
                clause_ref=precise.ref,
                quote=index.doc_text[start:end],
                char_start=start,
                char_end=end,
                verified=True,
                match_method=m.method,
            )

    if allow_reattribution:
        hits = find_all(quote, index.doc_text)
        if len(hits) == 1:
            start, end = hits[0]
            holder = index.deepest_containing(start, end, within=allowed)
            if holder is not None:
                return Citation(
                    **base,
                    clause_id=holder.clause_id,
                    clause_ref=holder.ref,
                    quote=index.doc_text[start:end],
                    char_start=start,
                    char_end=end,
                    verified=True,
                    match_method="reattributed",
                )

    fallback = index.by_id.get(cited_id) if cited_id else None
    return Citation(
        **base,
        clause_id=cited_id,
        clause_ref=fallback.ref if fallback else None,
        quote=quote,
        verified=False,
        match_method="none",
    )

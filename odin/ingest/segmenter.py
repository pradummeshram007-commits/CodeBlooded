"""Deterministic clause segmentation (no LLM).

Each contract keeps its own numbering scheme (see docs/DATA_NOTES.md). The segmenter
recognises them line by line and records exact character offsets, so that for every
clause ``text == document_text[char_start:char_end]``.

Two levels:
  level 1  top-level blocks: preamble, "SECTION 4 — ...", "Section C — ...",
           "EXHIBIT A — ...", ALL-CAPS headings (PROVIDER INFORMATION, SIGNATURES,
           USING THIS AGREEMENT), "LABEL: value" blocks, NOTE blocks, closing text
  level 2  numbered clauses inside them: "4.2", "§3.1", "I.1", Exhibit "M1", "Label:"

A level-1 block's span covers its children, so a quote can be verified against either
the section or the precise sub-clause. If nothing recognisable is found, the document
falls back to paragraph chunks and the result is marked unparseable. Never raises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DASH = "[—–-]"  # em dash, en dash, hyphen

DECORATION_RE = re.compile(r"^\s*(?:={5,}|-{5,})\s*$")
HARD_SEPARATOR_RE = re.compile(r"^\s*={5,}\s*$")
DASH_UNDERLINE_RE = re.compile(r"^\s*-{3,}\s*$")

SECTION_UPPER_RE = re.compile(rf"^SECTION\s+(\d{{1,2}})\s+{DASH}\s+(.+?)\s*$")
SECTION_TITLE_RE = re.compile(rf"^Section\s+([A-Z]{{1,2}}|\d{{1,2}})\s+{DASH}\s+(.+?)\s*$")
EXHIBIT_RE = re.compile(rf"^EXHIBIT\s+([A-Z])\s+{DASH}\s+(.+?)\s*$")
CAPS_HEADING_RE = re.compile(r"^([A-Z][A-Z &'/]{2,58}[A-Z])\s*$")
CAPS_LABEL_RE = re.compile(r"^([A-Z][A-Z &'/]{2,58}[A-Z]):\s+(\S.*?)\s*$")
NOTE_RE = re.compile(r"^\[?NOTE:")
END_BANNER_RE = re.compile(r"^\s*END OF\b")
BANNER_RE = re.compile(r"^\s*(?:END OF\b|[A-Z][A-Z0-9 .,&'/()—–-]*$)")

NUM_CLAUSE_RE = re.compile(r"^(\d{1,2}\.\d{1,2})\s+(?=\S)")              # "4.2  Invoicing."  (column 0)
SECT_CLAUSE_RE = re.compile(r"^(\s{0,8})§\s?(\d{1,2}\.\d{1,2})\s+(?=\S)")  # "  §3.1  Uptime ..."
LETTER_CLAUSE_RE = re.compile(r"^(\s{0,8})([A-Z]\.\d{1,2})\s+(?=\S)")      # "I.1  ..." / "  H.1  ..."
MILESTONE_RE = re.compile(rf"^(\s{{1,8}})(M\d{{1,2}})\s+{DASH}\s+(.+?)\s*$")  # "  M1 — Project Kickoff"
LABEL_BLOCK_RE = re.compile(r"^([A-Z][A-Za-z ]{2,40}):\s*$")              # "Acceptance Criteria:"

HEADING_SMALL_WORDS = {"and", "or", "of", "for", "to", "the", "in", "on", "by", "with", "a", "an", "from"}


@dataclass
class ClauseSeg:
    clause_id: str
    doc_id: str
    number: str
    ref: str                 # clause reference as the contracts write it: "§3.1", "Section 4.2"
    heading: str | None
    text: str
    char_start: int
    char_end: int
    level: int
    parent_id: str | None
    ordinal: int
    kind: str                # preamble | section | exhibit | clause | block | note | closing | paragraph


@dataclass
class Segmentation:
    doc_id: str
    clauses: list[ClauseSeg]
    method: str                       # "numbered" | "paragraph"
    warnings: list[str] = field(default_factory=list)

    @property
    def unparseable(self) -> bool:
        return self.method != "numbered"

    def leaves(self) -> list[ClauseSeg]:
        parents = {c.parent_id for c in self.clauses if c.parent_id}
        return [c for c in self.clauses if c.clause_id not in parents]

    def by_id(self) -> dict[str, ClauseSeg]:
        return {c.clause_id: c for c in self.clauses}


@dataclass
class _Open:
    level: int
    number: str
    ref: str
    heading: str | None
    kind: str
    start: int               # char offset where the clause text begins
    parent: "_Open | None" = None
    end: int | None = None
    skip: bool = False       # banners: decoration, not stored


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _title(text: str) -> str:
    words = text.lower().split()
    return " ".join(w if (i and w in HEADING_SMALL_WORDS) else w.capitalize() for i, w in enumerate(words))


def _inline_heading(rest: str) -> str | None:
    """Heading text after a clause number: '"Affiliate" means' -> '"Affiliate"', 'Access and Use. During' -> 'Access and Use'."""
    m = re.match(r'^("[^"]{1,60}")\s+means\b', rest)
    if m:
        return m.group(1)
    m = re.match(r"^([A-Z][^.]{0,70}?)\.(?:\s|$)", rest)
    if not m:
        return None
    candidate = m.group(1).strip()
    words = candidate.split()
    if not words or len(words) > 8:
        return None
    for w in words:
        bare = w.strip("()&,'\"-")
        if not bare:
            continue
        if not (bare[0].isupper() or bare[0].isdigit() or bare.lower() in HEADING_SMALL_WORDS):
            return None
    return candidate


def _line_table(text: str) -> list[tuple[int, str]]:
    """(start offset, line content without newline) for every line."""
    out: list[tuple[int, str]] = []
    pos = 0
    for raw in text.splitlines(keepends=True):
        out.append((pos, raw.rstrip("\r\n")))
        pos += len(raw)
    return out


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Drop leading/trailing whitespace and decoration lines from [start, end)."""
    while True:
        while start < end and text[start].isspace():
            start += 1
        line_end = text.find("\n", start, end)
        line_end = end if line_end == -1 else line_end
        if start < end and DECORATION_RE.match(text[start:line_end]):
            start = line_end
            continue
        break
    while True:
        while end > start and text[end - 1].isspace():
            end -= 1
        line_start = text.rfind("\n", start, end) + 1
        line_start = max(line_start, start)
        if end > start and DECORATION_RE.match(text[line_start:end]):
            end = line_start
            continue
        break
    return start, end


def _next_nonblank(lines: list[tuple[int, str]], i: int) -> str | None:
    for _, s in lines[i + 1:]:
        if s.strip():
            return s
    return None


def _prev_nonblank(lines: list[tuple[int, str]], i: int) -> str | None:
    for _, s in reversed(lines[:i]):
        if s.strip():
            return s
    return None


def _segment_numbered(doc_id: str, text: str) -> Segmentation:
    lines = _line_table(text)
    opened: list[_Open] = []
    cur1: _Open | None = _Open(1, "preamble", "Preamble", None, "preamble", 0)
    opened.append(cur1)
    cur2: _Open | None = None
    seen_heading = False
    closing_count = 0

    def close2(at: int) -> None:
        nonlocal cur2
        if cur2 is not None and cur2.end is None:
            cur2.end = at
        cur2 = None

    def close1(at: int) -> None:
        nonlocal cur1
        close2(at)
        if cur1 is not None and cur1.end is None:
            cur1.end = at
        cur1 = None

    def open1(node: _Open) -> None:
        nonlocal cur1, seen_heading
        close1(node.start)
        opened.append(node)
        cur1 = node
        seen_heading = True

    def open2(node: _Open) -> None:
        nonlocal cur2
        close2(node.start)
        node.parent = cur1
        opened.append(node)
        cur2 = node

    for i, (off, s) in enumerate(lines):
        if HARD_SEPARATOR_RE.match(s):
            # Before the first heading, separators only frame the title banner.
            if seen_heading:
                close1(off)
            continue
        if not s.strip():
            continue
        if END_BANNER_RE.match(s):
            open1(_Open(1, "banner", "Banner", None, "banner", off, skip=True))
            continue

        m = SECTION_UPPER_RE.match(s) or SECTION_TITLE_RE.match(s)
        if m:
            open1(_Open(1, m.group(1), f"Section {m.group(1)}", m.group(2), "section", off))
            continue
        m = EXHIBIT_RE.match(s)
        if m:
            open1(_Open(1, f"Ex{m.group(1)}", f"Exhibit {m.group(1)}", m.group(2), "exhibit", off))
            continue
        if NOTE_RE.match(s):
            open1(_Open(1, "note", "Note", None, "note", off))
            continue
        m = CAPS_LABEL_RE.match(s)
        if m and (cur1 is None or cur1.kind == "preamble"):
            label = m.group(1)
            open1(_Open(1, _slug(label), _title(label), label, "block", off))
            continue
        m = CAPS_HEADING_RE.match(s)
        if m:
            nxt, prv = _next_nonblank(lines, i), _prev_nonblank(lines, i)
            underlined = nxt is not None and DASH_UNDERLINE_RE.match(nxt) is not None
            after_separator = prv is not None and DECORATION_RE.match(prv) is not None
            if underlined or after_separator:
                label = m.group(1)
                open1(_Open(1, _slug(label), _title(label), label, "block", off))
                continue

        if cur1 is not None and cur1.kind != "preamble":
            m = NUM_CLAUSE_RE.match(s)
            if m:
                rest = s[m.end():]
                open2(_Open(2, m.group(1), f"Section {m.group(1)}", _inline_heading(rest), "clause", off))
                continue
            m = SECT_CLAUSE_RE.match(s)
            if m:
                rest = s[m.end():]
                open2(_Open(2, m.group(2), f"§{m.group(2)}", _inline_heading(rest), "clause", off + len(m.group(1))))
                continue
            m = LETTER_CLAUSE_RE.match(s)
            if m:
                rest = s[m.end():]
                open2(_Open(2, m.group(2), f"Section {m.group(2)}", _inline_heading(rest), "clause", off + len(m.group(1))))
                continue
            if cur1.kind == "exhibit":
                m = MILESTONE_RE.match(s)
                if m:
                    num = f"{cur1.number}.{m.group(2)}"
                    open2(_Open(2, num, f"{cur1.ref}, {m.group(2)}", m.group(3), "clause", off + len(m.group(1))))
                    continue
                m = LABEL_BLOCK_RE.match(s)
                if m:
                    label = m.group(1)
                    open2(_Open(2, f"{cur1.number}.{_slug(label)}", f"{cur1.ref}, {label}", label, "clause", off))
                    continue

        if cur1 is None:
            # Free text after a separator: a closing paragraph, or a decorative banner.
            is_banner = BANNER_RE.match(s) is not None and s.strip() == s.strip().upper()
            if is_banner:
                open1(_Open(1, "banner", "Banner", None, "banner", off, skip=True))
            else:
                closing_count += 1
                num = "closing" if closing_count == 1 else f"closing-{closing_count}"
                open1(_Open(1, num, "Closing Text", None, "closing", off))
            continue
        # otherwise: continuation line of the current clause

    close1(len(text))

    clauses: list[ClauseSeg] = []
    used: dict[str, int] = {}
    id_of: dict[int, str] = {}
    warnings: list[str] = []
    ordinal = 0
    for node in opened:
        if node.skip:
            continue
        start, end = _trim_span(text, node.start, node.end if node.end is not None else len(text))
        if end <= start:
            continue
        if node.level == 2 and LABEL_BLOCK_RE.match(text[start:end]):
            continue  # a bare "Milestones:" label whose items are their own clauses
        number = node.number
        if number in used:
            used[number] += 1
            new_number = f"{number}-{used[number]}"
            warnings.append(f"duplicate clause number {number!r}; stored as {new_number!r}")
            number = new_number
        else:
            used[number] = 1
        clause_id = f"{doc_id}:{number}"
        id_of[id(node)] = clause_id
        parent_id = id_of.get(id(node.parent)) if node.parent is not None else None
        ordinal += 1
        clauses.append(
            ClauseSeg(
                clause_id=clause_id,
                doc_id=doc_id,
                number=number,
                ref=node.ref,
                heading=node.heading,
                text=text[start:end],
                char_start=start,
                char_end=end,
                level=node.level,
                parent_id=parent_id,
                ordinal=ordinal,
                kind=node.kind,
            )
        )

    headed = [c for c in clauses if c.kind not in ("preamble", "closing")]
    if not headed:
        raise ValueError("no recognisable headings or numbered clauses")

    uncovered = _uncovered_text(text, clauses)
    if uncovered:
        warnings.append(f"{len(uncovered)} non-decoration characters fall outside every clause")
    return Segmentation(doc_id, clauses, "numbered", warnings)


def _uncovered_text(text: str, clauses: list[ClauseSeg]) -> str:
    """Substantive characters not inside any top-level clause (banners and separators excluded)."""
    covered = bytearray(len(text))
    for c in clauses:
        if c.level == 1:
            covered[c.char_start:c.char_end] = b"\x01" * (c.char_end - c.char_start)
    out = []
    for off, s in _line_table(text):
        if not s.strip() or DECORATION_RE.match(s):
            continue
        stripped = s.strip()
        if BANNER_RE.match(s) and stripped == stripped.upper():
            continue
        for k, ch in enumerate(s):
            if not ch.isspace() and not covered[off + k]:
                out.append(ch)
    return "".join(out)


def _segment_paragraphs(doc_id: str, text: str, reason: str) -> Segmentation:
    clauses: list[ClauseSeg] = []
    for n, m in enumerate(re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\s*\Z)", text, flags=re.S), start=1):
        start, end = _trim_span(text, m.start(), m.end())
        if end <= start:
            continue
        clauses.append(
            ClauseSeg(
                clause_id=f"{doc_id}:p{n}",
                doc_id=doc_id,
                number=f"p{n}",
                ref=f"Paragraph {n}",
                heading=None,
                text=text[start:end],
                char_start=start,
                char_end=end,
                level=1,
                parent_id=None,
                ordinal=n,
                kind="paragraph",
            )
        )
    return Segmentation(doc_id, clauses, "paragraph", [f"fell back to paragraph chunks: {reason}"])


def segment(doc_id: str, text: str) -> Segmentation:
    """Split a document into clauses. Falls back to paragraphs; never raises."""
    try:
        return _segment_numbered(doc_id, text)
    except Exception as exc:  # noqa: BLE001 - segmentation must never crash ingestion
        try:
            return _segment_paragraphs(doc_id, text, f"{type(exc).__name__}: {exc}")
        except Exception as exc2:  # noqa: BLE001
            whole = ClauseSeg(f"{doc_id}:p1", doc_id, "p1", "Paragraph 1", None, text, 0, len(text), 1, None, 1, "paragraph")
            return Segmentation(doc_id, [whole] if text else [], "paragraph", [f"paragraph fallback failed: {exc2}"])

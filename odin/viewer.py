"""Contract viewer data: everything the "See the contract" page shows, from the shared state.

    get_contract_view(doc_id, clause_id=None, quote=None) -> ContractView

* metadata of the document (status, parse status, text source, original file)
* a signed URL for the original (private bucket, expires after 1 hour)
* the full text split into clauses; each clause carries Thor's current fields that cite
  it, with confidence and verified badges
* an optional target: ``clause_id`` (+ ``quote``) for deep links. The quote is located
  inside that clause with the same normalisation the citation verifier uses, so a link
  built from any stored citation lands on the highlighted text.

Deep link format (``contract_link``): ``/Contracts?doc=A1&clause=A1:4.2&quote=...``.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from odin.citations import ClauseIndex, find_all, find_quote
from odin.config import OdinConfig
from odin.ingest.loader import document_text
from odin.state.errors import StoreError
from odin.state.files import FileStore
from odin.state.models import Citation, Clause, Extraction
from odin.state.store import StateStore

CONTRACTS_PAGE = "/Contracts"


def contract_link(doc_id: str, clause_id: str | None = None, quote: str | None = None, base: str = CONTRACTS_PAGE) -> str:
    params = {"doc": doc_id}
    if clause_id:
        params["clause"] = clause_id
    if quote:
        params["quote"] = quote[:300]
    return f"{base}?{urlencode(params)}"


@dataclass
class FieldBadge:
    id: int
    field_type: str
    field_key: str
    status: str
    confidence: float
    verified: bool               # every citation found verbatim in its clause
    value: Any
    summary: str
    citations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ClauseView:
    clause_id: str
    ref: str
    heading: str | None
    level: int
    kind: str
    parent_id: str | None
    char_start: int
    char_end: int
    own: list[tuple[int, int]]                       # absolute ranges not covered by sub-clauses
    fields: list[FieldBadge] = field(default_factory=list)
    flags: list[dict[str, Any]] = field(default_factory=list)
    is_target: bool = False


@dataclass
class ContractView:
    doc: dict[str, Any]
    original: dict[str, Any]
    clauses: list[ClauseView]
    fields: list[FieldBadge]
    flags: list[dict[str, Any]]
    relations: list[dict[str, Any]]
    files: list[dict[str, Any]]
    text: str
    target: dict[str, Any] | None = None
    # Highlighted spans over the whole text, (start, end, "cite" | "target"). Clause own-ranges partition
    # the text, so a span shows exactly where its words are, even across sub-clauses.
    marks: list[tuple[int, int, str]] = field(default_factory=list)

    def clause(self, clause_id: str) -> ClauseView | None:
        return next((c for c in self.clauses if c.clause_id == clause_id), None)


def _summary(value: Any, limit: int = 180) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        parts = [f"{k}: {v}" for k, v in value.items() if v not in (None, "", [], {})]
        text = "; ".join(parts)
    else:
        text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _own_ranges(c: Clause, children: list[Clause]) -> list[tuple[int, int]]:
    out, pos = [], c.char_start
    for ch in sorted(children, key=lambda x: x.char_start):
        if ch.char_start > pos:
            out.append((pos, ch.char_start))
        pos = max(pos, ch.char_end)
    if pos < c.char_end:
        out.append((pos, c.char_end))
    return out


def _badge(ex: Extraction, cites: list[Citation]) -> FieldBadge:
    return FieldBadge(
        id=ex.id or 0, field_type=ex.field_type, field_key=ex.field_key, status=ex.status,
        confidence=ex.confidence, verified=bool(cites) and all(c.verified for c in cites),
        value=ex.value, summary=_summary(ex.value) or ex.raw_text[:180],
        citations=[{"clause_id": c.clause_id, "clause_ref": c.clause_ref, "quote": c.quote, "verified": c.verified,
                    "match_method": c.match_method, "char_start": c.char_start, "char_end": c.char_end}
                   for c in cites],
    )


def get_contract_view(
    doc_id: str,
    clause_id: str | None = None,
    quote: str | None = None,
    *,
    store: StateStore | None = None,
    files: FileStore | None = None,
    cfg: OdinConfig | None = None,
    with_urls: bool = True,
) -> ContractView:
    if store is None or files is None or cfg is None:
        from odin.runtime import get_runtime

        rt = get_runtime(cfg)
        store, files, cfg = store or rt.store, files or rt.files, cfg or rt.cfg
    doc = store.get_document(doc_id)
    if doc is None:
        raise LookupError(f"no document {doc_id!r}")
    try:
        text = document_text(cfg, doc)
    except OSError:
        text = ""
    clauses = store.list_clauses(doc_id)
    extractions = store.current_extractions(doc_id)
    by_ex: dict[int, list[Citation]] = {}
    for c in store.citations_for_document(doc_id):
        by_ex.setdefault(c.extraction_id or 0, []).append(c)
    badges = [_badge(ex, by_ex.get(ex.id or 0, [])) for ex in extractions]
    flags = [f.model_dump() for f in store.list_flags(doc_id)]

    # Clause tree -> views with own text ranges.
    children: dict[str, list[Clause]] = {}
    for c in clauses:
        if c.parent_id:
            children.setdefault(c.parent_id, []).append(c)
    views = [ClauseView(c.clause_id, c.ref, c.heading, c.level, c.kind, c.parent_id, c.char_start, c.char_end,
                        _own_ranges(c, children.get(c.clause_id, []))) for c in clauses]
    by_id = {v.clause_id: v for v in views}
    marks: list[tuple[int, int, str]] = []
    for b in badges:
        for cite in b.citations:
            if cite["verified"] and cite["char_start"] is not None:
                marks.append((cite["char_start"], cite["char_end"], "cite"))
            v = by_id.get(cite["clause_id"] or "")
            if v is not None and all(f.id != b.id for f in v.fields):
                v.fields.append(b)
    for f in flags:
        if f.get("clause_id") in by_id:
            by_id[f["clause_id"]].flags.append(f)

    target = _locate_target(doc_id, clauses, text, by_id, clause_id, quote) if (clause_id or quote) else None
    if target and target["found"]:
        marks.append((target["char_start"], target["char_end"], "target"))

    original: dict[str, Any] = {"available": bool(doc.storage_path), "storage_path": doc.storage_path,
                                "filename": doc.original_filename, "mime_type": doc.mime_type,
                                "backend": getattr(files, "backend", None), "url": None, "download_url": None}
    if doc.storage_path and with_urls:
        ttl = cfg.state.signed_url_ttl_s
        try:
            original["url"] = files.signed_url(doc.storage_path, ttl)
            original["download_url"] = files.signed_url(doc.storage_path, ttl, download=True)
            if original["url"]:
                original["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat(timespec="seconds")
        except StoreError as exc:
            original["error"] = str(exc)

    meta = doc.model_dump(exclude={"text"})
    meta["clauses"] = len(clauses)
    meta["fields"] = sum(1 for b in badges if b.status != "missing")
    meta["missing"] = sum(1 for b in badges if b.status == "missing")
    meta["open_flags"] = len(flags)
    return ContractView(
        doc=meta, original=original, clauses=views, fields=badges, flags=flags,
        relations=[r.model_dump() for r in store.list_relations(doc_id)],
        files=[f.model_dump() for f in store.list_document_files(doc_id)],
        text=text, target=target, marks=marks,
    )


def _locate_target(doc_id: str, clauses: list[Clause], text: str, by_id: dict[str, ClauseView],
                   clause_ref: str | None, quote: str | None) -> dict[str, Any]:
    index = ClauseIndex(doc_id, clauses, text)
    cid = index.resolve(clause_ref) if clause_ref else None
    target: dict[str, Any] = {"requested_clause": clause_ref, "clause_id": cid, "quote": quote, "found": False,
                              "char_start": None, "char_end": None, "note": None}
    if clause_ref and cid is None:
        target["note"] = f"clause {clause_ref!r} is not a clause of {doc_id}"
    if quote:
        span = None
        if cid is not None:
            c = index.by_id[cid]
            m = find_quote(quote, text[c.char_start:c.char_end])
            if m.found:
                span = (c.char_start + m.start, c.char_start + m.end)  # type: ignore[operator]
        if span is None:
            hits = find_all(quote, text)
            if len(hits) == 1:
                span = hits[0]
                holder = index.deepest_containing(*span)
                if holder is not None and holder.clause_id != cid:
                    target["note"] = (f"quote found in {holder.clause_id}, not in {cid}" if cid
                                      else f"quote found in {holder.clause_id}")
                    cid = holder.clause_id
            elif len(hits) > 1:
                target["note"] = f"quote occurs {len(hits)} times in {doc_id}; give the clause to pick one"
            else:
                target["note"] = (target["note"] + "; " if target["note"] else "") + "quote not found in the document"
        if span is not None:
            target.update(found=True, char_start=span[0], char_end=span[1], quote=text[span[0]:span[1]])
            holder = index.deepest_containing(*span, within=index.descendants(cid)) if cid else None
            cid = holder.clause_id if holder else cid
    target["clause_id"] = cid
    if cid and cid in by_id:
        by_id[cid].is_target = True
    return target


# --------------------------------------------------------------------------- HTML rendering

_CSS = """
:root { --ink:#1f2328; --muted:#59636e; --line:#d1d9e0; --soft:#f6f8fa; --accent:#0969da; --ok:#1a7f37; --warn:#9a6700;
        --bad:#cf222e; --cite:#fff8c5; --target:#ffd33d; }
* { box-sizing:border-box; }
body { margin:0; font:14px/1.5 -apple-system, "Segoe UI", system-ui, sans-serif; color:var(--ink); background:#fff; }
.top { padding:10px 14px; border-bottom:1px solid var(--line); background:var(--soft); font-size:13px; }
.top b { font-weight:600; }
.missing { margin-top:6px; color:var(--muted); }
.missing span { display:inline-block; margin:2px 6px 2px 0; padding:0 6px; border:1px solid var(--line); border-radius:10px; background:#fff; }
.row { display:grid; grid-template-columns:minmax(0, 3fr) minmax(220px, 2fr); gap:14px; padding:10px 14px; border-bottom:1px solid #eef1f4; scroll-margin-top:8px; }
.row.target { background:#fffbe6; box-shadow:inset 4px 0 0 var(--target); }
.lvl-2 { padding-left:22px; } .lvl-3 { padding-left:40px; }
.ref { font-weight:600; font-size:13px; color:var(--accent); }
.ref .id { color:var(--muted); font-weight:400; margin-left:6px; font-size:12px; }
pre.text { margin:4px 0 0; white-space:pre-wrap; word-break:break-word; font:12.5px/1.55 ui-monospace, Consolas, "Cascadia Mono", monospace; }
mark.cite { background:var(--cite); padding:0; }
mark.target { background:var(--target); outline:2px solid #bf8700; padding:0; }
.flag { margin-top:6px; font-size:12px; color:var(--bad); }
.cards { display:flex; flex-direction:column; gap:6px; }
.card { border:1px solid var(--line); border-radius:6px; padding:6px 8px; font-size:12.5px; background:#fff; }
.card .h { display:flex; flex-wrap:wrap; gap:4px; align-items:center; }
.chip { font-size:11px; padding:0 6px; border-radius:10px; border:1px solid var(--line); background:var(--soft); }
.chip.ok { color:var(--ok); border-color:#4ac26b; background:#dafbe1; }
.chip.unv { color:var(--bad); border-color:#ff8182; background:#ffebe9; }
.chip.st-ambiguous, .chip.st-contradictory { color:var(--warn); border-color:#d4a72c; background:#fff8c5; }
.chip.conf-hi { color:var(--ok); } .chip.conf-mid { color:var(--warn); } .chip.conf-lo { color:var(--bad); }
.key { font-weight:600; }
.val { color:var(--muted); margin-top:2px; }
.q { margin-top:3px; font-style:italic; color:#424a53; }
.q a { color:inherit; text-decoration:none; border-bottom:1px dotted var(--muted); }
.empty { color:var(--muted); font-size:12px; }
@media (max-width: 760px) { .row { grid-template-columns:1fr; } }
"""


def _esc(s: str) -> str:
    return html.escape(s, quote=False)


def _render_range(text: str, start: int, end: int, marks: list[tuple[int, int, str]]) -> str:
    """Escape text[start:end], wrapping marked spans (target wins over cite)."""
    pts = {start, end}
    for s, e, _ in marks:
        if s < end and e > start:
            pts.update((max(s, start), min(e, end)))
    edges = sorted(pts)
    out = []
    for a, b in zip(edges, edges[1:]):
        kinds = {k for s, e, k in marks if s <= a and b <= e}
        piece = _esc(text[a:b])
        if "target" in kinds:
            piece = f'<mark class="target">{piece}</mark>'
        elif "cite" in kinds:
            piece = f'<mark class="cite">{piece}</mark>'
        out.append(piece)
    return "".join(out)


def _card(b: FieldBadge, doc_id: str, clause_id: str, link_base: str) -> str:
    conf = "conf-hi" if b.confidence >= 0.8 else ("conf-mid" if b.confidence >= 0.5 else "conf-lo")
    ver = '<span class="chip ok">&#10003; verified</span>' if b.verified else '<span class="chip unv">&#9888; unverified</span>'
    quotes = [c for c in b.citations if c["clause_id"] == clause_id]
    q_html = ""
    for c in quotes[:2]:
        q = c["quote"]
        short = q if len(q) <= 140 else q[:139] + "…"
        href = html.escape(contract_link(doc_id, clause_id, q, base=link_base))
        mark = "" if c["verified"] else " (not found in the text)"
        q_html += f'<div class="q"><a href="{href}" target="_blank" rel="noopener">&ldquo;{_esc(short)}&rdquo;</a>{mark}</div>'
    return (f'<div class="card"><div class="h"><span class="chip">{_esc(b.field_type)}</span>'
            f'<span class="key">{_esc(b.field_key)}</span></div>'
            f'<div class="h" style="margin-top:3px"><span class="chip st-{_esc(b.status)}">{_esc(b.status)}</span>'
            f'<span class="chip {conf}">confidence {b.confidence:.0%}</span>{ver}</div>'
            + (f'<div class="val">{_esc(b.summary)}</div>' if b.summary else "") + q_html + "</div>")


def render_clauses_html(view: ContractView, *, link_base: str = CONTRACTS_PAGE) -> str:
    """Clause-by-clause text with Thor's fields beside the clauses they cite; scrolls to the target."""
    doc_id = view.doc["doc_id"]
    missing = [b for b in view.fields if b.status == "missing"]
    doc_flags = [f for f in view.flags if not f.get("clause_id")]
    top = (f'<div class="top"><b>{_esc(doc_id)}</b> &middot; {len(view.clauses)} clauses &middot; '
           f'{view.doc["fields"]} fields &middot; {sum(1 for b in view.fields if b.verified)} verified &middot; '
           f'{view.doc["open_flags"]} open flags')
    if view.target:
        t = view.target
        state = "highlighted" if t["found"] else ("clause shown" if t["clause_id"] else "not found")
        top += f' &middot; deep link: <b>{_esc(t["clause_id"] or str(t["requested_clause"]))}</b> ({state})'
        if t.get("note"):
            top += f' &mdash; {_esc(t["note"])}'
    if missing:
        top += '<div class="missing">Not found in this document: ' + "".join(
            f'<span title="{html.escape(b.summary or b.field_key)}">{_esc(b.field_type)}: {_esc(b.field_key)}</span>'
            for b in missing) + "</div>"
    for f in doc_flags:
        top += f'<div class="flag">&#9873; [{_esc(f["type"])}] {_esc(f["description"])}</div>'
    top += "</div>"

    rows = []
    target_anchor = None
    for v in view.clauses:
        anchor = f"clause-{v.clause_id}"
        if v.is_target:
            target_anchor = anchor
        body = "".join(_render_range(view.text, s, e, view.marks) for s, e in v.own).strip("\n")
        title = _esc(v.ref) + (f" &mdash; {_esc(v.heading)}" if v.heading and v.heading not in v.ref else "")
        flags = "".join(f'<div class="flag">&#9873; [{_esc(f["type"])}] {_esc(f["description"])}</div>' for f in v.flags)
        cards = "".join(_card(b, doc_id, v.clause_id, link_base) for b in v.fields if b.status != "missing")
        rows.append(
            f'<div class="row{" target" if v.is_target else ""}" id="{html.escape(anchor)}">'
            f'<div class="lvl-{min(v.level, 3)}"><div class="ref">{title}<span class="id">{_esc(v.clause_id)}</span></div>'
            + (f'<pre class="text">{body}</pre>' if body.strip() else "")
            + flags + "</div>"
            f'<div class="cards">{cards or ""}</div></div>'
        )
    script = ""
    if target_anchor:
        script = ("<script>window.addEventListener('load',function(){var t=document.getElementById("
                  + json.dumps(target_anchor) + ");if(t){t.scrollIntoView({block:'start'});"
                  "var m=t.querySelector('mark.target');if(m){m.scrollIntoView({block:'center'});}}});</script>")
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{_CSS}</style></head><body>{top}{''.join(rows)}{script}</body></html>"

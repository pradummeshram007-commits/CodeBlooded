"""Contracts: upload, the document table, and "See the contract" (Original PDF + Clauses).

Deep link: /Contracts?doc=A1&clause=A1:4.2[&quote=...] opens the contract on the Clauses
tab, scrolled to that clause, with the cited quote highlighted.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # app/ (for ui), which adds the repo root

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

from ui import KIND_LABELS, PARSE_COLORS, THOR_COLORS, badge, frame_blocked, original_bytes, runtime_or_stop, signed_urls  # noqa: E402
from odin.ingest.upload import UploadRejected, ingest_file, run_thor_on  # noqa: E402
from odin.llm import llm_config_problem  # noqa: E402
from odin.state.errors import StoreError  # noqa: E402
from odin.viewer import contract_link, get_contract_view, render_clauses_html  # noqa: E402

st.set_page_config(page_title="Contracts · Odin", page_icon="📄", layout="wide")
rt = runtime_or_stop()
store, files, cfg = rt.store, rt.files, rt.cfg


def open_contract(doc_id: str) -> None:
    st.query_params.clear()
    st.query_params["doc"] = doc_id


def close_contract() -> None:
    st.query_params.clear()


# --------------------------------------------------------------------------- upload


def upload_section() -> None:
    st.subheader("Upload contracts")
    llm_problem = llm_config_problem(cfg)
    nonce = st.session_state.setdefault("upload_nonce", 0)
    uploads = st.file_uploader(
        f"PDF or TXT, up to {cfg.upload.max_upload_mb:g} MB each. A .txt and .pdf with the same name become one "
        "document (the .txt is the text, the .pdf the viewable original).",
        type=["pdf", "txt"], accept_multiple_files=True, key=f"uploader-{nonce}",
    )
    extract = st.checkbox("Run Thor extraction after upload", value=llm_problem is None, disabled=llm_problem is not None,
                          help=llm_problem or "Thor skips documents it already extracted; cached LLM calls are free.")
    if llm_problem:
        st.caption(f"Thor is not configured: {llm_problem}")
    if not uploads or not st.button(f"Process {len(uploads)} file(s)", type="primary"):
        return
    summary = []
    for up in uploads:
        with st.status(f"{up.name}: processing…", expanded=True) as status:
            try:
                res = ingest_file(up.getvalue(), up.name, store=store, files=files, cfg=cfg, extract=extract,
                                  progress=status.write)
            except UploadRejected as exc:
                status.update(label=f"{up.name}: rejected", state="error")
                summary.append(("error", str(exc)))
                continue
            except StoreError as exc:
                status.update(label=f"{up.name}: storage error", state="error")
                summary.append(("error", f"{up.name}: {exc}"))
                continue
            bad = res.parse_status == "unparseable" or bool(res.thor_error) or (res.thor and res.thor.status == "failed")
            thor = f", Thor {res.thor.status}" if res.thor else (f", {res.thor_error}" if res.thor_error else "")
            status.update(label=f"{up.name}: {res.outcome} → {res.doc_id}{thor}", state="error" if bad else "complete",
                          expanded=False)
            summary.append(("warning" if bad else "success", f"**{up.name}** → {res.doc_id}: {res.message}{thor}"))
    st.session_state["upload_summary"] = summary
    st.session_state["upload_nonce"] = nonce + 1           # clears the uploader
    st.rerun()


def show_last_upload() -> None:
    for kind, text in st.session_state.pop("upload_summary", []):
        getattr(st, kind)(text)


# --------------------------------------------------------------------------- table


def documents_table() -> None:
    docs = store.list_documents(include_text=False)
    stats = store.document_stats()
    st.subheader(f"Documents ({len(docs)})")
    if not docs:
        st.info("No documents yet: upload one above, or run `python scripts/seed_bundle.py`.")
        return
    docs.sort(key=lambda d: (d.kind != "standard_terms", d.doc_id))
    widths = [0.7, 3.6, 1.3, 1.1, 1.1, 0.7, 0.7, 1.5]
    head = st.columns(widths)
    for col, name in zip(head, ["ID", "Title", "Type", "Parse", "Thor", "Fields", "Flags", ""]):
        col.markdown(f"**{name}**")
    for d in docs:
        s = stats.get(d.doc_id, {})
        c = st.columns(widths, vertical_alignment="center")
        c[0].markdown(f"`{d.doc_id}`")
        source = {"txt": ".txt", "pdf_extracted": "PDF text"}.get(d.text_source or "", "")
        c[1].markdown(f"{d.title}  \n:gray[{d.original_filename or d.path}{' · text from ' + source if source else ''}]")
        c[2].write(KIND_LABELS.get(d.kind, d.kind))
        c[3].markdown(badge(d.parse_status, PARSE_COLORS))
        c[4].markdown(badge(d.status, THOR_COLORS), help=d.status_reason)
        c[5].markdown(str(s.get("fields", 0)))
        c[6].markdown(str(s.get("flags", 0)))
        c[7].button("See the contract", key=f"see-{d.doc_id}", on_click=open_contract, args=(d.doc_id,))


# --------------------------------------------------------------------------- contract view


def original_tab(view) -> None:
    o = view.original
    if not o["available"]:
        st.info("No original file is stored for this document (ingested before uploads were kept). "
                "Upload its .pdf or .txt to attach one.")
        return
    url, download_url = (signed_urls(o["storage_path"]) if files.backend == "supabase" else (None, None))
    name, mime = o["filename"] or Path(o["storage_path"]).name, o["mime_type"] or ""
    if mime == "application/pdf":
        modes = (["Embedded (signed URL)"] if url else []) + ["PDF viewer (pdf.js)"]
        why = frame_blocked(url) if url else "no URL for the local file store"
        mode = st.radio("Viewer", modes, horizontal=True, index=0 if url and not why else len(modes) - 1,
                        help=f"The embedded view needs a browser that shows PDFs in frames{'; ' + why if why else ''}. "
                             "If it stays blank, switch to the pdf.js viewer.", label_visibility="collapsed")
        if mode.startswith("Embedded"):
            # Not st.iframe: Streamlit sandboxes that frame and Chromium refuses to show PDFs in sandboxed frames.
            st.markdown(f'<iframe src="{html.escape(url, quote=True)}" title="{html.escape(name, quote=True)}" '
                        'style="width:100%;height:900px;border:0"></iframe>', unsafe_allow_html=True)
        else:
            try:
                from streamlit_pdf_viewer import pdf_viewer

                pdf_viewer(original_bytes(o["storage_path"]), height=900, render_text=True, key=f"pdf-{view.doc['doc_id']}")
            except Exception as exc:  # noqa: BLE001 - last fallback is the download link below
                st.warning(f"The PDF viewer could not render this file ({type(exc).__name__}); use the download below.")
    else:
        st.code(original_bytes(o["storage_path"]).decode("utf-8", errors="replace"), language=None, height=900,
                wrap_lines=True)
    cols = st.columns([1, 1, 3])
    cols[0].download_button("Download original", original_bytes(o["storage_path"]), file_name=name, mime=mime or None)
    if download_url:
        cols[1].link_button("Open in a new tab", url)
    stamp = f" · signed URL valid for {cfg.state.signed_url_ttl_s // 60} min" if url else ""
    cols[2].caption(f"{name} · {o['storage_path']} · {files.describe()}{stamp}")


def contract_view(doc_id: str, clause: str | None, quote: str | None) -> None:
    st.button("← All contracts", on_click=close_contract)
    try:
        view = get_contract_view(doc_id, clause, quote, store=store, files=files, cfg=cfg, with_urls=False)
    except LookupError:
        st.error(f"No document {doc_id!r}.")
        return
    d = view.doc
    st.title(f"{d['doc_id']} · {d['title']}")
    st.markdown(
        f"{KIND_LABELS.get(d['kind'], d['kind'])} · Thor {badge(d['status'], THOR_COLORS)} · parse "
        f"{badge(d['parse_status'], PARSE_COLORS)} · text from `{d['original_filename'] if d['text_source'] == 'pdf_extracted' else (Path(d['path']).name)}`"
        + (f" · own ID `{d['external_id']}`" if d.get("external_id") else "")
    )
    if d.get("status_reason") and d["status"] != "complete":
        st.caption(f"Thor: {d['status_reason']}")
    m = st.columns(5)
    m[0].metric("Clauses", d["clauses"])
    m[1].metric("Fields", d["fields"])
    m[2].metric("Verified", sum(1 for b in view.fields if b.verified))
    m[3].metric("Not found", d["missing"])
    m[4].metric("Open flags", d["open_flags"])
    if store.needs_extraction(doc_id) and llm_config_problem(cfg) is None:
        if st.button(f"Run Thor on {doc_id}"):
            with st.spinner("Thor is extracting… (cached LLM calls are free)"):
                _, error = run_thor_on(store, cfg, doc_id)
            if error:
                st.error(error)
            else:
                st.rerun()

    t = view.target
    if t and not t["found"] and t.get("note"):
        st.warning(f"Deep link: {t['note']}")
    tabs = st.tabs(["Original", "Clauses"], default="Clauses" if t else "Original")
    with tabs[0]:
        original_tab(view)
    with tabs[1]:
        components.html(render_clauses_html(view), height=900, scrolling=True)
        if t and t.get("clause_id"):
            st.caption(f"Deep link to this clause: `{contract_link(doc_id, t['clause_id'], quote if t['found'] else None)}`")
    with st.expander(f"Relations ({len(view.relations)}) and stored files ({len(view.files)})"):
        for r in view.relations:
            cite = r.get("citation") or {}
            link = contract_link(r["clause_id"].split(":", 1)[0], r["clause_id"], cite.get("quote")) if r.get("clause_id") else None
            target = f" → {cite['target_clause']}" if cite.get("target_clause") else ""
            st.markdown(f"- **{r['from_doc']}** {r['type']} **{r['to_doc']}**{target}"
                        + (f" — [{r['clause_id']}]({link})" if link else ""))
        for f in view.files:
            sim = f" · similarity to .txt {f['similarity']:.3f}" if f.get("similarity") is not None else ""
            st.markdown(f"- `{f['storage_path']}` ({f['role']}, {f['mime_type']}, {f['size_bytes']:,} bytes{sim})")


# --------------------------------------------------------------------------- page

params = st.query_params
if params.get("doc"):
    contract_view(params["doc"], params.get("clause"), params.get("quote"))
else:
    st.title("Contracts")
    st.caption(rt.describe())
    show_last_upload()
    upload_section()
    st.divider()
    documents_table()

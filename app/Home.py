"""Odin dashboard entry point:  streamlit run app/Home.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # app/ (for ui), which adds the repo root

import streamlit as st  # noqa: E402

from ui import THOR_COLORS, badge, runtime_or_stop  # noqa: E402

st.set_page_config(page_title="Odin", page_icon="⚖️", layout="wide")
st.title("Odin — contract war room")
rt = runtime_or_stop()
st.caption(rt.describe())

docs = rt.store.list_documents(include_text=False)
stats = rt.store.document_stats()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Documents", len(docs))
c2.metric("Extracted by Thor", sum(1 for d in docs if d.status == "complete"))
c3.metric("Fields", sum(s["fields"] for s in stats.values()))
c4.metric("Open flags", sum(s["flags"] for s in stats.values()))

st.page_link("pages/1_Contracts.py", label="Contracts: upload, browse, see the contract", icon="📄")
if docs:
    st.markdown(" · ".join(f"**{d.doc_id}** {badge(d.status, THOR_COLORS)}" for d in docs))

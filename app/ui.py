"""Shared Streamlit helpers: one runtime per server process, signed-URL caching, status badges.

Everything here runs server-side. The browser only ever receives rendered HTML and
signed URLs that expire; the Supabase secret key never leaves this process.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from odin.runtime import Runtime, get_runtime  # noqa: E402
from odin.state.errors import StoreError  # noqa: E402

THOR_COLORS = {"complete": "green", "partial": "orange", "failed": "red", "extracting": "blue", "pending": "gray"}
PARSE_COLORS = {"parsed": "green", "fallback": "orange", "unparseable": "red"}
KIND_LABELS = {"contract": "Contract", "standard_terms": "Standard terms", "amendment": "Amendment", "addendum": "Addendum"}


@st.cache_resource(show_spinner="Connecting to the state store…")
def _runtime() -> Runtime:
    return get_runtime()


def runtime_or_stop() -> Runtime:
    """The shared runtime, or a clear error (with the STATE_BACKEND=sqlite hint) and stop."""
    try:
        return _runtime()
    except StoreError as exc:
        st.error(f"**State store unavailable.** {exc}")
        st.stop()
        raise  # unreachable; keeps type checkers happy


def badge(text: str | None, colors: dict[str, str]) -> str:
    if not text:
        return ":gray[—]"
    return f":{colors.get(text, 'gray')}[{text}]"


@st.cache_data(ttl=50 * 60, show_spinner=False)
def signed_urls(storage_path: str) -> tuple[str | None, str | None]:
    """(inline URL, download URL), reused for 50 minutes so reruns don't reload the PDF frame."""
    rt = _runtime()
    ttl = rt.cfg.state.signed_url_ttl_s
    return rt.files.signed_url(storage_path, ttl), rt.files.signed_url(storage_path, ttl, download=True)


@st.cache_data(ttl=50 * 60, show_spinner=False, max_entries=32)
def original_bytes(storage_path: str) -> bytes:
    return _runtime().files.download(storage_path)


@st.cache_data(ttl=50 * 60, show_spinner=False)
def frame_blocked(url: str) -> str | None:
    """Why the browser would refuse to show this URL in an iframe (None = it should render)."""
    import httpx

    try:
        with httpx.stream("GET", url, timeout=15, follow_redirects=True) as r:
            h = {k.lower(): v for k, v in r.headers.items()}
            status = r.status_code
    except httpx.HTTPError as exc:
        return f"could not reach the file ({type(exc).__name__})"
    if status >= 400:
        return f"the signed URL answered HTTP {status}"
    if h.get("x-frame-options", "").upper() in ("DENY", "SAMEORIGIN"):
        return f"X-Frame-Options: {h['x-frame-options']}"
    csp = h.get("content-security-policy", "")
    if "frame-ancestors" in csp and "*" not in csp.split("frame-ancestors", 1)[1].split(";", 1)[0]:
        return "Content-Security-Policy frame-ancestors"
    if h.get("content-disposition", "").lower().startswith("attachment"):
        return "the server sends it as a download (Content-Disposition: attachment)"
    return None

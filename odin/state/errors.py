"""Errors raised by the state and file stores, with secrets scrubbed from every message."""
from __future__ import annotations

from typing import Iterable
from urllib.parse import quote, unquote, urlsplit

SQLITE_HINT = "Set STATE_BACKEND=sqlite in .env to use the local SQLite store and file folder instead."


class StoreError(RuntimeError):
    """A state-store problem that is not a transient connection failure (schema missing, bad config)."""


class StoreUnavailable(StoreError):
    """The Postgres backend could not be reached (after retries). Nothing was half-written."""


class StorageUnavailable(StoreError):
    """The file store (Supabase Storage) could not be reached or rejected the request (after retries)."""


def secrets_of(*values: str | None) -> list[str]:
    """Secret strings to scrub: raw values plus the password inside a connection URL, encoded and decoded."""
    out: list[str] = []
    for v in values:
        if not v:
            continue
        out.append(v)
        if "://" in v:
            try:
                pw = urlsplit(v).password
            except ValueError:
                pw = None
            if pw:
                out += [pw, unquote(pw), quote(unquote(pw), safe="")]
    return [s for s in out if len(s) >= 4]


def redact(text: str, secrets: Iterable[str]) -> str:
    for s in sorted(set(secrets), key=len, reverse=True):
        text = text.replace(s, "***")
    return text

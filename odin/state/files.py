"""File store for uploaded originals: Supabase Storage, or a local folder for the SQLite backend.

Paths are content-addressed, ``{doc_id}/{sha256}/{filename}``, so an upload is idempotent
and an older version is never overwritten by a newer one.

The Supabase secret key is used here, server-side only. It is never logged, never put in
an error message, and never sent to the browser: the browser only ever receives signed
URLs that expire (1 hour by default).
"""
from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar

from odin.state.errors import SQLITE_HINT, StorageUnavailable, redact, secrets_of

T = TypeVar("T")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    """Storage keys keep to [A-Za-z0-9._-]; the real name stays in original_filename."""
    base = Path(name).name or "file"
    stem, dot, ext = base.rpartition(".")
    stem, ext = (stem, ext) if dot else (base, "")
    clean = _SAFE_NAME_RE.sub("_", stem).strip("._") or "file"
    return f"{clean}.{_SAFE_NAME_RE.sub('', ext).lower()}" if ext else clean


def object_path(doc_id: str, sha256: str, filename: str) -> str:
    return f"{doc_id}/{sha256}/{safe_filename(filename)}"


class FileStore(Protocol):
    backend: str
    bucket: str

    def ensure_bucket(self) -> bool: ...
    def upload(self, path: str, data: bytes, content_type: str) -> None: ...
    def download(self, path: str) -> bytes: ...
    def exists(self, path: str) -> bool: ...
    def signed_url(self, path: str, expires_in: int, *, download: bool = False) -> str | None: ...
    def describe(self) -> str: ...


class LocalFileStore:
    """state/files/<bucket>/...; there are no URLs, the viewer reads the bytes directly."""

    backend = "local"

    def __init__(self, root: Path, bucket: str = "contracts"):
        self.root = Path(root)
        self.bucket = bucket

    def describe(self) -> str:
        return f"local folder ({self.root / self.bucket})"

    def _full(self, path: str) -> Path:
        full = (self.root / self.bucket / path).resolve()
        if not str(full).startswith(str((self.root / self.bucket).resolve())):
            raise ValueError(f"path escapes the file store: {path!r}")
        return full

    def ensure_bucket(self) -> bool:
        existed = (self.root / self.bucket).exists()
        (self.root / self.bucket).mkdir(parents=True, exist_ok=True)
        return not existed

    def upload(self, path: str, data: bytes, content_type: str) -> None:
        full = self._full(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=full.parent, prefix=".upload-")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, full)                 # atomic: never a half-written original

    def download(self, path: str) -> bytes:
        return self._full(path).read_bytes()

    def exists(self, path: str) -> bool:
        return self._full(path).is_file()

    def signed_url(self, path: str, expires_in: int, *, download: bool = False) -> str | None:
        return None


class SupabaseFileStore:
    """A private Supabase Storage bucket, accessed with the secret key through supabase-py."""

    backend = "supabase"

    def __init__(self, supabase_url: str, secret_key: str, bucket: str = "contracts", *, retries: int = 3,
                 backoff_s: float = 1.0, file_size_limit: int | None = None, sleep: Callable[[float], None] = time.sleep):
        if not supabase_url or not secret_key:
            raise StorageUnavailable(f"STATE_BACKEND=supabase needs SUPABASE_URL and SUPABASE_SECRET_KEY. {SQLITE_HINT}")
        self.url = supabase_url.rstrip("/")
        self.bucket = bucket
        self.retries = retries
        self.backoff_s = backoff_s
        self.file_size_limit = file_size_limit
        self._sleep = sleep
        self._key = secret_key
        self._secrets = secrets_of(secret_key)
        self._client: Any = None
        self._bucket_ready = False

    def __repr__(self) -> str:  # never show the key
        return f"SupabaseFileStore(url={self.url!r}, bucket={self.bucket!r})"

    def describe(self) -> str:
        return f"supabase storage ({self.url}, bucket {self.bucket!r}, private)"

    def _storage(self) -> Any:
        if self._client is None:
            from supabase import create_client

            self._client = create_client(self.url, self._key)
        return self._client.storage

    @staticmethod
    def _status(exc: BaseException) -> int | None:
        status = getattr(exc, "status", None) or getattr(getattr(exc, "response", None), "status_code", None)
        try:
            return int(status) if status is not None else None
        except (TypeError, ValueError):
            return None

    def _retry(self, what: str, fn: Callable[[], T]) -> T:
        import httpx

        delay = self.backoff_s
        last: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 - classified below
                status = self._status(exc)
                if isinstance(exc, httpx.TransportError):
                    transient = True                       # network: connect / read timeouts, resets
                elif status is not None:
                    transient = status >= 500 or status == 429
                else:
                    transient = False                      # not an HTTP failure: report it, don't loop
                last = exc
                if not transient:
                    break
                self._client = None          # fresh HTTP client on the next attempt
            if attempt < self.retries:
                self._sleep(delay)
                delay *= 2
        assert last is not None
        detail = " ".join(redact(f"{type(last).__name__}: {last}", self._secrets).split())[:300]
        raise StorageUnavailable(
            f"Supabase Storage {what} failed ({self.url}, bucket {self.bucket!r}): {detail}. "
            f"Check SUPABASE_URL / SUPABASE_SECRET_KEY and your network. {SQLITE_HINT}"
        ) from last

    def ensure_bucket(self) -> bool:
        """Create the private bucket if it does not exist. Returns True when it was created."""
        if self._bucket_ready:
            return False

        def go() -> bool:
            storage = self._storage()
            if any(b.id == self.bucket or b.name == self.bucket for b in storage.list_buckets()):
                return False
            options: dict[str, Any] = {"public": False}
            if self.file_size_limit:
                options["file_size_limit"] = self.file_size_limit
            storage.create_bucket(self.bucket, options=options)
            return True

        created = self._retry("bucket setup", go)
        self._bucket_ready = True
        return created

    def upload(self, path: str, data: bytes, content_type: str) -> None:
        # upsert: the same content-addressed path always holds the same bytes, so a retry is harmless.
        self._retry(f"upload of {path!r}", lambda: self._storage().from_(self.bucket).upload(
            path, data, {"content-type": content_type, "upsert": "true"}))

    def download(self, path: str) -> bytes:
        return self._retry(f"download of {path!r}", lambda: self._storage().from_(self.bucket).download(path))

    def exists(self, path: str) -> bool:
        return self._retry(f"lookup of {path!r}", lambda: self._storage().from_(self.bucket).exists(path))

    def signed_url(self, path: str, expires_in: int, *, download: bool = False) -> str | None:
        options = {"download": True} if download else None
        res = self._retry(f"signed URL for {path!r}", lambda: self._storage().from_(self.bucket).create_signed_url(
            path, expires_in, options))
        return res.get("signedURL") or res.get("signedUrl")

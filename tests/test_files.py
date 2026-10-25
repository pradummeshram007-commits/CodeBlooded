"""File stores: local folder always; the real Supabase bucket only when SUPABASE_URL + SUPABASE_SECRET_KEY are set."""
from __future__ import annotations

import uuid

import httpx
import pytest

from odin.state.errors import StorageUnavailable
from odin.state.files import LocalFileStore, SupabaseFileStore, object_path, safe_filename

from .conftest import supabase_env


def test_object_paths_are_content_addressed_and_safe() -> None:
    assert object_path("A1", "ab12", "A1.pdf") == "A1/ab12/A1.pdf"
    assert safe_filename("My Contract (v2).PDF") == "My_Contract_v2.pdf"
    assert safe_filename("../../etc/passwd") == "passwd"


def test_local_file_store_round_trip(tmp_path) -> None:
    fs = LocalFileStore(tmp_path)
    assert fs.ensure_bucket() is True and fs.ensure_bucket() is False
    fs.upload("A1/ab/A1.pdf", b"%PDF-1.4", "application/pdf")
    assert fs.exists("A1/ab/A1.pdf") and fs.download("A1/ab/A1.pdf") == b"%PDF-1.4"
    assert fs.signed_url("A1/ab/A1.pdf", 60) is None
    with pytest.raises(ValueError):
        fs.upload("../outside.txt", b"x", "text/plain")


def test_storage_errors_name_the_fallback_and_hide_the_key() -> None:
    fs = SupabaseFileStore("http://127.0.0.1:1", "sb_secret_DO-NOT-PRINT-ME", retries=1, backoff_s=0.0,
                           sleep=lambda s: None)
    with pytest.raises(StorageUnavailable) as err:
        fs.ensure_bucket()
    msg = str(err.value)
    assert "STATE_BACKEND=sqlite" in msg and "DO-NOT-PRINT-ME" not in msg and "DO-NOT-PRINT-ME" not in repr(fs)


@pytest.fixture(scope="module")
def bucket() -> SupabaseFileStore:
    url, key = supabase_env("SUPABASE_URL"), supabase_env("SUPABASE_SECRET_KEY")
    if not (url and key):
        pytest.skip("SUPABASE_URL / SUPABASE_SECRET_KEY not set: Storage test skipped")
    fs = SupabaseFileStore(url, key, supabase_env("SUPABASE_BUCKET") or "contracts")
    fs.ensure_bucket()
    return fs


def test_supabase_storage_round_trip_and_signed_url(bucket) -> None:
    path = f"_pytest/{uuid.uuid4().hex}/hello.txt"
    try:
        bucket.upload(path, b"odin storage test", "text/plain; charset=utf-8")
        bucket.upload(path, b"odin storage test", "text/plain; charset=utf-8")    # idempotent (upsert)
        assert bucket.exists(path) and bucket.download(path) == b"odin storage test"
        url = bucket.signed_url(path, 60)
        assert url and "token=" in url
        assert httpx.get(url, timeout=20).content == b"odin storage test"
        public = f"{bucket.url}/storage/v1/object/public/{bucket.bucket}/{path}"
        assert httpx.get(public, timeout=20).status_code in (400, 404)           # private bucket: no public URL
    finally:
        bucket._storage().from_(bucket.bucket).remove([path])

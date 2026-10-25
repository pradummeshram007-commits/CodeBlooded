"""Streamlit Contracts page, headless (streamlit.testing): table, "See the contract", deep link."""
from __future__ import annotations

import pytest

from odin.config import ROOT
from odin.ingest.upload import ingest_file
from odin.runtime import reset_runtime
from odin.state.backend import open_file_store
from odin.state.store import SQLiteStateStore

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
PAGE = str(ROOT / "app" / "pages" / "1_Contracts.py")


@pytest.fixture
def app_env(monkeypatch, tmp_path, cfg):
    import streamlit as st

    monkeypatch.setenv("STATE_BACKEND", "sqlite")
    monkeypatch.setenv("ODIN_DB_PATH", str(cfg.paths.db_path))
    monkeypatch.setenv("ODIN_FILES_DIR", str(cfg.paths.files_dir))
    store = SQLiteStateStore(cfg.paths.db_path)
    files = open_file_store(cfg)
    bundle = cfg.paths.bundle_dir / "contracts"
    for name in ("A1.txt", "A1.pdf", "A3.txt"):
        ingest_file((bundle / name).read_bytes(), name, store=store, files=files, cfg=cfg, extract=False)
    store.close()
    reset_runtime()
    st.cache_resource.clear()
    st.cache_data.clear()
    yield
    reset_runtime()
    st.cache_resource.clear()
    st.cache_data.clear()


def test_contracts_table_lists_documents(app_env) -> None:
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception, at.exception
    assert at.title[0].value == "Contracts"
    labels = [b.label for b in at.button]
    assert labels.count("See the contract") == 2
    at.button(key="see-A1").click().run()
    assert at.query_params["doc"] == ["A1"] or at.query_params["doc"] == "A1"
    assert at.title[0].value.startswith("A1 · ")
    assert [t.label for t in at.tabs] == ["Original", "Clauses"]


def test_deep_link_opens_the_clause(app_env) -> None:
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.query_params["doc"] = "A1"
    at.query_params["clause"] = "A1:preamble"
    at.query_params["quote"] = "this Cover Page controls"
    at.run()
    assert not at.exception, at.exception
    assert at.title[0].value.startswith("A1 · ")
    assert any("Deep link to this clause" in c.value for c in at.caption)
    assert not at.warning                                  # the quote was found


def test_unknown_document_is_an_error_not_a_crash(app_env) -> None:
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.query_params["doc"] = "NOPE"
    at.run()
    assert not at.exception and "No document" in at.error[0].value

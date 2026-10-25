"""Shared fixtures. No test makes a real LLM call: providers are replaced by FakeProvider.

``any_store`` runs a test against both backends: SQLite (always) and Supabase Postgres
(only when SUPABASE_DB_URL is set in the environment or .env; skipped otherwise). The
Postgres tests use a throwaway schema ``odin_test_<random>`` with the migrations applied,
truncated between tests and dropped at the end, so the real ``public`` tables are never touched.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
from dotenv import dotenv_values

from odin.config import ROOT, OdinConfig, load_config, normalize_db_url
from odin.ingest.bundle import ingest_bundle
from odin.llm import LLMClient, ProviderResponse
from odin.state.store import TABLES, SQLiteStateStore, StateStore

DOC_IDS = ["STD", "A1", "A2", "A3", "B1", "B2", "C1", "D1"]


class FakeProvider:
    """Scripted provider: ``responder(system, messages)`` returns the reply text."""

    name = "fake"

    def __init__(self, responder: Callable[[str | None, list[dict[str, str]]], str], model: str = "fake-model"):
        self.responder = responder
        self.model = model
        self.calls: list[list[dict[str, str]]] = []

    def settings_fingerprint(self) -> dict[str, Any]:
        return {}

    def complete(self, system, messages, max_tokens) -> ProviderResponse:
        self.calls.append(messages)
        text = self.responder(system, messages)
        return ProviderResponse(text=text, input_tokens=100, output_tokens=50, stop_reason="end_turn", model=self.model)


def doc_id_of(messages: list[dict[str, str]]) -> str:
    m = re.search(r"^doc_id: (\S+)$", messages[0]["content"], re.M)
    assert m, "prompt has no doc_id header"
    return m.group(1)


@pytest.fixture
def cfg(tmp_path: Path) -> OdinConfig:
    c = load_config(env={"ODIN_DB_PATH": str(tmp_path / "odin.db"), "ODIN_OUTPUTS_DIR": str(tmp_path / "out"),
                         "ODIN_FILES_DIR": str(tmp_path / "files")})
    c.paths.llm_cache_dir = tmp_path / "llm-cache"
    c.limits.backoff_base_s = 0.0
    c.thor.recall_check = False   # scripted fake replies; the recall pass would add unscripted calls
    return c


@pytest.fixture
def store(cfg: OdinConfig) -> Iterator[StateStore]:
    s = SQLiteStateStore(cfg.paths.db_path)
    yield s
    s.close()


@pytest.fixture
def ingested(store: StateStore, cfg: OdinConfig) -> StateStore:
    ingest_bundle(store, cfg, include_pdfs=False)
    return store


# --------------------------------------------------------------------------- Postgres (Supabase)


def supabase_env(key: str) -> str | None:
    """A Supabase setting from the environment, else from .env (tests never load .env into os.environ)."""
    value = os.environ.get(key) or dotenv_values(ROOT / ".env").get(key)
    return value.strip().strip('"') if value else None


@pytest.fixture(scope="session")
def pg_schema() -> Iterator[tuple[str, str]]:
    url = supabase_env("SUPABASE_DB_URL")
    if not url or os.environ.get("ODIN_TEST_POSTGRES") == "0":
        pytest.skip("SUPABASE_DB_URL not set: Postgres backend tests skipped")
    from odin.state.migrate import apply_migrations

    url = normalize_db_url(url)
    schema = f"odin_test_{uuid.uuid4().hex[:8]}"
    apply_migrations(url, ROOT / "supabase" / "migrations", schema=schema, log=lambda _m: None)
    yield url, schema
    import psycopg

    with psycopg.connect(url, autocommit=True, prepare_threshold=None, connect_timeout=10) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.fixture(params=["sqlite", "postgres"])
def any_store(request, cfg: OdinConfig) -> Iterator[StateStore]:
    if request.param == "sqlite":
        s: StateStore = SQLiteStateStore(cfg.paths.db_path)
    else:
        from odin.state.postgres import PostgresStateStore

        url, schema = request.getfixturevalue("pg_schema")
        s = PostgresStateStore(url, schema=schema, migrations_dir=ROOT / "supabase" / "migrations")
        # Test-only reset (raw SQL is otherwise confined to odin/state).
        s._write(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
    yield s
    s.close()


@pytest.fixture
def any_ingested(any_store: StateStore, cfg: OdinConfig) -> StateStore:
    ingest_bundle(any_store, cfg, include_pdfs=False)
    return any_store


# --------------------------------------------------------------------------- LLM helpers


def make_llm(cfg: OdinConfig, responder, **kw) -> tuple[LLMClient, FakeProvider]:
    provider = FakeProvider(responder)
    client = LLMClient(settings=cfg.llm, limits=cfg.limits, cache_dir=cfg.paths.llm_cache_dir, provider=provider,
                       sleep=lambda s: None, **kw)
    return client, provider


def field(field_type: str, key: str, value: dict | None, cites: list[tuple[str, str]], status: str = "extracted",
          confidence: float = 0.9, **extra: Any) -> dict[str, Any]:
    return {"field_type": field_type, "key": key, "status": status, "value": value, "raw_text": "",
            "confidence": confidence, "citations": [{"clause_id": c, "quote": q} for c, q in cites], **extra}


def reply(fields: list[dict[str, Any]], issues: list[dict[str, Any]] | None = None) -> str:
    return json.dumps({"fields": fields, "issues": issues or []})


def amends(key: str, clause: str, quote: str, to_doc: str, target: str, op: str, **extra: Any) -> dict[str, Any]:
    value = {"ref_type": "amends", "from_doc": "A3", "to_doc": to_doc, "target_doc": to_doc, "target_clause": target,
             "operation": op, "new_text": extra.pop("new_text", f"new wording of {target}"), "effective_date": "2027-01-01",
             **extra}
    return field("cross_reference", key, value, [(clause, quote)])


# A3 as a model should read it: one amends row per operation, plus the links its preamble states.
A3_RELATIONS_ONLY_SLA = [
    amends("amends_sla_3_2", "A3:1", "Section 3.2 of the SLA is deleted in its entirety and replaced with the following",
           "QH-STRATO-2026-SLA", "Section 3.2", "replace"),
]
A3_ALL = A3_RELATIONS_ONLY_SLA + [
    amends("amends_sla_3_1", "A3:2", "Section 3.1 of the SLA is deleted in its entirety and replaced with the following",
           "A2", "Section 3.1", "replace"),
    amends("amends_cover_page_b", "A3:3", "Section B of the Cover Page (Contract ID: QH-STRATO-2026-001) is amended",
           "A1", "Section B", "modify", old_value="90 days", new_value="60 days"),
    field("cross_reference", "sla_incorporated_into_agreement",
          {"ref_type": "incorporates", "from_doc": "A1", "to_doc": "A2"},
          [("A3:preamble", "which is\nincorporated by reference into the Cloud Service Agreement")]),
    field("cross_reference", "amendment_controls",
          {"ref_type": "precedence", "controlling_doc": "A3", "subordinate_doc": "A2"},
          [("A3:preamble", "In the event of a conflict between this Amendment and the SLA, this Amendment controls.")]),
]

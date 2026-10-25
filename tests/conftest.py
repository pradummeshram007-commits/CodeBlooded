"""Shared fixtures. No test makes a real LLM call: providers are replaced by FakeProvider."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

import pytest

from odin.config import OdinConfig, load_config
from odin.ingest.loader import ingest_bundle
from odin.llm import LLMClient, ProviderResponse
from odin.state.store import StateStore

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
    c = load_config(env={"ODIN_DB_PATH": str(tmp_path / "odin.db"), "ODIN_OUTPUTS_DIR": str(tmp_path / "out")})
    c.paths.llm_cache_dir = tmp_path / "llm-cache"
    c.limits.backoff_base_s = 0.0
    return c


@pytest.fixture
def store(cfg: OdinConfig) -> StateStore:
    s = StateStore(cfg.paths.db_path)
    yield s
    s.close()


@pytest.fixture
def ingested(store: StateStore, cfg: OdinConfig) -> StateStore:
    ingest_bundle(store, cfg)
    return store


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

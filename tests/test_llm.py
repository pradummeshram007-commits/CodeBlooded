from __future__ import annotations

import pytest
from pydantic import BaseModel

from odin.config import load_config
from odin.llm import (
    BudgetExceeded,
    KeyRejected,
    LLMClient,
    LLMError,
    LLMValidationError,
    OpenAICompatProvider,
    ProviderResponse,
    RetryableError,
    _retry_after,
    llm_config_problem,
)

from .conftest import make_llm


class Answer(BaseModel):
    value: int


def test_identical_calls_hit_the_disk_cache(cfg) -> None:
    llm, provider = make_llm(cfg, lambda s, m: '{"value": 1}')
    assert llm.call_json("q", Answer).value == 1
    assert llm.call_json("q", Answer).value == 1
    assert len(provider.calls) == 1 and llm.stats.cache_hits == 1 and llm.stats.calls == 1


def test_invalid_json_is_reprompted_with_the_error(cfg) -> None:
    replies = iter(["not json at all", '```json\n{"value": "seven"}\n```', '{"value": 7}'])
    llm, provider = make_llm(cfg, lambda s, m: next(replies))
    assert llm.call_json("q", Answer).value == 7
    assert len(provider.calls) == 3
    repair = provider.calls[2][-1]["content"]
    assert "schema validation failed" in repair and "value" in repair
    assert provider.calls[2][-2]["role"] == "assistant"


def test_validation_gives_up_after_the_limit(cfg) -> None:
    cfg.limits.validation_retries = 1
    llm, _ = make_llm(cfg, lambda s, m: "{}")
    with pytest.raises(LLMValidationError):
        llm.call_json("q", Answer)


def test_budget_exceeded_on_call_limit(cfg) -> None:
    cfg.limits.max_llm_calls = 1
    llm, _ = make_llm(cfg, lambda s, m: '{"value": 1}')
    llm.call_json("first", Answer)
    with pytest.raises(BudgetExceeded):
        llm.call_json("second", Answer)
    assert llm.call_json("first", Answer).value == 1   # cached calls stay free


def test_budget_exceeded_on_tokens(cfg) -> None:
    cfg.limits.max_tokens_budget = 100                  # fake provider reports 150 tokens per call
    llm, _ = make_llm(cfg, lambda s, m: '{"value": 1}')
    llm.call_json("first", Answer)
    with pytest.raises(BudgetExceeded):
        llm.call_json("second", Answer)


def test_transient_errors_are_retried_with_backoff(cfg) -> None:
    attempts = {"n": 0}

    def flaky(s, m):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RetryableError("overloaded")
        return '{"value": 3}'

    delays: list[float] = []
    llm, _ = make_llm(cfg, flaky)
    llm.sleep = delays.append
    cfg.limits.backoff_base_s = 1.0
    assert llm.call_json("q", Answer).value == 3
    assert attempts["n"] == 3 and len(delays) == 2 and delays[1] >= delays[0]


def test_rate_limit_waits_as_long_as_the_provider_asks(cfg) -> None:
    attempts = {"n": 0}

    def limited(s, m):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RetryableError("429 Rate limit reached ... Please try again in 7.66s.", _retry_after(
                Exception("Please try again in 7.66s.")))
        return '{"value": 4}'

    delays: list[float] = []
    llm, _ = make_llm(cfg, limited)
    llm.sleep = delays.append
    assert llm.call_json("q", Answer).value == 4
    assert delays and delays[0] >= 7.66


def test_retry_after_parsing() -> None:
    assert _retry_after(Exception("Please try again in 7.66s.")) == 7.66
    assert _retry_after(Exception("try again in 1m2.5s")) == 62.5
    assert _retry_after(Exception("try again in 250ms")) == 0.25
    assert _retry_after(Exception("no hint here")) is None


def test_loki_override_keeps_other_agents_and_their_cache_keys(cfg) -> None:
    gemini = "https://generativelanguage.googleapis.com/v1beta/openai/"
    base = {"LLM_PROVIDER": "openai_compat", "LLM_MODEL": "openai/gpt-oss-20b", "LLM_API_KEY": "groq-key",
            "LLM_BASE_URL": "https://api.groq.com/openai/v1"}
    loki_env = {"LOKI_LLM_PROVIDER": "openai_compat", "LOKI_LLM_BASE_URL": gemini, "LOKI_LLM_MODEL": "gemma-4-31b-it"}
    plain, both = load_config(env=base), load_config(env={**base, **loki_env, "LOKI_LLM_API_KEY": "gemini-key"})
    assert both.llm == plain.llm and both.llm_for("thor") is both.llm and plain.llm_for("norns") is plain.llm
    # On Groq (here through the shared settings) Loki alone gets the free tier's limits.
    groq = plain.llm_for("loki")
    assert (groq.model, groq.api_key, groq.max_output_tokens, groq.reasoning_effort, groq.max_request_tokens,
            groq.tokens_per_minute, groq.max_concurrent, groq.retry_413) == (
        "openai/gpt-oss-20b", "groq-key", 3000, "low", 7000, 7500, 1, False)
    assert (plain.llm.max_output_tokens, plain.llm.tokens_per_minute, plain.llm.retry_413) == (32000, 0, True)
    loki = both.llm_for("loki")
    assert (loki.model, loki.base_url, loki.api_key, loki.request_timeout_s, loki.reasoning_effort, loki.lenient_json,
            loki.requests_per_minute) == ("gemma-4-31b-it", gemini, "gemini-key", 180, "", True, 12)
    # The shared key is never sent to Loki's endpoint.
    assert llm_config_problem(load_config(env={**base, **loki_env}), "loki") == "no API key: set LOKI_LLM_API_KEY"
    # Thor's request settings (part of every cache key) are unchanged; a reasoning effort enters the key only when sent.
    assert OpenAICompatProvider(both.llm).settings_fingerprint() == {"temperature": 0.0, "json_mode": True}
    effort = loki.model_copy(update={"reasoning_effort": "low"})
    assert OpenAICompatProvider(effort).settings_fingerprint()["reasoning_effort"] == "low"

    # The model is in the cache key: a Groq answer is never reused for Gemma. Gemma's fenced reply parses as is.
    groq, _ = make_llm(cfg, lambda s, m: '{"value": 1}')
    groq.provider.model = "openai/gpt-oss-20b"
    gemma, provider = make_llm(cfg, lambda s, m: 'Here it is:\n```json\n{"value": 2}\n```\nNote: {done}')
    gemma.settings, provider.model = loki, "gemma-4-31b-it"
    assert groq.call_json("q", Answer, system="s").value == 1
    assert gemma.call_json("q", Answer, system="s").value == 2
    assert gemma.stats.calls == 1 and gemma.stats.cache_hits == 0 and len(provider.calls) == 1


# --------------------------------------------------------------------------- API-key fallback (same model, other keys)


class KeyProvider:
    """One key's provider: replies in turn from ``script`` (an exception is raised, a string is the reply)."""

    name, model = "fake", "fake-model"

    def __init__(self, *script):
        self.script, self.calls = list(script), 0

    def settings_fingerprint(self) -> dict:
        return {}

    def complete(self, system, messages, max_tokens):
        self.calls += 1
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return ProviderResponse(item, 100, 50, "end_turn", self.model)


def keyed_llm(cfg, *providers):
    first, *rest = providers
    return LLMClient(settings=cfg.llm, limits=cfg.limits, cache_dir=cfg.paths.llm_cache_dir, provider=first,
                     fallback_providers=list(rest))


def test_next_key_takes_over_when_one_is_rate_limited_or_rejected(cfg) -> None:
    limited = KeyProvider(RetryableError("429 rate limit", retry_after=7.0))
    rejected = KeyProvider(KeyRejected("401 invalid api key"))
    works = KeyProvider('{"value": 5}')
    llm = keyed_llm(cfg, limited, rejected, works)
    delays: list[float] = []
    llm.sleep = delays.append
    records: list = []
    llm.on_call = records.append
    assert llm.call_json("q", Answer).value == 5
    assert (limited.calls, rejected.calls, works.calls) == (1, 1, 1) and delays == []      # no waiting
    assert [(r.key_slot, r.key_slots, bool(r.error)) for r in records] == [(1, 3, True), (2, 3, True), (3, 3, False)]
    assert llm.stats.calls == 1 and llm.stats.failures == 2       # failed attempts never reached the model
    assert llm.call_json("another question", Answer).value == 5   # the key that worked is tried first from now on
    assert (limited.calls, rejected.calls, works.calls) == (1, 1, 2)


def test_every_key_exhausted_fails_fast_with_each_reason(cfg) -> None:
    capped = [KeyProvider(RetryableError(f"429 tokens per day, key {n}", retry_after=5000.0)) for n in (1, 2, 3)]
    llm = keyed_llm(cfg, *capped)
    delays: list[float] = []
    llm.sleep = delays.append
    with pytest.raises(LLMError, match="every one of the 3 API keys") as info:
        llm.call_json("q", Answer)
    assert "key 1: provider asks to wait 5000s" in str(info.value) and "key 3:" in str(info.value)
    assert delays == [] and [p.calls for p in capped] == [1, 1, 1]


def test_waits_only_when_every_key_is_resting(cfg) -> None:
    first = KeyProvider(RetryableError("429", retry_after=5.0), '{"value": 6}')
    second = KeyProvider(RetryableError("429", retry_after=9.0), '{"value": 6}')
    llm = keyed_llm(cfg, first, second)
    delays: list[float] = []
    llm.sleep = delays.append
    assert llm.call_json("q", Answer).value == 6
    assert len(delays) == 1 and 5.0 <= delays[0] < 9.0               # the soonest key's wait, not the longest
    assert (first.calls, second.calls) == (2, 1)


def test_numbered_keys_are_read_in_order_and_each_gets_its_own_client() -> None:
    base = {"LLM_PROVIDER": "openai_compat", "LLM_MODEL": "openai/gpt-oss-20b", "LLM_BASE_URL": "https://api.groq.com/openai/v1"}
    cfg = load_config(env={**base, "LLM_API_KEY": "k1", "LLM_API_KEY_2": "k2", "LLM_API_KEY_3": "k3"})
    assert cfg.llm.api_keys() == ["k1", "k2", "k3"] and cfg.llm.api_key == "k1"
    assert load_config(env={**base, "LLM_API_KEYS": "a, b\nc,a"}).llm.api_keys() == ["a", "b", "c"]
    assert "k2" not in repr(cfg.llm)                                   # keys never show up in logs or reprs
    llm = LLMClient.from_config(cfg)
    assert llm.key_count == 3 and [llm._provider(n).client.api_key for n in range(3)] == ["k1", "k2", "k3"]
    assert llm.pool is LLMClient.from_config(cfg).pool                # one pool per model and keys, process-wide
    # Loki's own model has its own keys; the shared ones are never sent to its endpoint.
    loki = load_config(env={**base, "LLM_API_KEY": "k1", "LLM_API_KEY_2": "k2", "LOKI_LLM_PROVIDER": "openai_compat",
                            "LOKI_LLM_MODEL": "gemma-4-31b-it", "LOKI_LLM_BASE_URL": "https://example.test/v1",
                            "LOKI_LLM_API_KEY": "g1", "LOKI_LLM_API_KEY_2": "g2"}).llm_for("loki")
    assert loki.api_keys() == ["g1", "g2"]
    assert llm_config_problem(load_config(env={**base, "LLM_API_KEY": "k1", "LLM_API_KEY_2": "<your-key>"})) == \
        "LLM_API_KEY_2 in .env looks like a placeholder"

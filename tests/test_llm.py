from __future__ import annotations

import pytest
from pydantic import BaseModel

from odin.config import load_config
from odin.llm import (
    BudgetExceeded,
    LLMValidationError,
    OpenAICompatProvider,
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

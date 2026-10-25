from __future__ import annotations

import pytest
from pydantic import BaseModel

from odin.llm import BudgetExceeded, LLMValidationError, RetryableError, _retry_after

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

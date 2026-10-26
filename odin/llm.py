"""LLM wrapper: ``call_json(prompt, schema)`` -> validated pydantic object.

* Provider chosen by config/env: ``anthropic`` (Anthropic SDK) or ``openai_compat``
  (OpenAI SDK pointed at OpenAI, Gemini, Groq, OpenRouter, ... via LLM_BASE_URL).
* Retries API errors with exponential backoff; re-prompts with the validation error when
  the reply is not valid JSON for the schema.
* Key fallback: LLM_API_KEY, LLM_API_KEY_2, LLM_API_KEY_3 (same provider and model, other
  accounts' quota). A key that is rate-limited, out of quota or rejected hands the request to
  the next key at once (``KeyPool``); the call waits only when every key is resting.
* Disk cache keyed by a hash of (provider, model, system, messages, generation settings):
  an identical call is never sent twice, so re-runs are free and reproducible.
* Counts real calls and tokens; raises BudgetExceeded before a call that would pass the limits.
* Per-agent settings: ``LLMClient.from_config(cfg, agent="loki")`` uses Loki's own model when
  LOKI_LLM_* is set (config.py); every other agent uses the shared llm section.

Determinism: temperature=0 is sent wherever the provider accepts it. Current Claude models
reject sampling parameters, so for them reproducibility comes from the cache instead.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, ClassVar, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from odin.config import Limits, LLMSettings, OdinConfig, load_config

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """A call failed and retrying will not help (or retries are exhausted)."""


class RetryableError(LLMError):
    """Transient provider failure (rate limit, overload, 5xx, connection)."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


_RETRY_IN_RE = re.compile(r"(?:try again|retry) in\s+(?:(\d+)m)?\s*([\d.]+)\s*(ms|s)\b", re.I)
_RETRY_DELAY_RE = re.compile(r"retryDelay['\"]?\s*:\s*['\"]([\d.]+)s", re.I)   # Google's RetryInfo detail


def _retry_after(exc: Exception) -> float | None:
    """Seconds to wait, from a Retry-After header, a 'try again in 7.5s' / 'Please retry in 37s' message, or
    Google's retryDelay."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    value = headers.get("retry-after") if hasattr(headers, "get") else None
    if value:
        try:
            return float(value)
        except ValueError:
            pass
    m = _RETRY_IN_RE.search(str(exc))
    if m:
        minutes = float(m.group(1) or 0)
        amount = float(m.group(2)) / (1000.0 if m.group(3).lower() == "ms" else 1.0)
        return minutes * 60 + amount
    m = _RETRY_DELAY_RE.search(str(exc))
    if m:
        return float(m.group(1))
    return None


_WINDOW_RE = re.compile(r"Limit\s+(\d+),\s*Requested\s+(\d+)", re.I)


def _window_wait(exc: Exception) -> float | None:
    """Seconds until a per-minute token window can admit the request (Groq-style 413/429 text)."""
    text = str(exc)
    if "per minute" not in text.lower():
        return None
    m = _WINDOW_RE.search(text)
    if not m:
        return 60.0
    limit, requested = int(m.group(1)), int(m.group(2))
    if requested <= limit:
        return 10.0
    return (requested - limit) / limit * 60.0 + 2.0


def _too_large(status: int, provider: str, exc: Exception) -> LLMError:
    return LLMError(
        f"{provider} status {status}: request is larger than the provider allows per request or per minute; "
        f"lower thor.chunk_max_chars (env ODIN_CHUNK_MAX_CHARS) or use a higher tier. Detail: {exc}"
    )


class LLMRefusal(LLMError):
    pass


class LLMTruncated(LLMError):
    """The reply hit max_tokens; the caller should send less input per call."""


class LLMTooLarge(LLMError):
    """The provider refused the request as too large (413) and settings.retry_413 is off: send less per call."""


class LLMValidationError(LLMError):
    pass


class KeyRejected(LLMError):
    """The provider refused this API key (invalid, no permission, out of credit or quota). Another key for the same
    model may still work, so the client moves on to the next key instead of failing the call."""


# A rate-limit reply that will not clear by waiting: the account's quota or credit is used up. (Not "billing":
# Groq's ordinary per-minute rate-limit message links to its billing page.)
_QUOTA_GONE_RE = re.compile(r"insufficient_quota|exceeded your current quota|credit balance is too low|"
                            r"insufficient (?:credits|balance|funds)", re.I)
# Google says "You exceeded your current quota" for its per-minute limits too (quotaId ...PerMinute...): those
# clear within a minute, so the key only waits; a per-day quota does not clear by waiting.
_PER_MINUTE_RE = re.compile(r"per ?minute", re.I)


def _quota_gone(text: str) -> bool:
    """A rate-limit reply that waiting will not clear: the key's credit or (daily) quota is used up."""
    return bool(_QUOTA_GONE_RE.search(text)) and not _PER_MINUTE_RE.search(text)


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class ProviderResponse:
    text: str
    input_tokens: int
    output_tokens: int
    stop_reason: str            # end_turn | max_tokens | refusal | ...
    model: str


@dataclass
class CallRecord:
    """One completion (real or cached) or failed attempt; handed to the on_call hook."""

    purpose: str
    provider: str
    model: str
    cache_key: str
    cache_hit: bool
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    attempt: int = 0
    stop_reason: str | None = None
    error: str | None = None
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    key_slot: int = 1           # which API key served or failed it (1 = LLM_API_KEY, 2 = LLM_API_KEY_2, ...)
    key_slots: int = 1          # how many keys the model has

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str | None, messages: list[dict[str, str]], max_tokens: int) -> ProviderResponse: ...

    def settings_fingerprint(self) -> dict[str, Any]: ...


# --------------------------------------------------------------------------- providers

# Claude model families that reject temperature/top_p/top_k (400 if sent).
_NO_SAMPLING = re.compile(r"claude-(fable|mythos|opus-4-[78]|opus-5|sonnet-5|haiku-5)")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: LLMSettings):
        import anthropic  # local import: openai_compat users need not install it

        self._anthropic = anthropic
        self.model = settings.model
        self.effort = settings.effort or None
        self.fallbacks = settings.fallbacks
        self.send_temperature = not _NO_SAMPLING.search(self.model)
        self.temperature = settings.temperature
        kwargs: dict[str, Any] = {"max_retries": 0, "timeout": settings.request_timeout_s}
        if settings.api_key:
            kwargs["api_key"] = settings.api_key
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        self.client = anthropic.Anthropic(**kwargs)

    def settings_fingerprint(self) -> dict[str, Any]:
        return {"effort": self.effort, "temperature": self.temperature if self.send_temperature else None}

    def complete(self, system: str | None, messages: list[dict[str, str]], max_tokens: int) -> ProviderResponse:
        a = self._anthropic
        kwargs: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        if system:
            # Static instructions first, cached across chunks and documents.
            kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        if self.send_temperature:
            kwargs["extra_body"] = {"temperature": self.temperature}
        try:
            if self.fallbacks:
                stream_ctx = self.client.beta.messages.stream(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                )
            else:
                stream_ctx = self.client.messages.stream(**kwargs)
            with stream_ctx as stream:
                msg = stream.get_final_message()
        except a.BadRequestError as exc:
            text = str(exc).lower()
            if self.send_temperature and "temperature" in text:
                self.send_temperature = False
                return self.complete(system, messages, max_tokens)
            if self.fallbacks and "fallback" in text:
                self.fallbacks = False
                return self.complete(system, messages, max_tokens)
            if _quota_gone(text):
                raise KeyRejected(f"anthropic: this key is out of credit: {exc}") from exc
            raise LLMError(f"anthropic bad request: {exc}") from exc
        except (a.RateLimitError, a.APIConnectionError, a.InternalServerError) as exc:
            if isinstance(exc, a.RateLimitError) and _quota_gone(str(exc)):
                raise KeyRejected(f"anthropic: this key is out of quota: {exc}") from exc
            raise RetryableError(f"anthropic transient error: {exc}", _retry_after(exc)) from exc
        except a.APIStatusError as exc:
            if exc.status_code in (401, 402, 403):
                raise KeyRejected(f"anthropic status {exc.status_code}: this key was rejected: {exc}") from exc
            if exc.status_code == 413:
                raise _too_large(413, "anthropic", exc) from exc
            if exc.status_code in (408, 409, 429) or exc.status_code >= 500:
                raise RetryableError(f"anthropic status {exc.status_code}: {exc}", _retry_after(exc)) from exc
            raise LLMError(f"anthropic status {exc.status_code}: {exc}") from exc

        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            raise LLMRefusal(f"model declined the request: {details}")
        text = "".join(getattr(b, "text", "") for b in msg.content if b.type == "text")
        usage = msg.usage
        return ProviderResponse(
            text=text,
            input_tokens=(usage.input_tokens or 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0)
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0),
            output_tokens=usage.output_tokens or 0,
            stop_reason=msg.stop_reason or "end_turn",
            model=msg.model,
        )


# A 400 saying the model takes no system message (Gemma on the Gemini API: "Developer instruction is not enabled").
_SYSTEM_REJECTED_RE = re.compile(r"developer instruction|system (?:instruction|message|role|prompt)")


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, settings: LLMSettings):
        import openai

        if not settings.model:
            raise LLMError("LLM_MODEL must be set when LLM_PROVIDER=openai_compat")
        self._openai = openai
        self.model = settings.model
        self.temperature: float | None = settings.temperature
        self.json_mode = settings.json_mode
        self.reasoning_effort: str | None = settings.reasoning_effort or None
        self.system_in_user = settings.system_in_user
        self.retry_413 = settings.retry_413
        self.max_tokens_param = "max_tokens"
        self.client = openai.OpenAI(
            api_key=settings.api_key or "missing-api-key",
            base_url=settings.base_url or None,
            max_retries=0,
            timeout=settings.request_timeout_s,
        )

    def settings_fingerprint(self) -> dict[str, Any]:
        fingerprint: dict[str, Any] = {"temperature": self.temperature, "json_mode": self.json_mode}
        if self.reasoning_effort:  # only when sent, so the keys of calls without it are unchanged
            fingerprint["reasoning_effort"] = self.reasoning_effort
        return fingerprint

    def complete(self, system: str | None, messages: list[dict[str, str]], max_tokens: int) -> ProviderResponse:
        o = self._openai
        if system and self.system_in_user:
            msgs = [{**messages[0], "content": f"{system}\n\n{messages[0]['content']}"}] + messages[1:]
        else:
            msgs = ([{"role": "system", "content": system}] if system else []) + messages
        kwargs: dict[str, Any] = {"model": self.model, "messages": msgs, self.max_tokens_param: max_tokens}
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except o.BadRequestError as exc:
            text = str(exc).lower()
            # Adapt once to provider quirks, then retry the same request.
            if self.reasoning_effort and "reasoning_effort" in text:
                self.reasoning_effort = None
                return self.complete(system, messages, max_tokens)
            if self.json_mode and ("response_format" in text or "json mode" in text):
                self.json_mode = False
                return self.complete(system, messages, max_tokens)
            if self.temperature is not None and "temperature" in text:
                self.temperature = None
                return self.complete(system, messages, max_tokens)
            if self.max_tokens_param == "max_tokens" and "max_completion_tokens" in text:
                self.max_tokens_param = "max_completion_tokens"
                return self.complete(system, messages, max_tokens)
            if self.reasoning_effort and ("reasoning" in text or "thinking" in text):
                self.reasoning_effort = None
                return self.complete(system, messages, max_tokens)
            if system and not self.system_in_user and _SYSTEM_REJECTED_RE.search(text):
                self.system_in_user = True
                return self.complete(system, messages, max_tokens)
            raise LLMError(f"openai_compat bad request: {exc}") from exc
        except (o.RateLimitError, o.APIConnectionError, o.InternalServerError) as exc:
            if isinstance(exc, o.RateLimitError) and _quota_gone(str(exc)):
                raise KeyRejected(f"openai_compat: this key is out of quota: {exc}") from exc
            raise RetryableError(f"openai_compat transient error: {exc}", _retry_after(exc) or _window_wait(exc)) from exc
        except o.APIStatusError as exc:
            if exc.status_code in (401, 402, 403):
                raise KeyRejected(f"openai_compat status {exc.status_code}: this key was rejected: {exc}") from exc
            if exc.status_code == 413:
                if not self.retry_413:
                    raise LLMTooLarge(f"openai_compat 413 request too large: {exc}") from exc
                # Some providers (Groq on-demand) answer 413 when the per-minute token window is
                # full, counting tokens already used this minute: that clears by waiting.
                wait = _window_wait(exc)
                if wait is not None:
                    raise RetryableError(f"openai_compat 413 token window full: {exc}", wait) from exc
                raise _too_large(413, "openai_compat", exc) from exc
            if exc.status_code in (408, 409, 429) or exc.status_code >= 500:
                raise RetryableError(f"openai_compat status {exc.status_code}: {exc}", _retry_after(exc)) from exc
            raise LLMError(f"openai_compat status {exc.status_code}: {exc}") from exc

        if not resp.choices:
            raise RetryableError("openai_compat returned no choices")
        choice = resp.choices[0]
        finish = choice.finish_reason or "stop"
        if finish == "content_filter":
            raise LLMRefusal("provider content filter declined the request")
        usage = resp.usage
        return ProviderResponse(
            text=choice.message.content or "",
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            stop_reason="max_tokens" if finish == "length" else "end_turn",
            model=getattr(resp, "model", self.model) or self.model,
        )


def make_provider(settings: LLMSettings) -> Provider:
    if settings.provider == "anthropic":
        return AnthropicProvider(settings)
    if settings.provider == "openai_compat":
        return OpenAICompatProvider(settings)
    raise LLMError(f"unknown LLM_PROVIDER {settings.provider!r}")


# --------------------------------------------------------------------------- JSON handling

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def extract_json(text: str) -> Any:
    """Parse the JSON object in a reply, tolerating code fences or surrounding prose."""
    t = _FENCE_RE.sub("", text.strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(t[start : end + 1])


_FENCED_RE = re.compile(r"```(?:json)?[ \t]*\n?(.*?)```", re.S | re.I)


def extract_json_lenient(text: str) -> Any:
    """The last ```json block that parses, else the last top-level JSON object in the reply: text before and
    after it (a preamble, notes, reasoning) is ignored. Falls back to ``extract_json`` and its error."""
    for block in reversed(_FENCED_RE.findall(text)):
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    decoder = json.JSONDecoder()
    found: Any = None
    i = text.find("{")
    while i != -1:
        try:
            found, end = decoder.raw_decode(text, i)
            i = text.find("{", end)
        except json.JSONDecodeError:
            i = text.find("{", i + 1)
    return found if found is not None else extract_json(text)


SCHEMA_INSTRUCTION = (
    "\n\nRespond with a single JSON object and nothing else (no prose, no code fences). "
    "It must validate against this JSON Schema:\n{schema}"
)

REPAIR_PROMPT = (
    "Your previous reply could not be used: {error}\n\n"
    "Reply again with the complete corrected JSON object only. Fix exactly these problems; "
    "do not drop valid content and do not invent values to satisfy the schema."
)


def _format_validation_error(exc: Exception, limit: int = 25) -> str:
    if isinstance(exc, ValidationError):
        lines = []
        for err in exc.errors()[:limit]:
            loc = ".".join(str(p) for p in err.get("loc", ()))
            lines.append(f"- {loc}: {err.get('msg')}")
        more = len(exc.errors()) - limit
        if more > 0:
            lines.append(f"- ... and {more} more errors")
        return "schema validation failed:\n" + "\n".join(lines)
    return f"invalid JSON: {exc}"


# --------------------------------------------------------------------------- client

CHARS_PER_TOKEN_ESTIMATE = 4.0   # conservative: Thor's logged gpt-oss calls measured 4.3 characters per token
TOKEN_WINDOW_MARGIN_S = 1.0      # extra wait past the 60 s window, for clock differences with the provider


def estimate_tokens(system: str | None, messages: list[dict[str, str]]) -> int:
    """Input tokens of a request, estimated from its length (for the tokens_per_minute cap)."""
    chars = len(system or "") + sum(len(m.get("content") or "") for m in messages)
    return int(chars / CHARS_PER_TOKEN_ESTIMATE) + 1


KEY_REJECTED_REST_S = 3600.0     # a rejected key (invalid, out of credit or quota) is not tried again for this long


class KeyPool:
    """The API keys of one provider and model, in the order they are tried (LLM_API_KEY, LLM_API_KEY_2, ...).

    A key the provider rate-limits rests for the wait it asks for; a key it rejects, or one that hit a daily cap,
    rests for longer. Meanwhile the next key serves, and the last key that worked is tried first from then on.
    ``KeyPool.shared`` keeps one pool per (provider, base URL, model, keys) in the process, so a key one agent found
    exhausted is skipped by the next agent too. Only key positions are kept here, never the keys themselves.
    """

    _shared: ClassVar[dict[str, "KeyPool"]] = {}
    _shared_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, size: int, clock: Callable[[], float] = time.monotonic):
        self.size = max(1, size)
        self.clock = clock
        self.preferred = 0
        self._until = [0.0] * self.size          # clock time each key may be used again
        self._why: list[str | None] = [None] * self.size
        self._lock = threading.Lock()

    @classmethod
    def shared(cls, settings: LLMSettings) -> "KeyPool":
        keys = settings.api_keys()
        ident = hashlib.sha256(json.dumps([settings.provider, settings.base_url or "", settings.model, keys]).encode())
        with cls._shared_lock:
            return cls._shared.setdefault(ident.hexdigest(), cls(len(keys)))

    def pick(self, tried: set[int], waited: set[int]) -> int | None:
        """The key to try next: the preferred one, then the others in order. Skips the keys already tried in this
        round and keys still resting, except the ones the caller has just waited out."""
        with self._lock:
            now = self.clock()
            for k in range(self.size):
                i = (self.preferred + k) % self.size
                if i not in tried and (i in waited or self._until[i] <= now):
                    return i
            return None

    def rest(self, slot: int, seconds: float, why: str) -> None:
        with self._lock:
            self._until[slot] = max(self._until[slot], self.clock() + max(seconds, 0.0))
            self._why[slot] = why

    def worked(self, slot: int) -> None:
        with self._lock:
            self.preferred, self._until[slot], self._why[slot] = slot, 0.0, None

    def remaining(self) -> list[float]:
        """Seconds until each key may be used again (0 = now)."""
        with self._lock:
            now = self.clock()
            return [max(0.0, u - now) for u in self._until]

    def reasons(self) -> str:
        with self._lock:
            return "; ".join(f"key {i + 1}: {why}" for i, why in enumerate(self._why) if why)


@dataclass
class LLMStats:
    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: int = 0

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMClient:
    settings: LLMSettings
    limits: Limits
    cache_dir: Path | None
    provider: Provider | None = None
    fallback_providers: list[Provider] = field(default_factory=list)   # given providers for keys 2, 3, ... (tests)
    on_call: Callable[[CallRecord], None] | None = None
    sleep: Callable[[float], None] = time.sleep
    stats: LLMStats = field(default_factory=LLMStats)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _sent: deque[float] = field(default_factory=deque, repr=False)      # send times, for requests_per_minute
    _window: list[list[float]] = field(default_factory=list, repr=False)  # [time, tokens] per request, tokens_per_minute
    _rate_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _providers: dict[int, Provider] = field(default_factory=dict, repr=False)   # per key slot (slot 0 is .provider)
    _providers_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _pool: KeyPool | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Providers handed in (tests) bring their own keys: the pool is theirs, not the process-wide one.
        self._given = self.provider is not None

    @classmethod
    def from_config(cls, cfg: OdinConfig, agent: str | None = None, **kwargs: Any) -> "LLMClient":
        """``agent``: use that agent's own LLM settings when it has an override (e.g. LOKI_LLM_*).
        ``kwargs`` may replace any field, e.g. ``limits``."""
        settings = cfg.llm_for(agent) if agent else cfg.llm
        return cls(**{"settings": settings, "limits": cfg.limits, "cache_dir": cfg.paths.llm_cache_dir, **kwargs})

    @property
    def key_count(self) -> int:
        """API keys this client can fall back across (1 when a single key, or none, is set)."""
        if self._given:
            return 1 + len(self.fallback_providers)
        return max(1, len(self.settings.api_keys()))

    @property
    def pool(self) -> KeyPool:
        if self._pool is None:
            self._pool = KeyPool(self.key_count) if self._given else KeyPool.shared(self.settings)
        return self._pool

    def _provider(self, slot: int = 0) -> Provider:
        """The provider that sends requests with key ``slot`` (0 = LLM_API_KEY). Each key gets its own client, with
        the same model and settings."""
        if slot == 0 and self.provider is not None:
            return self.provider
        if slot > 0 and self._given:
            return self.fallback_providers[slot - 1]
        with self._providers_lock:
            if slot == 0 and self.provider is not None:
                return self.provider
            if slot not in self._providers:
                keys = self.settings.api_keys()
                settings = self.settings.model_copy(update={"api_key": keys[slot]}) if keys else self.settings
                self._providers[slot] = make_provider(settings)
            if slot == 0:
                self.provider = self._providers[0]
            return self._providers[slot]

    @property
    def model(self) -> str:
        return self.provider.model if self.provider is not None else self.settings.model

    # ---------------------------------------------------------------- cache

    def _cache_key(self, system: str | None, messages: list[dict[str, str]], max_tokens: int) -> str:
        p = self._provider()
        payload = {
            "provider": p.name,
            "model": p.model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
            "settings": p.settings_fingerprint(),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def _cache_path(self, key: str) -> Path | None:
        return self.cache_dir / key[:2] / f"{key}.json" if self.cache_dir else None

    def _cache_get(self, key: str) -> ProviderResponse | None:
        path = self._cache_path(key)
        if path is None or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ProviderResponse(**data["response"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _cache_put(self, key: str, resp: ProviderResponse, purpose: str) -> None:
        path = self._cache_path(key)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"purpose": purpose, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "response": resp.__dict__}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    # ---------------------------------------------------------------- calls

    def _check_budget(self) -> None:
        if self.stats.calls >= self.limits.max_llm_calls:
            raise BudgetExceeded(f"max_llm_calls={self.limits.max_llm_calls} reached")
        if self.stats.tokens >= self.limits.max_tokens_budget:
            raise BudgetExceeded(f"max_tokens_budget={self.limits.max_tokens_budget} reached ({self.stats.tokens} used)")

    def _emit(self, rec: CallRecord) -> None:
        if self.on_call is not None:
            self.on_call(rec)

    def _throttle(self, system: str | None, messages: list[dict[str, str]], max_tokens: int) -> list[float] | None:
        """Client-side caps, threads waiting in turn: at most settings.requests_per_minute requests, and at most
        settings.tokens_per_minute tokens (estimated input + max_tokens), in any 60 s. Returns the request's
        token-window entry, which ``complete`` raises to the real usage when the reply arrives."""
        rpm, tpm = self.settings.requests_per_minute, self.settings.tokens_per_minute
        if rpm <= 0 and tpm <= 0:
            return None
        with self._rate_lock:
            now = time.monotonic()
            if rpm > 0:
                while self._sent and now - self._sent[0] >= 60.0:
                    self._sent.popleft()
                if len(self._sent) >= rpm:
                    now = max(now, self._sent.popleft() + 60.0)
            entry = None
            if tpm > 0:
                need = estimate_tokens(system, messages) + max_tokens
                window = sorted(e for e in self._window if now - e[0] < 60.0)
                used = sum(e[1] for e in window)
                while window and used + need > tpm:   # wait until enough of the oldest requests leave the window
                    t, n = window.pop(0)
                    used -= n
                    now = max(now, t + 60.0 + TOKEN_WINDOW_MARGIN_S)
                entry = [now, float(need)]
                self._window = window + [entry]
            wait = now - time.monotonic()
            if wait > 0:
                self.sleep(wait)
            if rpm > 0:
                self._sent.append(now)
            return entry

    def complete(
        self, system: str | None, messages: list[dict[str, str]], *, purpose: str = "", max_tokens: int | None = None
    ) -> ProviderResponse:
        """One completion with cache, budget and retry/backoff.

        With several API keys (LLM_API_KEY, LLM_API_KEY_2, ...) a key that is rate-limited, out of quota or rejected
        hands the request straight to the next key; the call only waits when every key is resting, and fails when
        every key is rejected or exhausted. A single key behaves as before: retries with backoff, honouring the wait
        the provider asks for up to rate_limit_max_wait_s."""
        max_tokens = max_tokens or self.settings.max_output_tokens
        provider = self._provider()
        key = self._cache_key(system, messages, max_tokens)   # the request, whichever key serves it
        cached = self._cache_get(key)
        if cached is not None:
            with self._lock:
                self.stats.cache_hits += 1
            self._emit(CallRecord(purpose, provider.name, provider.model, key, True, cached.input_tokens,
                                  cached.output_tokens, 0, 0, cached.stop_reason))
            return cached

        pool, slots = self.pool, self.key_count
        last_exc: Exception | None = None
        waited: set[int] = set()        # keys the last sleep waited out (usable again whatever the clock says)
        for attempt in range(self.limits.max_retries + 1):
            tried: set[int] = set()
            while (slot := pool.pick(tried, waited)) is not None:
                tried.add(slot)
                waited.discard(slot)
                provider = self._provider(slot)
                with self._lock:  # check and reserve atomically: workers share one budget
                    self._check_budget()
                    self.stats.calls += 1
                window_entry = self._throttle(system, messages, max_tokens)
                t0 = time.monotonic()
                try:
                    resp = provider.complete(system, messages, max_tokens)
                except (RetryableError, KeyRejected) as exc:
                    last_exc = exc
                    with self._lock:
                        # The request never reached the model (rate limit, overload, rejected key): give the slot
                        # back. Waits per call stay bounded by max_retries.
                        self.stats.calls -= 1
                        self.stats.failures += 1
                    self._emit(CallRecord(purpose, provider.name, provider.model, key, False,
                                          duration_ms=int((time.monotonic() - t0) * 1000), attempt=attempt,
                                          error=str(exc), key_slot=slot + 1, key_slots=slots))
                    if isinstance(exc, KeyRejected):
                        pool.rest(slot, KEY_REJECTED_REST_S, str(exc))
                    elif exc.retry_after and exc.retry_after > self.limits.rate_limit_max_wait_s:
                        pool.rest(slot, exc.retry_after, f"provider asks to wait {exc.retry_after:.0f}s (over "
                                  f"rate_limit_max_wait_s={self.limits.rate_limit_max_wait_s:.0f}); likely a daily "
                                  f"cap: {exc}")
                    else:
                        pool.rest(slot, exc.retry_after or 0.0, str(exc))
                    continue
                except LLMError as exc:
                    with self._lock:
                        self.stats.failures += 1
                    self._emit(CallRecord(purpose, provider.name, provider.model, key, False,
                                          duration_ms=int((time.monotonic() - t0) * 1000), attempt=attempt,
                                          error=str(exc), key_slot=slot + 1, key_slots=slots))
                    raise
                with self._lock:
                    self.stats.input_tokens += resp.input_tokens
                    self.stats.output_tokens += resp.output_tokens
                if window_entry is not None:
                    with self._rate_lock:
                        window_entry[0] = max(window_entry[0], time.monotonic())
                        window_entry[1] = max(window_entry[1], float(resp.input_tokens + resp.output_tokens))
                pool.worked(slot)
                self._emit(CallRecord(purpose, provider.name, resp.model, key, False, resp.input_tokens,
                                      resp.output_tokens, int((time.monotonic() - t0) * 1000), attempt, resp.stop_reason,
                                      key_slot=slot + 1, key_slots=slots))
                self._cache_put(key, resp, purpose)
                return resp

            # No key can be tried right now: every key is resting, or failed in this round.
            remaining = pool.remaining()
            soonest = min(remaining)
            if soonest > self.limits.rate_limit_max_wait_s:
                prefix = f"every one of the {slots} API keys is rejected or exhausted: " if slots > 1 else ""
                raise LLMError(prefix + (pool.reasons() or str(last_exc))) from last_exc
            if attempt >= self.limits.max_retries:
                break
            delay = min(self.limits.backoff_base_s * (2 ** attempt), self.limits.backoff_max_s)
            if soonest > 0:  # the provider said how long to wait (e.g. a per-minute token window)
                delay = max(delay, soonest + 0.5)
            waited = {i for i, r in enumerate(remaining) if r <= delay}
            self.sleep(delay + random.uniform(0, min(delay / 4, 5.0)))
        raise LLMError(f"giving up after {self.limits.max_retries + 1} attempts: {last_exc}")

    def call_json(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        purpose: str = "",
        include_schema: bool = True,
        max_tokens: int | None = None,
    ) -> T:
        """Send ``prompt`` and return the reply validated as ``schema``.

        Invalid JSON or schema violations are sent back to the model with the error text,
        up to ``limits.validation_retries`` times.
        """
        content = prompt
        if include_schema:
            content += SCHEMA_INSTRUCTION.format(schema=json.dumps(schema.model_json_schema(), separators=(",", ":")))
        messages: list[dict[str, str]] = [{"role": "user", "content": content}]
        parse = extract_json_lenient if self.settings.lenient_json else extract_json
        last_error = ""
        for round_ in range(self.limits.validation_retries + 1):
            resp = self.complete(system, messages, purpose=f"{purpose}#v{round_}" if round_ else purpose, max_tokens=max_tokens)
            if resp.stop_reason == "max_tokens":
                raise LLMTruncated(f"reply truncated at max_tokens ({purpose})")
            try:
                return schema.model_validate(parse(resp.text))
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = _format_validation_error(exc)
                messages = messages + [
                    {"role": "assistant", "content": resp.text},
                    {"role": "user", "content": REPAIR_PROMPT.format(error=last_error)},
                ]
        raise LLMValidationError(f"reply still invalid after {self.limits.validation_retries} re-prompts: {last_error}")


_default_client: LLMClient | None = None


def call_json(prompt: str, schema: type[T], **kwargs: Any) -> T:
    """Module-level convenience using a client built from config.yaml / .env."""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient.from_config(load_config())
    return _default_client.call_json(prompt, schema, **kwargs)


PLACEHOLDER_MARKS = ("<", "your-", "changeme", "xxxx", "replace-me")


def llm_config_problem(cfg: OdinConfig, agent: str | None = None) -> str | None:
    """Catch unfilled .env templates before any API call is attempted (None = looks usable).

    ``agent``: check the settings that agent uses (its own <AGENT>_LLM_* override, when set).
    """
    own = cfg.agent_llm.get(agent) if agent else None
    llm, var = (own, f"{agent.upper()}_LLM_") if own and agent else (cfg.llm, "LLM_")
    model, key = llm.model or "", llm.api_key or ""
    if not model:
        return f"{var}MODEL is empty (required for provider {llm.provider})"
    if any(m in model.lower() for m in PLACEHOLDER_MARKS):
        return f"{var}MODEL looks like a placeholder: {model!r}"
    if llm.provider == "openai_compat" and not key:
        return f"no API key: set {var}API_KEY" + ("" if own else " (or OPENAI_API_KEY)")
    if key and any(key.lower().startswith(m) for m in PLACEHOLDER_MARKS):
        return "the API key in .env looks like a placeholder"
    for n, extra in enumerate(llm.fallback_api_keys, start=2):
        if any(extra.lower().startswith(m) for m in PLACEHOLDER_MARKS):
            return f"{var}API_KEY_{n} in .env looks like a placeholder"
    return None


def llm_unavailable(cfg: OdinConfig, agent: str | None = None) -> str | None:
    """Why ``agent`` cannot call its LLM from the server or the orchestrator (None = it can): an unfilled .env, or no
    API key at all (the scripts may still use an SDK login; a server run never does)."""
    problem = llm_config_problem(cfg, agent)
    settings = cfg.llm_for(agent) if agent else cfg.llm
    if problem is None and not settings.api_keys():
        var = f"{agent.upper()}_LLM_API_KEY" if agent and agent in cfg.agent_llm else "LLM_API_KEY"
        problem = f"no API key set ({var} in .env)"
    return problem

"""Configuration and limits.

Precedence (lowest to highest): built-in defaults < config.yaml < environment / .env.
Every agent reads limits from here so loops and LLM spend are bounded in one place.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]

# Default model per provider. openai_compat has no default: the base URL decides
# which models exist, so LLM_MODEL must be set explicitly.
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"


class LLMSettings(BaseModel):
    provider: Literal["anthropic", "openai_compat"] = "anthropic"
    model: str = ""
    base_url: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    temperature: float = 0.0
    # Anthropic only: output_config.effort. Empty string = don't send it.
    effort: str = "high"
    # Anthropic only: server-side refusal fallback (`fallbacks: "default"`).
    fallbacks: bool = True
    # openai_compat only: ask for response_format={"type": "json_object"}.
    json_mode: bool = True
    # openai_compat only: reasoning_effort for reasoning models (e.g. "low"); dropped if the provider rejects it.
    reasoning_effort: str | None = None
    max_output_tokens: int = 32000
    request_timeout_s: float = 600.0
    # openai_compat only: reasoning_effort sent with each request ("" = not sent). Dropped for the rest of
    # the process when the endpoint rejects it.
    reasoning_effort: str = ""
    # openai_compat only: the system text opens the first user message instead of a system message. Also
    # switched on for the rest of the process when the endpoint rejects a system message.
    system_in_user: bool = False
    # The JSON is taken out of ```json fences and any text before or after it before validation.
    lenient_json: bool = False
    requests_per_minute: int = 0       # client-side cap on requests sent (0 = none)
    tokens_per_minute: int = 0         # client-side cap on estimated input + max_tokens per rolling minute (0 = none)
    max_request_tokens: int = 0        # estimated input + max_tokens per request; callers split to fit (0 = none)
    max_concurrent: int = 0            # requests in flight at once (0 = no limit, 1 = one after another)
    retry_413: bool = True             # False: a 413 (request too large) is raised at once, for the caller to split


class Limits(BaseModel):
    max_llm_calls: int = 60            # real (non-cached) API calls per process
    max_tokens_budget: int = 1_500_000  # input+output tokens per process
    max_retries: int = 4               # API-error retries per call (with backoff)
    backoff_base_s: float = 2.0
    backoff_max_s: float = 60.0
    rate_limit_max_wait_s: float = 240.0  # longest wait honoured when a provider says "retry in N s"
    validation_retries: int = 2        # re-prompts when the JSON fails validation


class LoopLimits(BaseModel):
    """Bounds for the agents built after Thor. Defined now so they share one config."""

    loki_max_rounds: int = 3
    loki_max_clarifications_per_doc: int = 5
    max_message_hops: int = 6          # request -> response chains between agents
    heimdall_max_events_per_drop: int = 100
    norns_max_iterations: int = 500
    tyr_max_rulings_per_run: int = 25


class ThorSettings(BaseModel):
    chunk_max_chars: int = 9000        # above this, split by top-level section (fits low per-minute token limits)
    min_split_chars: int = 1500        # don't split a truncated chunk below this
    std_doc_id: str = "STD"            # extracted first, once, as its own document
    recall_check: bool = True          # re-extract clauses whose figures no extraction captures (code check)
    recall_max_reextracts_per_doc: int = 8


class NornsSettings(BaseModel):
    """Timeline agent. All date and money logic is deterministic; the LLM only normalises due-rule
    text Thor's fields leave open, and writes the short worst-case summary."""

    contracts: list[str] = ["A1", "B1"]   # root contracts; each brings its family (SLA, amendments, STD, ...)
    horizon_months: int = 12              # instances run to this many months after the last checkpoint
    projection_months: int = 12           # worst case: how far past as_of the "no action" scenario runs
    due_soon_days: int = 7                # "due now" window
    writeup_min_words: int = 150
    writeup_max_words: int = 250


class LokiSettings(BaseModel):
    """Adversarial review agent. Reads Thor's output only; the LLM finds, code checks every finding."""

    max_findings_per_doc: int = 8
    max_input_tokens: int = 100_000       # per call (estimated); only a larger document is split by top-level section
    chars_per_token: float = 4.0          # estimate for that split; Thor's logged calls measured 4.3 (gpt-oss-20b)
    context_tokens: int = 600             # company/context.txt is trimmed to about this
    max_llm_calls: int = 8                # real API calls per run_loki.py process (cache hits are free)
    # Loki's own model, used only when LOKI_LLM_* is set: these fields update the llm section for Loki.
    llm: dict[str, Any] = {}
    # Further updates when Loki's base URL is on that host, e.g. api.groq.com: the free tier's limits.
    llm_for_host: dict[str, dict[str, Any]] = {}


class HeimdallSettings(BaseModel):
    """Event monitoring. Code maps what it can; the LLM sees only the events code cannot map or classify."""

    # A drop is released at this clock checkpoint (format_spec: drop 1 = initial analysis, drop 2 = mid-cycle).
    drop_release_checkpoints: dict[str, int] = {"drop1": 1, "drop2": 2}
    llm_batch_size: int = 10              # events per LLM call
    max_llm_calls: int = 4                # real API calls per run_heimdall.py process (cache hits are free)
    max_tokens: int = 3000                # output tokens per call, reasoning included
    max_request_tokens: int = 7000        # estimated input + max_tokens per call (Groq free tier)
    tokens_per_minute: int = 7500         # rolling 60 s budget across calls (input + output)
    reasoning_effort: str | None = "low"  # openai_compat reasoning models; dropped if the provider rejects it
    chars_per_token: float = 4.0          # input estimate (Thor's logged gpt-oss calls measured 4.3)
    event_body_chars: int = 900           # event text shown to the LLM
    task_window_days: int = 60            # tasks: overdue, due or upcoming within this many days
    due_soon_days: int = 7                # alert "high"
    due_month_days: int = 30              # alert "medium"; a renewal-notice deadline this close is "high"


class StateSettings(BaseModel):
    """Where shared state and uploaded files live. sqlite = local file; supabase = Postgres + Storage."""

    backend: Literal["sqlite", "supabase"] = "sqlite"
    db_url: str | None = Field(default=None, repr=False)          # SUPABASE_DB_URL (session pooler)
    supabase_url: str | None = None                               # SUPABASE_URL (https://<ref>.supabase.co)
    secret_key: str | None = Field(default=None, repr=False)      # SUPABASE_SECRET_KEY, server-side only
    bucket: str = "contracts"
    signed_url_ttl_s: int = 3600
    connect_timeout_s: int = 10
    retries: int = 3                   # attempts after the first, per Supabase call
    retry_backoff_s: float = 1.0       # doubles per attempt


class UploadSettings(BaseModel):
    max_upload_mb: float = 20.0
    allowed_extensions: tuple[str, ...] = (".pdf", ".txt")
    # Below this text similarity a PDF attached to a .txt of the same name is flagged as a possible mismatch.
    min_pair_similarity: float = 0.85

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)


class Paths(BaseModel):
    bundle_dir: Path = ROOT / "02_Ragnarok Odin The Contract War Room" / "Pack" / "odin_dev_pack" / "bundle"
    db_path: Path = ROOT / "state" / "odin.db"
    files_dir: Path = ROOT / "state" / "files"   # file store when STATE_BACKEND=sqlite
    outputs_dir: Path = ROOT / "outputs"
    llm_cache_dir: Path = ROOT / ".cache" / "llm"
    prompts_dir: Path = ROOT / "prompts"
    migrations_dir: Path = ROOT / "supabase" / "migrations"

    @property
    def pack_dir(self) -> Path:
        return self.bundle_dir.parent


class OdinConfig(BaseModel):
    llm: LLMSettings = LLMSettings()
    agent_llm: dict[str, LLMSettings] = {}   # per-agent override (loki: LOKI_LLM_*); every other agent uses llm
    limits: Limits = Limits()
    loops: LoopLimits = LoopLimits()
    thor: ThorSettings = ThorSettings()
    norns: NornsSettings = NornsSettings()
    loki: LokiSettings = LokiSettings()
    heimdall: HeimdallSettings = HeimdallSettings()
    state: StateSettings = StateSettings()
    upload: UploadSettings = UploadSettings()
    paths: Paths = Paths()

    def llm_for(self, agent: str) -> LLMSettings:
        """The agent's own LLM settings when it has an override, else the shared llm section."""
        return self.agent_llm.get(agent, self.llm)


# Agents that may use their own model: <AGENT>_LLM_PROVIDER / _BASE_URL / _MODEL / _API_KEY in .env.
AGENT_LLM_OVERRIDES = ("loki",)
_AGENT_LLM_ENV = (("PROVIDER", "provider"), ("BASE_URL", "base_url"), ("MODEL", "model"), ("API_KEY", "api_key"))

_URL_UNSAFE_IN_PASSWORD = set("@/?#[] %")


def normalize_db_url(url: str) -> str:
    """Percent-encode a password that contains URL delimiters ('@', '/', ...).

    Supabase shows the connection string with the raw password; libpq splits user info at
    the first '@', so a password like ``abc@123`` would otherwise be read as host ``123@...``.
    """
    url = url.strip().strip('"').strip("'")
    m = re.match(r"^(postgres(?:ql)?://)(.*)$", url)
    if not m or "@" not in m.group(2):
        return url
    scheme, rest = m.groups()
    at = rest.rfind("@")
    userinfo, hostpart = rest[:at], rest[at + 1:]
    if ":" not in userinfo:
        return url
    user, password = userinfo.split(":", 1)
    if any(c in _URL_UNSAFE_IN_PASSWORD for c in password):
        password = quote(password, safe="")
    return f"{scheme}{user}:{password}@{hostpart}"


def db_url_summary(url: str | None) -> str:
    """host:port/db of a connection URL, with no credentials (safe to print)."""
    if not url:
        return "(SUPABASE_DB_URL not set)"
    try:
        parts = urlsplit(normalize_db_url(url))
        return f"{parts.hostname}:{parts.port or 5432}/{parts.path.lstrip('/') or 'postgres'}"
    except ValueError:
        return "(unparseable SUPABASE_DB_URL)"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _resolve_path(value: Any) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def _env_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config(path: str | Path | None = None, *, env: dict[str, str] | None = None) -> OdinConfig:
    """Build the config from defaults, config.yaml and the environment."""
    if env is None:
        load_dotenv(ROOT / ".env", override=False)
        env = dict(os.environ)

    data: dict[str, Any] = OdinConfig().model_dump()
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    if cfg_path.exists():
        loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        data = _deep_merge(data, loaded)

    llm = data["llm"]
    env_map = {
        "LLM_PROVIDER": "provider",
        "LLM_MODEL": "model",
        "LLM_BASE_URL": "base_url",
        "LLM_EFFORT": "effort",
    }
    for env_key, field in env_map.items():
        if env.get(env_key) is not None:
            llm[field] = env[env_key]
    if env.get("LLM_FALLBACKS") is not None:
        llm["fallbacks"] = _env_bool(env["LLM_FALLBACKS"])
    if env.get("LLM_JSON_MODE") is not None:
        llm["json_mode"] = _env_bool(env["LLM_JSON_MODE"])
    if env.get("LLM_MAX_OUTPUT_TOKENS"):
        llm["max_output_tokens"] = int(env["LLM_MAX_OUTPUT_TOKENS"])
    # Key lookup: an explicit LLM_API_KEY (alias ODIN_LLM_API_KEY) wins; otherwise the provider's usual variable.
    explicit_key = env.get("LLM_API_KEY") or env.get("ODIN_LLM_API_KEY")
    if explicit_key:
        llm["api_key"] = explicit_key
    elif llm.get("provider") == "anthropic" and env.get("ANTHROPIC_API_KEY"):
        llm["api_key"] = env["ANTHROPIC_API_KEY"]
    elif llm.get("provider") == "openai_compat" and env.get("OPENAI_API_KEY"):
        llm["api_key"] = env["OPENAI_API_KEY"]
    if not llm.get("model") and llm.get("provider") == "anthropic":
        llm["model"] = DEFAULT_ANTHROPIC_MODEL

    # Per-agent override: when any <AGENT>_LLM_* variable is set, that agent uses the llm section updated with
    # <agent>.llm from config.yaml and those variables. Base URL, model and key are never inherited, so the
    # shared key is never sent to the agent's endpoint. Then <agent>.llm_for_host[<base URL host>], if any.
    for agent in AGENT_LLM_OVERRIDES:
        section = data[agent]
        own = {field: env[f"{agent.upper()}_LLM_{key}"] for key, field in _AGENT_LLM_ENV
               if env.get(f"{agent.upper()}_LLM_{key}")}
        settings = ({**llm, "base_url": None, "model": "", "api_key": None, **(section.get("llm") or {}), **own}
                    if own else dict(llm))
        host = urlsplit(settings.get("base_url") or "").hostname or ""
        for_host = (section.get("llm_for_host") or {}).get(host)
        if own or for_host:
            data["agent_llm"][agent] = {**settings, **(for_host or {})}

    for env_key, field in (("ODIN_MAX_LLM_CALLS", "max_llm_calls"), ("ODIN_MAX_TOKENS_BUDGET", "max_tokens_budget")):
        if env.get(env_key):
            data["limits"][field] = int(env[env_key])
    if env.get("ODIN_CHUNK_MAX_CHARS"):
        data["thor"]["chunk_max_chars"] = int(env["ODIN_CHUNK_MAX_CHARS"])

    state = data["state"]
    if env.get("STATE_BACKEND"):
        state["backend"] = env["STATE_BACKEND"].strip().strip('"').lower()
    for env_key, field in (("SUPABASE_DB_URL", "db_url"), ("SUPABASE_URL", "supabase_url"),
                           ("SUPABASE_SECRET_KEY", "secret_key"), ("SUPABASE_BUCKET", "bucket")):
        if env.get(env_key):
            state[field] = env[env_key].strip().strip('"').strip("'")
    if state.get("db_url"):
        state["db_url"] = normalize_db_url(state["db_url"])
    if env.get("ODIN_MAX_UPLOAD_MB"):
        data["upload"]["max_upload_mb"] = float(env["ODIN_MAX_UPLOAD_MB"])

    paths = data["paths"]
    for env_key, field in (("ODIN_BUNDLE_DIR", "bundle_dir"), ("ODIN_DB_PATH", "db_path"), ("ODIN_OUTPUTS_DIR", "outputs_dir"),
                           ("ODIN_FILES_DIR", "files_dir")):
        if env.get(env_key):
            paths[field] = env[env_key]
    for field in list(paths):
        paths[field] = _resolve_path(paths[field])

    return OdinConfig.model_validate(data)

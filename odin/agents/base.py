"""Agent base class shared by Thor and the agents that follow it.

An agent has a name, its own prompt files under prompts/, and logs every action, LLM
call and state transition to the ``trace`` table under one run id.
"""
from __future__ import annotations

import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Iterator, TypeVar

from pydantic import BaseModel

from odin.config import OdinConfig
from odin.llm import CallRecord, LLMClient
from odin.state.models import TraceEntry
from odin.state.store import StateStore

T = TypeVar("T", bound=BaseModel)

SYSTEM_MARK = "=== SYSTEM ==="
USER_MARK = "=== USER ==="


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    system: str
    user: str

    def render(self, **values: Any) -> str:
        """Fill ``{{placeholders}}`` in the user part (double braces keep JSON examples literal)."""
        out = self.user
        for key, value in values.items():
            out = out.replace("{{" + key + "}}", str(value))
        return out


def load_prompt(path: Path) -> PromptTemplate:
    """A prompt file holds a cached system part and a user template, split by markers."""
    raw = path.read_text(encoding="utf-8")
    if SYSTEM_MARK in raw and USER_MARK in raw:
        system = raw.split(SYSTEM_MARK, 1)[1].split(USER_MARK, 1)[0].strip()
        user = raw.split(USER_MARK, 1)[1].strip()
    else:
        system, user = "", raw.strip()
    return PromptTemplate(path.stem, system, user)


class Agent:
    name: ClassVar[str] = "agent"
    prompt_files: ClassVar[dict[str, str]] = {}

    def __init__(self, store: StateStore, llm: LLMClient | None, cfg: OdinConfig, run_id: str | None = None):
        self.store = store
        self.llm = llm
        self.cfg = cfg
        self.run_id = run_id or f"{self.name}-{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self._prompts: dict[str, PromptTemplate] = {}
        self._llm_ref: str | None = None  # input_ref attached to LLM-call trace rows
        # SQLite connections are single-threaded: LLM calls made from worker threads are
        # buffered here and written to the trace by the main thread (flush_llm_log).
        self._main_thread = threading.get_ident()
        self._pending_llm_log: list[CallRecord] = []
        self._pending_lock = threading.Lock()
        if llm is not None:
            llm.on_call = self._on_llm_call

    # ------------------------------------------------------------------ prompts

    def prompt(self, key: str) -> PromptTemplate:
        if key not in self._prompts:
            self._prompts[key] = load_prompt(self.cfg.paths.prompts_dir / self.prompt_files[key])
        return self._prompts[key]

    # ------------------------------------------------------------------ trace

    def log(
        self,
        action: str,
        input_ref: str | None = None,
        output_ref: str | None = None,
        *,
        tokens: int = 0,
        duration_ms: int = 0,
        error: str | None = None,
        ts: str | None = None,
        **meta: Any,
    ) -> None:
        entry = TraceEntry(run_id=self.run_id, agent=self.name, action=action, input_ref=input_ref,
                           output_ref=output_ref, tokens=tokens, duration_ms=duration_ms, error=error, meta=meta)
        if ts:
            entry.ts = ts  # when the event happened (LLM calls from worker threads are written later)
        self.store.log_trace(entry)

    def transition(self, entity: str, old: str | None, new: str, reason: str | None = None) -> None:
        self.log("state_transition", entity, new, previous=old, reason=reason)

    @contextmanager
    def step(self, action: str, input_ref: str | None = None) -> Iterator[dict[str, Any]]:
        """Time a step and log it (with the error, if it raises). Yields a dict for output metadata."""
        info: dict[str, Any] = {}
        t0 = time.monotonic()
        try:
            yield info
        except BaseException as exc:
            self.log(action, input_ref, info.pop("output_ref", None), duration_ms=int((time.monotonic() - t0) * 1000),
                     error=f"{type(exc).__name__}: {exc}", **info)
            raise
        self.log(action, input_ref, info.pop("output_ref", None), duration_ms=int((time.monotonic() - t0) * 1000), **info)

    def _on_llm_call(self, rec: CallRecord) -> None:
        if threading.get_ident() != self._main_thread:
            with self._pending_lock:
                self._pending_llm_log.append(rec)
            return
        self._write_llm_log(rec)

    def flush_llm_log(self) -> None:
        with self._pending_lock:
            pending, self._pending_llm_log = self._pending_llm_log, []
        for rec in pending:
            self._write_llm_log(rec)

    def _write_llm_log(self, rec: CallRecord) -> None:
        self.log(
            "llm_call",
            rec.purpose or self._llm_ref,
            rec.cache_key,
            tokens=rec.tokens,
            duration_ms=rec.duration_ms,
            error=rec.error,
            ts=rec.ts,
            cache_hit=rec.cache_hit,
            model=rec.model,
            provider=rec.provider,
            attempt=rec.attempt,
            stop_reason=rec.stop_reason,
            input_tokens=rec.input_tokens,
            output_tokens=rec.output_tokens,
        )

    # ------------------------------------------------------------------ LLM

    def call_json(self, template: PromptTemplate, schema: type[T], *, purpose: str, system: str | None = None,
                  **values: Any) -> T:
        """Render ``template`` and call the LLM. ``system`` overrides the template's system part."""
        if self.llm is None:
            raise RuntimeError(f"{self.name} was constructed without an LLM client")
        return self.llm.call_json(template.render(**values), schema, system=system or template.system or None,
                                  purpose=purpose)

    def run(self, **kwargs: Any) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

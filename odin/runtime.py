"""One shared (config, state store, file store) per process, for callers that don't pass their own."""
from __future__ import annotations

import threading
from dataclasses import dataclass

from odin.config import OdinConfig, load_config
from odin.state.backend import open_file_store, open_store
from odin.state.files import FileStore
from odin.state.store import StateStore


@dataclass
class Runtime:
    cfg: OdinConfig
    store: StateStore
    files: FileStore

    def describe(self) -> str:
        return f"state: {self.store.describe()}; files: {self.files.describe()}"


_runtime: Runtime | None = None
_lock = threading.Lock()


def get_runtime(cfg: OdinConfig | None = None) -> Runtime:
    """The process-wide runtime, opened on first use from ``cfg`` (default: config.yaml + .env)."""
    global _runtime
    with _lock:
        if _runtime is None:
            cfg = cfg or load_config()
            _runtime = Runtime(cfg, open_store(cfg), open_file_store(cfg))
        return _runtime


def reset_runtime() -> None:
    global _runtime
    with _lock:
        if _runtime is not None:
            _runtime.store.close()
        _runtime = None

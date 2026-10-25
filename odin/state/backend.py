"""Pick the state store and file store from STATE_BACKEND (sqlite | supabase)."""
from __future__ import annotations

from odin.config import OdinConfig
from odin.state.errors import SQLITE_HINT, StoreError
from odin.state.files import FileStore, LocalFileStore, SupabaseFileStore
from odin.state.store import SQLiteStateStore, StateStore


def open_store(cfg: OdinConfig) -> StateStore:
    """The configured StateStore. Raises StoreUnavailable / StoreError with a fix-it message."""
    if cfg.state.backend == "sqlite":
        return SQLiteStateStore(cfg.paths.db_path)
    if cfg.state.backend == "supabase":
        from odin.state.postgres import PostgresStateStore

        if not cfg.state.db_url:
            raise StoreError(f"STATE_BACKEND=supabase but SUPABASE_DB_URL is not set. {SQLITE_HINT}")
        return PostgresStateStore(
            cfg.state.db_url,
            connect_timeout_s=cfg.state.connect_timeout_s,
            retries=cfg.state.retries,
            backoff_s=cfg.state.retry_backoff_s,
            migrations_dir=cfg.paths.migrations_dir,
        )
    raise StoreError(f"unknown STATE_BACKEND={cfg.state.backend!r} (use sqlite or supabase)")


def open_file_store(cfg: OdinConfig) -> FileStore:
    if cfg.state.backend == "supabase":
        secret_key = (cfg.state.secret_key or "").strip()
        # Supabase API keys are JWT tokens (format: eyJ...)
        if secret_key and secret_key.startswith("eyJ") and cfg.state.supabase_url:
            try:
                store = SupabaseFileStore(
                    cfg.state.supabase_url, secret_key, cfg.state.bucket,
                    retries=1, backoff_s=0.5,
                    file_size_limit=cfg.upload.max_upload_bytes,
                )
                store.ensure_bucket()
                return store
            except Exception:
                pass
    return LocalFileStore(cfg.paths.files_dir, cfg.state.bucket)


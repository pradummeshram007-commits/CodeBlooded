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
        return SupabaseFileStore(
            cfg.state.supabase_url or "", cfg.state.secret_key or "", cfg.state.bucket,
            retries=cfg.state.retries, backoff_s=cfg.state.retry_backoff_s,
            file_size_limit=cfg.upload.max_upload_bytes,
        )
    return LocalFileStore(cfg.paths.files_dir, cfg.state.bucket)

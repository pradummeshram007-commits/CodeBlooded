"""Apply supabase/migrations/NNN_name.sql in order, once each, recorded in schema_migrations.

Each migration runs in its own transaction together with its schema_migrations row, so a
failing file leaves nothing behind. A session advisory lock stops two migrators racing.
Re-running is safe: applied versions are skipped (and a changed checksum is reported).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from odin.state.errors import StoreUnavailable
from odin.state.postgres import MIGRATION_FILE_RE, PostgresStateStore

LOCK_KEY = 0x0D1D_2A2A  # pg_advisory_lock key for odin migrations

SCHEMA_MIGRATIONS_DDL = """
create table if not exists schema_migrations (
    version    text primary key,
    name       text not null,
    checksum   text not null,
    applied_at timestamptz not null default now()
)
"""


@dataclass
class MigrationResult:
    version: str
    name: str
    status: str            # applied | skipped | changed (already applied, file edited since)


def migration_files(migrations_dir: Path) -> list[tuple[str, Path]]:
    out = [(m.group(1), p) for p in sorted(Path(migrations_dir).glob("*.sql")) if (m := MIGRATION_FILE_RE.match(p.name))]
    versions = [v for v, _ in out]
    dupes = {v for v in versions if versions.count(v) > 1}
    if dupes:
        raise ValueError(f"duplicate migration version(s): {sorted(dupes)}")
    return out


def apply_migrations(db_url: str, migrations_dir: Path, *, schema: str | None = None, retries: int = 3,
                     log: Callable[[str], None] = print) -> list[MigrationResult]:
    import psycopg
    from psycopg import sql as pgsql

    files = migration_files(migrations_dir)
    # Reuse the store's connection handling (retries, redacted errors, SQLite hint); schema not checked yet.
    store = PostgresStateStore(db_url, schema=None, retries=retries)
    results: list[MigrationResult] = []
    try:
        conn = store._run(lambda c: c)
        if schema:
            conn.execute(pgsql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(pgsql.Identifier(schema)))
            conn.execute(pgsql.SQL("SET search_path TO {}").format(pgsql.Identifier(schema)))
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            conn.execute(SCHEMA_MIGRATIONS_DDL)
            applied = {r["version"]: r["checksum"] for r in conn.execute("SELECT version, checksum FROM schema_migrations")}
            for version, path in files:
                body = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(body.encode("utf-8")).hexdigest()
                if version in applied:
                    status = "skipped" if applied[version] == checksum else "changed"
                    if status == "changed":
                        log(f"  {path.name}: already applied, but the file changed since (not re-run; add a new migration)")
                    results.append(MigrationResult(version, path.name, status))
                    continue
                with conn.transaction():
                    conn.execute(body)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                        (version, path.name, checksum),
                    )
                log(f"  {path.name}: applied")
                results.append(MigrationResult(version, path.name, "applied"))
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
        raise StoreUnavailable(store._message(exc, "migration rolled back")) from exc
    finally:
        store.close()
    return results

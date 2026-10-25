"""Supabase Postgres backend for the StateStore interface (psycopg 3).

* Connects to SUPABASE_DB_URL (the session pooler, port 5432) with autocommit; multi-row
  writes run in ``transaction()`` (BEGIN ... COMMIT), so a failure rolls the whole unit back.
* Every call is retried on connection errors with exponential backoff and a fresh
  connection. A connection lost *inside* a transaction is not retried piecemeal: the
  transaction is rolled back and StoreUnavailable is raised, so nothing is half-written.
* After the retries, StoreUnavailable tells the user to fall back to STATE_BACKEND=sqlite.
* Passwords never appear in messages (see ``errors.redact``).
"""
from __future__ import annotations

import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence, TypeVar

from odin.config import db_url_summary
from odin.state.errors import SQLITE_HINT, StoreError, StoreUnavailable, redact, secrets_of
from odin.state.store import StateStore

T = TypeVar("T")
MIGRATION_FILE_RE = re.compile(r"^(\d{3,})_[\w-]+\.sql$")


def _psycopg():
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise StoreError(f"psycopg is not installed (pip install -r requirements.txt). {SQLITE_HINT}") from exc
    return psycopg


def migration_versions(migrations_dir: Path) -> list[str]:
    return sorted(m.group(1) for p in Path(migrations_dir).glob("*.sql") if (m := MIGRATION_FILE_RE.match(p.name)))


class PostgresStateStore(StateStore):
    backend = "supabase"
    json_native = True

    def __init__(
        self,
        db_url: str,
        *,
        schema: str | None = None,
        connect_timeout_s: int = 10,
        retries: int = 3,
        backoff_s: float = 1.0,
        migrations_dir: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        super().__init__()
        if not db_url:
            raise StoreError(f"STATE_BACKEND=supabase but SUPABASE_DB_URL is not set. {SQLITE_HINT}")
        self._url = db_url
        self._secrets = secrets_of(db_url)
        self.schema = schema
        self.connect_timeout_s = connect_timeout_s
        self.retries = retries
        self.backoff_s = backoff_s
        self._sleep = sleep
        self._conn: Any = None
        self._run(lambda conn: None)          # connect now: fail fast with a clear message
        if migrations_dir is not None:
            self.check_schema(migrations_dir)

    def describe(self) -> str:
        return f"supabase postgres ({db_url_summary(self._url)}{', schema ' + self.schema if self.schema else ''})"

    # ------------------------------------------------------------------ connection + retries

    def _connect(self) -> Any:
        psycopg = _psycopg()
        from psycopg import sql as pgsql
        from psycopg.rows import dict_row

        conn = psycopg.connect(
            self._url,
            connect_timeout=self.connect_timeout_s,
            autocommit=True,
            prepare_threshold=None,           # no server-side prepared statements: safe behind any pooler mode
            row_factory=dict_row,
            application_name="odin",
        )
        if self.schema:
            conn.execute(pgsql.SQL("SET search_path TO {}").format(pgsql.Identifier(self.schema)))
        return conn

    def _drop(self) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:  # noqa: BLE001 - already broken
            pass
        self._conn = None

    def _message(self, exc: BaseException, extra: str = "") -> str:
        detail = redact(f"{type(exc).__name__}: {exc}".strip(), self._secrets)
        detail = " ".join(detail.split())[:300]
        return (f"Supabase Postgres is unreachable at {db_url_summary(self._url)} after {self.retries + 1} attempt(s)"
                f"{' (' + extra + ')' if extra else ''}: {detail}. Check SUPABASE_DB_URL and your network. {SQLITE_HINT}")

    def _run(self, fn: Callable[[Any], T]) -> T:
        psycopg = _psycopg()
        transient = (psycopg.OperationalError, psycopg.InterfaceError)
        attempts = 1 if self._depth else self.retries + 1
        delay = self.backoff_s
        last: BaseException | None = None
        for attempt in range(attempts):
            with self._lock:
                try:
                    if self._conn is None or self._conn.closed:
                        self._conn = self._connect()
                    return fn(self._conn)
                except transient as exc:
                    last = exc
                    self._drop()
                    if self._depth:
                        raise StoreUnavailable(self._message(exc, "connection lost mid-transaction; it was rolled back")) from exc
            if attempt + 1 < attempts:
                self._sleep(delay)
                delay *= 2
        assert last is not None
        raise StoreUnavailable(self._message(last)) from last

    @contextmanager
    def transaction(self) -> Iterator[StateStore]:
        psycopg = _psycopg()
        with self._lock:
            if self._depth:
                self._depth += 1
                try:
                    yield self
                finally:
                    self._depth -= 1
                return
            conn = self._run(lambda c: c)
            self._depth = 1
            try:
                with conn.transaction():
                    yield self
            except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
                self._drop()
                raise StoreUnavailable(self._message(exc, "the transaction was rolled back; nothing was written")) from exc
            finally:
                self._depth = 0

    # ------------------------------------------------------------------ plumbing

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("%", "%%").replace("?", "%s")

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        q = self._sql(sql)
        return self._run(lambda c: c.execute(q, tuple(params)).fetchall())

    def _write(self, sql: str, params: Sequence[Any] = ()) -> int:
        q = self._sql(sql)
        return self._run(lambda c: c.execute(q, tuple(params)).rowcount)

    def _write_many(self, sql: str, seq: list[tuple[Any, ...]]) -> int:
        q = self._sql(sql)

        def go(c: Any) -> int:
            with c.cursor() as cur:
                cur.executemany(q, seq)
                return cur.rowcount

        if self._depth:
            return self._run(go)
        with self.transaction():               # all rows or none
            return self._run(go)

    def _insert_id(self, sql: str, params: Sequence[Any]) -> int | None:
        q = self._sql(sql) + " RETURNING id"

        def go(c: Any) -> int | None:
            row = c.execute(q, tuple(params)).fetchone()
            return int(row["id"]) if row else None

        return self._run(go)

    def close(self) -> None:
        with self._lock:
            self._drop()

    # ------------------------------------------------------------------ schema

    def applied_migrations(self) -> list[str]:
        psycopg = _psycopg()
        try:
            return [r["version"] for r in self._query("SELECT version FROM schema_migrations ORDER BY version")]
        except psycopg.errors.UndefinedTable:
            return []

    def check_schema(self, migrations_dir: Path) -> None:
        missing = sorted(set(migration_versions(migrations_dir)) - set(self.applied_migrations()))
        if missing:
            raise StoreError(
                f"Supabase schema is not up to date: migration(s) {', '.join(missing)} not applied. "
                f"Run: python scripts/db_migrate.py"
            )

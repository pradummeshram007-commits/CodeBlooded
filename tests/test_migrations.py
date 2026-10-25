"""The Postgres migrations and the SQLite schema must describe the same tables and columns."""
from __future__ import annotations

import re

from odin.config import ROOT
from odin.state.migrate import migration_files
from odin.state.store import SQLITE_SCHEMA, TABLES

TABLE_RE = re.compile(r"create table if not exists (\w+)\s*\((.*?)\n\);", re.I | re.S)
CONSTRAINT_WORDS = {"primary", "unique", "foreign", "check", "constraint"}


def _tables(sql: str) -> dict[str, set[str]]:
    sql = re.sub(r"--[^\n]*", "", sql)
    out: dict[str, set[str]] = {}
    for name, body in TABLE_RE.findall(sql):
        cols = set()
        for line in body.split("\n"):
            word = line.strip().split(" ", 1)[0].strip(",").lower()
            if word and word not in CONSTRAINT_WORDS:
                cols.add(word)
        out[name.lower()] = cols
    return out


def test_migrations_are_numbered_and_ordered() -> None:
    files = migration_files(ROOT / "supabase" / "migrations")
    assert files and files[0][0] == "001" and files[0][1].name == "001_init.sql"
    assert [v for v, _ in files] == sorted(v for v, _ in files)


def test_postgres_and_sqlite_schemas_match() -> None:
    pg: dict[str, set[str]] = {}
    for _, path in migration_files(ROOT / "supabase" / "migrations"):
        pg.update(_tables(path.read_text(encoding="utf-8")))
    lite = _tables(SQLITE_SCHEMA)
    assert set(pg) == set(lite), set(pg) ^ set(lite)
    for table in lite:
        assert pg[table] == lite[table], (table, pg[table] ^ lite[table])
    assert set(TABLES) <= set(lite)
    assert {"storage_path", "original_filename", "mime_type", "text_source", "parse_status", "uploaded_at",
            "text"} <= pg["documents"]


def test_every_postgres_table_has_row_level_security() -> None:
    sql = (ROOT / "supabase" / "migrations" / "001_init.sql").read_text(encoding="utf-8")
    rls = set(re.findall(r"alter table (\w+)\s+enable row level security", sql, re.I))
    assert rls == set(_tables(sql))

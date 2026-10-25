"""Apply supabase/migrations/*.sql to the Supabase Postgres in SUPABASE_DB_URL, in order.

    python scripts/db_migrate.py            # apply pending migrations (safe to re-run)
    python scripts/db_migrate.py --status   # list applied / pending, change nothing

Applied versions are recorded in schema_migrations; each migration runs in one transaction.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from odin.config import db_url_summary, load_config  # noqa: E402
from odin.state.errors import SQLITE_HINT, StoreError  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="show applied and pending migrations only")
    ap.add_argument("--config", help="path to config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if not cfg.state.db_url:
        print(f"error: SUPABASE_DB_URL is not set in .env. {SQLITE_HINT}")
        return 2
    print(f"Database: {db_url_summary(cfg.state.db_url)}")
    print(f"Migrations: {cfg.paths.migrations_dir}")
    try:
        if args.status:
            from odin.state.migrate import migration_files
            from odin.state.postgres import PostgresStateStore

            store = PostgresStateStore(cfg.state.db_url, retries=cfg.state.retries)
            applied = set(store.applied_migrations())
            store.close()
            for version, path in migration_files(cfg.paths.migrations_dir):
                print(f"  {path.name}: {'applied' if version in applied else 'PENDING'}")
            return 0
        from odin.state.migrate import apply_migrations

        results = apply_migrations(cfg.state.db_url, cfg.paths.migrations_dir, retries=cfg.state.retries)
    except StoreError as exc:
        print(f"error: {exc}")
        return 3
    applied = [r for r in results if r.status == "applied"]
    for r in results:
        if r.status != "applied":
            print(f"  {r.name}: {'already applied' if r.status == 'skipped' else 'already applied (file changed since!)'}")
    print(f"Done: {len(applied)} applied, {len(results) - len(applied)} already up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

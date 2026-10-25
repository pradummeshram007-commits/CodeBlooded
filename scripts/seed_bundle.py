"""Seed the dev-pack bundle into the configured backend (STATE_BACKEND=supabase | sqlite).

    python scripts/seed_bundle.py

* 8 contracts, each a .txt + .pdf pair -> ONE document (.txt = text source, .pdf = viewable
  original), both files in the private "contracts" bucket at {doc_id}/{sha256}/{filename}
* company/context.txt -> resources (full text) + Storage
* payments_ledger.csv -> ledger_entries, holidays.csv -> holidays, clock.json -> clock_checkpoints
* events/*.jsonl -> Storage only (not processed: Heimdall reads them drop by drop)

Idempotent: unchanged files (same sha256) are neither re-uploaded nor re-segmented.
No LLM calls: run scripts/run_thor.py afterwards.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from odin.config import load_config  # noqa: E402
from odin.ingest.bundle import ingest_bundle  # noqa: E402
from odin.state.backend import open_file_store, open_store  # noqa: E402
from odin.state.errors import StoreError  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-pdfs", action="store_true", help="skip the .pdf originals")
    ap.add_argument("--config", help="path to config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    try:
        store = open_store(cfg)
        files = open_file_store(cfg)
        print(f"State: {store.describe()}\nFiles: {files.describe()}\nBundle: {cfg.paths.bundle_dir}\n")
        created = files.ensure_bucket()
        if created:
            print(f"Created private bucket {files.bucket!r}")
        report = ingest_bundle(store, cfg, files, include_pdfs=not args.no_pdfs)
    except StoreError as exc:
        print(f"error: {exc}")
        return 3

    for u in report.uploads:
        extra = f" similarity={u.similarity:.3f}" if u.similarity is not None else ""
        print(f"  {u.filename:<10} {u.outcome:<9} {u.doc_id:<4} {u.parse_status or '':<11} {u.storage_path or ''}{extra}")
        for w in u.warnings:
            print(f"      warning: {w}")
    print(f"\nResources registered/refreshed: {', '.join(report.resources) or '(none, unchanged)'}")
    print("Rows inserted this run: " + (", ".join(f"{k}={v}" for k, v in report.tables.items()) or "(none)"))
    print("\nRow counts:")
    for table, n in store.row_counts().items():
        print(f"  {table:<18} {n:>6}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

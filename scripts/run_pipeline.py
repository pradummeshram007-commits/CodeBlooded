"""Run Odin's pipeline for one document: THOR -> NORNS -> LOKI -> HEIMDALL, then print every stage.

    python scripts/run_pipeline.py --doc D1                     # on the simulated clock's date
    python scripts/run_pipeline.py --doc D1 --checkpoint 1
    python scripts/run_pipeline.py --doc A3 --as-of 2027-06-01 --force-thor
    python scripts/run_pipeline.py --doc D1 --no-loki --no-heimdall-llm   # fewest LLM calls

The web app runs the same pipeline after every upload (and from the ODIN page). THOR is skipped when the
document's text is unchanged and already extracted; LOKI reviews the document (an amendment: the contracts it
amends); HEIMDALL processes released drops not yet processed on the date and re-maps events that name the
document's contract but were mapped before it was uploaded or re-extracted. LLM calls are capped per run by odin.max_llm_calls (config.yaml), and every agent falls
back across LLM_API_KEY, LLM_API_KEY_2, LLM_API_KEY_3. Writes pipeline_runs, the trace and
outputs/odin/<run_id>.json. Exit code 0 when the run is complete, 1 when partial or failed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from odin.agents.loki import as_of_label  # noqa: E402
from odin.agents.odin import Odin  # noqa: E402
from odin.config import load_config  # noqa: E402
from odin.ingest.loader import load_clock  # noqa: E402
from odin.state.backend import open_file_store, open_store  # noqa: E402
from odin.state.errors import StoreError  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", required=True, help="document id (e.g. D1)")
    when = ap.add_mutually_exclusive_group()
    when.add_argument("--checkpoint", type=int, help="0 = start date, 1.. = clock.json checkpoints")
    when.add_argument("--as-of", type=as_of_label, help="YYYY-MM-DD (default: the simulated clock's date)")
    ap.add_argument("--force-thor", action="store_true", help="extract again even if the text is unchanged")
    ap.add_argument("--no-loki", action="store_true", help="skip LOKI's review (saves its LLM call)")
    ap.add_argument("--no-heimdall-llm", action="store_true", help="HEIMDALL maps events by code only")
    ap.add_argument("--config", help="path to config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    try:
        store = open_store(cfg)
        files = open_file_store(cfg)
    except StoreError as exc:
        print(f"error: {exc}")
        return 3
    as_of = args.as_of
    if args.checkpoint is not None:
        points = store.list_checkpoints() or load_clock(cfg.paths.pack_dir / "clock.json")
        match = next((p for p in points if p.idx == args.checkpoint), None)
        if match is None:
            print(f"error: checkpoint {args.checkpoint} does not exist")
            return 2
        as_of = match.date

    def show(run) -> None:
        stage = next((s for s in run.stages if s.name == run.current_stage), None)
        if stage is not None and stage.status == "running":
            print(f"  … {stage.name.upper()} running", flush=True)

    odin = Odin(store, cfg, files=files, on_update=show)
    options = {"force_thor": args.force_thor, "run_loki": not args.no_loki, "heimdall_use_llm": not args.no_heimdall_llm}
    try:
        run = odin.new_run(args.doc, as_of=as_of, options=options)
    except LookupError as exc:
        print(f"error: {exc}")
        return 2
    print(f"State: {store.describe()}")
    print(f"Odin run {run.run_id}: {run.doc_id} as of {run.as_of}; at most {cfg.odin.max_llm_calls} LLM calls; "
          f"{len(cfg.llm.api_keys()) or 'no'} API key(s) for {cfg.llm.provider} {cfg.llm.model or ''}".rstrip())
    run = odin.execute(run)

    print()
    for s in run.stages:
        print(f"{s.name.upper():9} {s.status:15} {f'{s.seconds}s' if s.seconds is not None else '-':>7}  {s.summary or ''}")
        if s.reason:
            print(f"{'':9} reason: {s.reason}")
        if s.llm_calls or s.cache_hits:
            print(f"{'':9} LLM: {s.llm_calls} call(s), {s.cache_hits} cached, {s.tokens:,} tokens")
    print(f"\nPipeline {run.status}" + (f": {run.reason}" if run.reason else ""))
    print(f"Plan: root {run.plan.get('root')}, followed {', '.join(run.plan.get('followed') or [])}, "
          f"LOKI reviews {', '.join(run.plan.get('loki_docs') or []) or 'nothing'}, HEIMDALL "
          + (", ".join(f"{a['action']} {a['drop']}" for a in run.plan.get("heimdall") or []) or "reassess only"))
    u = run.llm
    print(f"LLM: {u['llm_calls']} calls, {u['cache_hits']} cache hits, {u['tokens']:,} tokens, "
          f"{u['failed_attempts']} failed attempts")
    print(f"Wrote {cfg.paths.outputs_dir / 'odin' / (run.run_id + '.json')}")
    return 0 if run.status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())

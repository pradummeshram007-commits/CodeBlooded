"""Run Heimdall on one released event drop, as of a checkpoint or a date.

    python scripts/run_heimdall.py --drop 1 --checkpoint 1
    python scripts/run_heimdall.py --drop 2 --as-of 2027-06-01
    python scripts/run_heimdall.py --drop 1 --checkpoint 1 --no-llm      # code mapping only

A drop is processed only once it is released (heimdall.drop_release_checkpoints in
config.yaml) and only its events dated on or before the clock date. Code maps what it can;
the rest goes to the LLM in batches (at most heimdall.max_llm_calls real calls per process,
within the Groq limits in config.yaml). Writes heimdall_events / heimdall_alerts /
heimdall_tasks, the trace and outputs/heimdall/<drop>_<as_of>.json. The Streamlit page
(app/pages/2_Heimdall.py) shows the board; it never calls the LLM.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from odin.agents.heimdall import SEVERITY_RANK, TASK_STATUSES, Heimdall, heimdall_llm  # noqa: E402
from odin.agents.loki import as_of_label  # noqa: E402
from odin.config import load_config  # noqa: E402
from odin.llm import llm_config_problem  # noqa: E402
from odin.state.backend import open_file_store, open_store  # noqa: E402
from odin.state.errors import StoreError  # noqa: E402


def table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    fmt = lambda r: "  ".join(str(v).ljust(w) for v, w in zip(r, widths))  # noqa: E731
    return "\n".join([fmt(headers), "  ".join("-" * w for w in widths)] + [fmt(r) for r in rows])


def fact_text(fact: dict | None) -> str:
    if not fact:
        return "-"
    f = dict(fact)
    kind = f.pop("type")
    keep = {k: v for k, v in f.items() if k not in ("source", "event_id", "contract", "date") and v not in (None, "")}
    return f"{kind} {f.get('contract') or ''} {f.get('date') or ''} " + " ".join(f"{k}={v}" for k, v in keep.items())


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drop", required=True, help="drop number (1, 2) or name (drop1)")
    when = ap.add_mutually_exclusive_group(required=True)
    when.add_argument("--checkpoint", type=int, help="0 = start date, 1.. = clock.json checkpoints")
    when.add_argument("--as-of", type=as_of_label, help="YYYY-MM-DD")
    ap.add_argument("--no-llm", action="store_true", help="code mapping only; events code cannot map stay unmapped")
    ap.add_argument("--config", help="path to config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    drop_name = args.drop if args.drop.startswith("drop") else f"drop{args.drop}"
    llm = None
    if not args.no_llm:
        problem = llm_config_problem(cfg)
        if problem:
            print(f"error: {problem}\nFix .env (see .env.example), or run with --no-llm.")
            return 2
        llm = heimdall_llm(cfg)
    try:
        store = open_store(cfg)
        files = open_file_store(cfg)
    except StoreError as exc:
        print(f"error: {exc}")
        return 3
    heimdall = Heimdall(store, llm, cfg, files=files)
    try:
        as_of = args.as_of or heimdall.checkpoint(args.checkpoint)
        h = cfg.heimdall
        print(f"State: {store.describe()}")
        print(f"Heimdall run {heimdall.run_id}: {drop_name} as of {as_of}; "
              + (f"provider={cfg.llm.provider} model={cfg.llm.model}, at most {llm.limits.max_llm_calls} LLM calls, "
                 f"max_tokens {h.max_tokens}, input + max_tokens <= {h.max_request_tokens}, <= {h.tokens_per_minute} "
                 f"tokens/min, reasoning_effort={h.reasoning_effort}" if llm else "no LLM (code mapping only)"))
        result = heimdall.run(drop_name, as_of)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}")
        return 2
    path = heimdall.write_output(result)

    c = result.counts()
    print(f"\nEvents ({result.source}): {c['total']} visible = {c['mapped_by_code']} mapped by code + "
          f"{c['mapped_by_llm']} mapped by LLM + {c['noise']} noise + {c['unmapped']} unmapped + "
          f"{c['unparseable']} unparseable; {c['not_yet_visible']} dated after {as_of} (not yet visible)")

    rows = [[e.event_id or f"line {e.line_no}", e.status, e.mapped_by or "-", ", ".join(e.doc_ids) or "-",
             ", ".join(e.clause_ids) or "-", fact_text(e.fact), e.exposure.get("delta", "-")] for e in result.events]
    print()
    print(table(rows, ["event", "status", "by", "contracts", "clauses", "fact", "exposure delta"]))
    for e in result.events:
        why = e.noise_reason or e.status_reason or e.breach_reason
        if why:
            print(f"  {e.event_id or e.line_no}: {why}")

    live = result.live
    print(f"\nWorst case on {as_of}: {live.baseline} without facts -> {live.after_events} with the events' facts "
          f"(live with user facts: {live.live})")
    for contract, v in live.by_contract.items():
        print(f"  {contract}: {v['after_events']}")

    sev = Counter(a.severity for a in live.alerts)
    print("\nAlerts: " + ", ".join(f"{s} {sev.get(s, 0)}" for s in sorted(SEVERITY_RANK, key=lambda s: -SEVERITY_RANK[s])))
    for a in live.alerts:
        print(f"  [{a.severity}] {a.message}  ({a.clause_id or '-'})")

    cols = Counter(t.status for t in live.tasks)
    print("\nTask board: " + ", ".join(f"{s} {cols.get(s, 0)}" for s in TASK_STATUSES))
    u = result.llm
    print(f"\nLLM: {u['llm_calls']} calls, {u['cache_hits']} cache hits, {u['input_tokens'] + u['output_tokens']:,} tokens "
          f"({u['input_tokens']:,} in / {u['output_tokens']:,} out), {u['failed_attempts']} failed attempts, "
          f"{u['rate_wait_s']} s waited for the per-minute budget")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

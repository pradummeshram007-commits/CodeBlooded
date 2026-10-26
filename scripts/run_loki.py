"""Run Loki (adversarial review) on named documents, as of a checkpoint or a date.

    python scripts/run_loki.py --docs A1,A2 --checkpoint 1
    python scripts/run_loki.py --docs B1 --as-of 2027-06-01

--docs is required: there is no "all documents" default. Amendments and standard terms
are not reviewed on their own (their text is reviewed inside the documents they amend or
that incorporate them). Loki uses its own model when LOKI_LLM_* is set in .env, else the
shared LLM_* settings. One call per document; --parallel N (default 4) runs documents at
the same time. On Groq (loki.llm_for_host) parts are smaller, calls run one after another
and wait to stay within the per-minute token limit. Real LLM calls per process are capped
by loki.max_llm_calls (config.yaml, default 8); cache hits are free. Reads Thor's output and Norns' exposure_items; writes
loki_findings, Loki's workstream status, the trace and outputs/loki/<doc_id>_<as_of>.json.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from odin.agents.loki import Loki, as_of_label  # noqa: E402
from odin.config import load_config  # noqa: E402
from odin.llm import LLMClient, llm_config_problem  # noqa: E402
from odin.state.backend import open_store  # noqa: E402
from odin.state.errors import StoreError  # noqa: E402


def table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    fmt = lambda r: "  ".join(str(v).ljust(w) for v, w in zip(r, widths))  # noqa: E731
    return "\n".join([fmt(headers), "  ".join("-" * w for w in widths)] + [fmt(r) for r in rows])


def impact_text(impact) -> str:
    if impact == "unquantified":
        return "unquantified"
    amount = f"${impact.amount:,.2f}" if impact.amount is not None else "no amount"
    return f"#{impact.exposure_item_id} {impact.category} {amount}"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", required=True, help="comma-separated doc ids to review (required)")
    when = ap.add_mutually_exclusive_group(required=True)
    when.add_argument("--checkpoint", type=int, help="0 = start date, 1.. = clock.json checkpoints")
    when.add_argument("--as-of", type=as_of_label, help="YYYY-MM-DD")
    ap.add_argument("--parallel", type=int, default=4, help="documents reviewed at the same time (default 4)")
    ap.add_argument("--config", help="path to config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    settings = cfg.llm_for("loki")
    docs = [d.strip() for d in args.docs.split(",") if d.strip()]
    if not docs:
        print("error: --docs names no document")
        return 2
    if args.parallel < 1:
        print("error: --parallel must be at least 1")
        return 2
    problem = llm_config_problem(cfg, "loki")
    if problem:
        print(f"error: {problem}\nFix .env (see .env.example).")
        return 2
    if settings.provider == "anthropic" and not (settings.api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("warning: no ANTHROPIC_API_KEY / LLM_API_KEY set; the SDK will try an `ant auth login` profile.")
    try:
        store = open_store(cfg)
    except StoreError as exc:
        print(f"error: {exc}")
        return 3

    limits = cfg.limits.model_copy(update={"max_llm_calls": min(cfg.limits.max_llm_calls, cfg.loki.max_llm_calls)})
    llm = LLMClient.from_config(cfg, agent="loki", limits=limits)
    loki = Loki(store, llm, cfg)
    try:
        as_of = args.as_of or loki.checkpoint(args.checkpoint)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    print(f"State: {store.describe()}")
    rate = "".join([f", at most {settings.requests_per_minute} requests/minute" if settings.requests_per_minute else "",
                    f", at most {settings.tokens_per_minute:,} tokens/minute" if settings.tokens_per_minute else "",
                    f", input + max_tokens <= {settings.max_request_tokens:,} per call" if settings.max_request_tokens else ""])
    print(f"Loki run {loki.run_id}: as_of {as_of}, provider={settings.provider} model={settings.model} "
          f"(max_tokens {settings.max_output_tokens:,}, reasoning_effort {settings.reasoning_effort or 'not sent'}), "
          f"at most {limits.max_llm_calls} LLM calls / {limits.max_tokens_budget:,} tokens, "
          f"{min(loki.workers(args.parallel), len(docs))} document(s) at a time{rate}")

    t0 = time.monotonic()
    reviews = loki.run(docs, as_of, parallel=args.parallel)
    elapsed = time.monotonic() - t0

    rows = []
    for r in reviews:
        u = r.usage()
        rows.append([r.doc_id, str(len(r.parts)), str(len(r.accepted)), str(len(r.rejected)), str(u.get("llm_calls", 0)),
                     str(u.get("cache_hits", 0)), f"{u.get('input_tokens', 0) + u.get('output_tokens', 0):,}",
                     f"{r.seconds:.1f}", f"{r.llm_seconds:.1f}", r.status])
    print()
    print(table(rows, ["doc", "parts", "accepted", "rejected", "LLM calls", "cached", "tokens", "seconds", "LLM s",
                       "status"]))
    for r in reviews:
        if r.reason:
            print(f"  {r.doc_id}: {r.reason}")
        if r.context:
            amended = [c.clause_id for c in r.context.clauses if c.note and c.note.startswith("amendment text")]
            print(f"  {r.doc_id}: amendment text in force: {', '.join(amended) or 'none'}; Standard Terms: "
                  f"{r.context.std_mode or 'none'}; parts (estimated input tokens): "
                  f"{', '.join(f'{p.label}={p.est_tokens}' for p in r.context.parts)}")
            for note in r.context.notes:
                print(f"    note: {note}")

    for r in reviews:
        if not r.findings:
            continue
        print(f"\n== {r.doc_id} as of {r.as_of}: accepted findings (most severe first)")
        acc = [[f.type or "-", f.title, ", ".join(sorted({c.clause_id for c in f.citations if c.clause_id})),
                f.severity or "-", f.likelihood or "-", impact_text(f.impact)] for f in r.accepted]
        print(table(acc, ["type", "title", "cited clauses", "severity", "likelihood", "impact"]) if acc else "(none)")
        if r.rejected:
            print(f"\n== {r.doc_id}: rejected findings")
            for f in r.rejected:
                print(f"- [{f.type or '?'}] {f.title or '(no title)'}: {f.rejection_reason}")

    s = llm.stats
    print(f"\nTotals: {s.calls} API calls, {s.cache_hits} cache hits, {s.tokens:,} tokens "
          f"({s.input_tokens:,} in / {s.output_tokens:,} out), {s.failures} failed attempts, {elapsed:.1f} s wall clock")
    for r in reviews:
        if r.output_path:
            print(f"Wrote {r.output_path}")
    return 0 if all(r.status in ("complete", "skipped") for r in reviews) else 1


if __name__ == "__main__":
    raise SystemExit(main())

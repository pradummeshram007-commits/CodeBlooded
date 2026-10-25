"""Ingest the bundle and run Thor on every contract document.

    python scripts/run_thor.py                 # ingest + extract (skips unchanged, complete docs)
    python scripts/run_thor.py --docs A1,A3    # only these documents
    python scripts/run_thor.py --force         # re-extract even if unchanged (LLM cache still applies)
    python scripts/run_thor.py --no-llm        # ingest + segment only, no API calls
    python scripts/run_thor.py --details       # also print failed citations, flags and relations

Writes outputs/thor/<doc_id>.json and outputs/state_export.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from odin.agents.thor import DocResult, Thor  # noqa: E402
from odin.config import load_config  # noqa: E402
from odin.ingest.loader import ingest_bundle  # noqa: E402
from odin.llm import LLMClient  # noqa: E402
from odin.state.store import StateStore  # noqa: E402

COLUMNS = ["doc", "clauses", "fields", "amb", "miss", "contra", "cit ok", "cit fail", "LLM calls", "cached", "tokens",
           "cover%", "status"]


def table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    fmt = lambda r: "  ".join(str(v).rjust(w) if i else str(v).ljust(w) for i, (v, w) in enumerate(zip(r, widths)))  # noqa: E731
    sep = "  ".join("-" * w for w in widths)
    return "\n".join([fmt(headers), sep] + [fmt(r) for r in rows])


def result_row(r: DocResult) -> list[str]:
    status = r.status + (" (unchanged, skipped)" if r.skipped else "")
    return [r.doc_id, str(r.clauses), str(r.fields), str(r.ambiguous), str(r.missing), str(r.contradictory),
            str(r.citations_verified), str(r.citations_failed), str(r.llm_calls), str(r.cache_hits), f"{r.tokens:,}",
            f"{r.coverage:.0f}", status]


PLACEHOLDER_MARKS = ("<", "your-", "changeme", "xxxx", "replace-me")


def llm_config_problem(cfg) -> str | None:
    """Catch unfilled .env templates before any API call is attempted."""
    model, key = cfg.llm.model or "", cfg.llm.api_key or ""
    if not model:
        return f"LLM_MODEL is empty (required for provider {cfg.llm.provider})"
    if any(m in model.lower() for m in PLACEHOLDER_MARKS):
        return f"LLM_MODEL looks like a placeholder: {model!r}"
    if cfg.llm.provider == "openai_compat" and not key:
        return "no API key: set LLM_API_KEY (or OPENAI_API_KEY)"
    if key and any(key.lower().startswith(m) for m in PLACEHOLDER_MARKS):
        return "the API key in .env looks like a placeholder"
    return None


def print_details(store: StateStore) -> None:
    print("\n== Citations that failed verification")
    n = 0
    for ex in store.current_extractions(agent="thor"):
        for c in store.citations_for(ex.id):  # type: ignore[arg-type]
            if not c.verified:
                n += 1
                print(f"- {ex.doc_id} {ex.field_type}/{ex.field_key} cited {c.llm_clause_id!r}: {c.quote[:160]!r}")
    if not n:
        print("(none)")

    print("\n== Open flags")
    flags = store.list_flags(status="open")
    for f in flags:
        ev = "" if not f.evidence else f"  [evidence {'verified' if f.evidence_verified else 'NOT verified'}]"
        print(f"- [{f.type}] {f.clause_id or f.doc_id}: {f.description}{ev}")
    if not flags:
        print("(none)")

    print("\n== Document relations")
    rels = store.list_relations()
    for r in rels:
        cite = r.citation or {}
        target = f" -> {cite.get('target_clause')}" if cite.get("target_clause") else ""
        op = f" ({cite.get('operation')})" if cite.get("operation") else ""
        print(f"- {r.from_doc} {r.type} {r.to_doc}{target}{op}  via {r.clause_id} "
              f"[{'verified' if r.verified else 'UNVERIFIED'}]: {str(cite.get('quote', ''))[:140]!r}")
    if not rels:
        print("(none)")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", help="comma-separated doc ids (default: all)")
    ap.add_argument("--force", action="store_true", help="re-extract even when the document is unchanged")
    ap.add_argument("--workers", type=int, default=4, help="parallel LLM calls (default 4)")
    ap.add_argument("--no-llm", action="store_true", help="ingest and segment only")
    ap.add_argument("--details", action="store_true", help="print failed citations, flags and relations")
    ap.add_argument("--config", help="path to config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    store = StateStore(cfg.paths.db_path)
    report = ingest_bundle(store, cfg)
    print(f"Bundle: {cfg.paths.bundle_dir}")
    print("Ingested: " + ", ".join(f"{d.doc_id}({d.status}, {d.clauses} clauses, {d.method})" for d in report.documents))

    out_dir = cfg.paths.outputs_dir
    if args.no_llm:
        store.export_json(out_dir / "state_export.json")
        print(f"--no-llm: wrote {out_dir / 'state_export.json'}")
        return 0

    problem = llm_config_problem(cfg)
    if problem:
        print(f"error: {problem}\nFix .env (see .env.example), or run with --no-llm.")
        return 2
    if cfg.llm.provider == "anthropic" and not (cfg.llm.api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("warning: no ANTHROPIC_API_KEY / LLM_API_KEY set; the SDK will try an `ant auth login` profile.")
    llm = LLMClient.from_config(cfg)
    thor = Thor(store, llm, cfg)
    print(f"Thor run {thor.run_id}: provider={cfg.llm.provider} model={cfg.llm.model} "
          f"limits: {cfg.limits.max_llm_calls} calls / {cfg.limits.max_tokens_budget:,} tokens")
    docs = [d.strip() for d in args.docs.split(",")] if args.docs else None
    results = thor.run(docs, force=args.force, workers=args.workers)
    thor.handle_messages()

    print()
    print(table([result_row(r) for r in results], COLUMNS))
    total = llm.stats
    print(f"\nTotals: {total.calls} API calls, {total.cache_hits} cache hits, {total.tokens:,} tokens "
          f"({total.input_tokens:,} in / {total.output_tokens:,} out), {total.failures} failed attempts")
    for r in results:
        if r.reason and r.status != "complete":
            print(f"  {r.doc_id}: {r.reason}")

    (out_dir / "thor").mkdir(parents=True, exist_ok=True)
    for r in results:
        path = out_dir / "thor" / f"{r.doc_id}.json"
        path.write_text(json.dumps(thor.document_report(r.doc_id), ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "thor" / "_run_summary.json").write_text(json.dumps({
        "run_id": thor.run_id, "provider": cfg.llm.provider, "model": cfg.llm.model,
        "llm": {"calls": total.calls, "cache_hits": total.cache_hits, "input_tokens": total.input_tokens,
                "output_tokens": total.output_tokens, "failures": total.failures},
        "documents": [r.__dict__ for r in results],
    }, indent=2), encoding="utf-8")
    store.export_json(out_dir / "state_export.json")
    print(f"\nWrote {out_dir / 'thor'}/<doc_id>.json and {out_dir / 'state_export.json'}")

    if args.details:
        print_details(store)
    return 0 if all(r.status == "complete" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

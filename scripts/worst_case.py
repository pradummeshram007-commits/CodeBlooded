"""Worst-case exposure if nobody acts from a date on, against acting on time.

    python scripts/worst_case.py --checkpoint 2
    python scripts/worst_case.py --as-of 2027-06-01
    python scripts/worst_case.py --checkpoint 1 --no-writeup     # skip the LLM writeup

Stores exposure_items (both scenarios), a timeline snapshot with chart_data, and the writeup
("AI-generated analysis", or a template when the LLM is unavailable or fails the number check).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from odin.config import load_config  # noqa: E402
from odin.llm import LLMClient, llm_config_problem  # noqa: E402
from odin.norns import writeup  # noqa: E402
from odin.norns.calendar import iso, to_date  # noqa: E402
from odin.norns.engine import Norns  # noqa: E402
from odin.norns.report import timeline_text, worst_case_text  # noqa: E402
from odin.norns.worst_case import worst_case  # noqa: E402
from odin.state.backend import open_store  # noqa: E402
from odin.state.errors import StoreError  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    when = ap.add_mutually_exclusive_group(required=True)
    when.add_argument("--as-of", help="YYYY-MM-DD")
    when.add_argument("--checkpoint", type=int, help="0 = start date, 1.. = clock.json checkpoints")
    ap.add_argument("--contracts", help="comma-separated root contracts")
    ap.add_argument("--facts", help="JSON file with a list of facts")
    ap.add_argument("--no-writeup", action="store_true")
    ap.add_argument("--json", help="also write the full result to this file")
    ap.add_argument("--config")
    args = ap.parse_args()

    cfg = load_config(args.config)
    try:
        store = open_store(cfg)
    except StoreError as exc:
        print(f"error: {exc}")
        return 3
    llm = None
    if not args.no_writeup and llm_config_problem(cfg) is None:
        llm = LLMClient.from_config(cfg)
    norns = Norns(store, llm, cfg, contracts=args.contracts.split(",") if args.contracts else None)
    as_of = norns.checkpoint(args.checkpoint) if args.checkpoint is not None else to_date(args.as_of)
    facts = json.loads(Path(args.facts).read_text(encoding="utf-8")) if args.facts else []

    t = norns.compute(as_of, facts)
    wc = worst_case(norns, t)
    chart = wc.chart_data()
    with norns.step("worst_case", iso(as_of)) as info:
        store.replace_exposure_items(iso(as_of), wc.items())  # type: ignore[arg-type]
        norns.persist(t, chart_data=chart)
        info.update(output_ref=f"worst {wc.total('worst_case')} / avoidable {wc.avoidable}",
                    unquantified=len([u for u in wc.unquantified if u["scenario"] == "worst_case"]))
    print(timeline_text(t, cfg.norns.due_soon_days))
    print()
    print(worst_case_text(wc))
    if not args.no_writeup:
        w = writeup.generate(norns, wc)
        store.add_writeup(w)
        norns.log("writeup", iso(as_of), w.generated_by, label=w.label, model=w.model, prompt_hash=w.prompt_hash,
                  check_passed=w.check_passed)
        print(f"\n== Writeup [{w.label}] (model {w.model or '-'}, prompt {str(w.prompt_hash)[:12]})")
        print(w.text)
    if args.json:
        Path(args.json).write_text(json.dumps({"timeline": t.summary(cfg.norns.due_soon_days), "chart_data": chart,
                                               "items": [i.model_dump() for i in wc.items()]}, indent=2, default=str),
                                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

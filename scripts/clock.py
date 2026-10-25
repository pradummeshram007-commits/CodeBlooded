"""The simulated clock. Every move recomputes Norns from scratch and stores a snapshot.

    python scripts/clock.py show
    python scripts/clock.py set 2027-03-15
    python scripts/clock.py checkpoint 1            # 0 = start date, 1.. = clock.json checkpoints
    python scripts/clock.py advance 7d              # Nd | Nw | Nm
    python scripts/clock.py play --step 7d --until 2027-06-01

Options: --contracts A1,B1 (default: config norns.contracts), --facts facts.json (a list of
fact dicts: payment_made, notice_sent, insurance_renewed, outage; see odin/norns/engine.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from odin.config import load_config  # noqa: E402
from odin.norns.clock import Clock  # noqa: E402
from odin.norns.engine import Norns  # noqa: E402
from odin.norns.report import changes_text, timeline_text, worst_case_text  # noqa: E402
from odin.state.backend import open_store  # noqa: E402
from odin.state.errors import StoreError  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["show", "set", "checkpoint", "advance", "play"])
    ap.add_argument("value", nargs="?", help="date (set), checkpoint number, or step (advance)")
    ap.add_argument("--step", default="7d", help="play: step size (Nd, Nw, Nm)")
    ap.add_argument("--until", help="play: last date")
    ap.add_argument("--contracts", help="comma-separated root contracts")
    ap.add_argument("--facts", help="JSON file with a list of facts")
    ap.add_argument("--config")
    args = ap.parse_args()

    cfg = load_config(args.config)
    try:
        store = open_store(cfg)
    except StoreError as exc:
        print(f"error: {exc}")
        return 3
    facts = json.loads(Path(args.facts).read_text(encoding="utf-8")) if args.facts else []
    norns = Norns(store, None, cfg, contracts=args.contracts.split(",") if args.contracts else None)
    clock = Clock(norns, facts)
    due = cfg.norns.due_soon_days

    if args.command == "show":
        t, wc = clock.evaluate(clock.current())
        state = store.get_clock_state()
        print(f"Clock at {clock.current()} ({'set ' + state.updated_at if state else 'never set: start date'})")
        print(timeline_text(t, due))
        print(worst_case_text(wc))
        return 0
    if args.command == "play":
        if not args.until:
            ap.error("play needs --until")
        print(f"Playing from {clock.current()} in steps of {args.step} until {args.until}")
        for t, wc, ch in clock.play(args.step, args.until):
            print(changes_text(ch) + f"   [worst case {wc.kpis['total_worst_case']}, overdue {len(t.overdue())}]")
        print()
        print(timeline_text(t, due))
        return 0
    if args.value is None:
        ap.error(f"{args.command} needs a value")
    if args.command == "set":
        t, wc = clock.set(args.value)
    elif args.command == "checkpoint":
        t, wc = clock.checkpoint(int(args.value))
    else:
        t, wc = clock.advance(args.value)
    print(f"Clock moved to {t.as_of}; snapshot stored.")
    print(timeline_text(t, due))
    print(worst_case_text(wc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

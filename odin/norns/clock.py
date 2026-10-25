"""The simulated clock: every move recomputes from scratch and stores a snapshot.

``play`` steps through dates and reports what CHANGED between positions: newly overdue
items, penalties newly triggered, deadlines passed, renewals locked in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable

from odin.norns.calendar import add_months, iso, to_date
from odin.norns.engine import Norns, Timeline
from odin.norns.worst_case import WorstCase, worst_case


def parse_step(spec: str) -> tuple[int, str]:
    m = re.fullmatch(r"\s*(\d+)\s*([dwm])\s*", spec, re.I)
    if not m:
        raise ValueError(f"step must look like 7d, 2w or 1m, not {spec!r}")
    return int(m.group(1)), m.group(2).lower()


def step_from(d: date, spec: str) -> date:
    n, unit = parse_step(spec)
    if unit == "m":
        return add_months(d, n)
    return d + timedelta(days=n * (7 if unit == "w" else 1))


@dataclass
class Changes:
    from_as_of: str
    to_as_of: str
    newly_overdue: list[dict[str, Any]] = field(default_factory=list)
    penalties_triggered: list[dict[str, Any]] = field(default_factory=list)
    deadlines_passed: list[dict[str, Any]] = field(default_factory=list)
    renewals_locked_in: list[dict[str, Any]] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.newly_overdue or self.penalties_triggered or self.deadlines_passed or self.renewals_locked_in)


def diff(prev: Timeline, cur: Timeline) -> Changes:
    ch = Changes(iso(prev.as_of), iso(cur.as_of))  # type: ignore[arg-type]
    before_overdue = {i.key for i in prev.overdue()}
    ch.newly_overdue = [i.view() for i in cur.overdue() if i.key not in before_overdue]
    before_triggers = {(t["type"], t["instance"]) for t in prev.penalty_triggers}
    ch.penalties_triggered = [t for t in cur.penalty_triggers if (t["type"], t["instance"]) not in before_triggers]
    prev_by_key = {i.key: i for i in prev.instances}
    for i in cur.instances:
        p = prev_by_key.get(i.key)
        if i.due and prev.as_of < i.due < cur.as_of and (p is None or p.status == "upcoming"):
            ch.deadlines_passed.append({**i.view(), "outcome": i.status})
        if i.kind == "renewal" and i.status == "missed" and (p is None or p.status != "missed"):
            ch.renewals_locked_in.append(i.view())
    return ch


class Clock:
    def __init__(self, norns: Norns, facts: Iterable[dict[str, Any]] | None = None):
        self.norns = norns
        self.store = norns.store
        self.facts = list(facts or [])

    def current(self) -> date:
        state = self.store.get_clock_state()
        if state:
            return to_date(state.current_as_of)  # type: ignore[return-value]
        return self.norns.checkpoint(0)

    def evaluate(self, as_of: date) -> tuple[Timeline, WorstCase]:
        t = self.norns.compute(as_of, self.facts)
        return t, worst_case(self.norns, t)

    def move(self, as_of: date, action: str, note: str | None = None) -> tuple[Timeline, WorstCase]:
        t, wc = self.evaluate(as_of)
        self.norns.persist(t, chart_data=wc.chart_data())
        self.store.set_clock_state(iso(as_of), action, note)  # type: ignore[arg-type]
        self.norns.log("clock_" + action, iso(as_of), f"{len(t.instances)} instances", note=note,
                       overdue=len(t.overdue()), worst_case=str(wc.total("worst_case")))
        return t, wc

    def set(self, as_of: date | str) -> tuple[Timeline, WorstCase]:
        return self.move(to_date(as_of), "set")  # type: ignore[arg-type]

    def checkpoint(self, n: int) -> tuple[Timeline, WorstCase]:
        return self.move(self.norns.checkpoint(n), "checkpoint", f"checkpoint {n}")

    def advance(self, spec: str) -> tuple[Timeline, WorstCase]:
        return self.move(step_from(self.current(), spec), "advance", spec)

    def play(self, step: str, until: date | str) -> list[tuple[Timeline, WorstCase, Changes]]:
        end = to_date(until)
        assert end is not None
        prev_t, _ = self.evaluate(self.current())
        out = []
        d = step_from(prev_t.as_of, step)
        while True:
            d = min(d, end)
            t, wc = self.move(d, "play", f"step {step} until {end}")
            out.append((t, wc, diff(prev_t, t)))
            prev_t = t
            if d >= end:
                break
            d = step_from(d, step)
        return out

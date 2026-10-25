"""Deterministic calendar and money arithmetic for Norns.

* Business day = not Saturday/Sunday and not in the holidays table for the observer
  (``All`` rows apply to everyone; ``Quillhub`` rows only to Quillhub).
* Month arithmetic uses dateutil.relativedelta (Jan 31 + 1 month = Feb 28/29).
* A day count whose day_type is "unspecified" is computed both ways; deadlines use the
  EARLIER date (the conservative reading) and say so.
* Money is Decimal, rounded to cents half-up, never float.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

import numpy as np
from dateutil.relativedelta import relativedelta

from odin.state.models import Holiday

CENT = Decimal("0.01")
MONTH_DAYS = Decimal(30)        # part-month interest: days / 30 (the contracts do not say)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]


def money(x: Decimal | int | float | str) -> Decimal:
    if isinstance(x, float):
        x = f"{x:.2f}"
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def pct(x: str | float | Decimal) -> Decimal:
    """'15%' / 15 / '0.15' -> Decimal('0.15')."""
    s = str(x).strip().rstrip("%").strip()
    v = Decimal(s)
    return v / 100 if (isinstance(x, str) and str(x).strip().endswith("%")) or v > 1 else v


def to_date(x: str | date | None) -> date | None:
    if x is None or isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def add_months(d: date, n: int) -> date:
    return d + relativedelta(months=n)


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(d: date) -> date:
    return (d.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)


def months_between(start: date, end: date) -> Decimal:
    """Elapsed months from start to end: whole months by relativedelta, the rest as days/30."""
    if end <= start:
        return Decimal(0)
    rd = relativedelta(end, start)
    whole = rd.years * 12 + rd.months
    rest = (end - (start + relativedelta(months=whole))).days
    return Decimal(whole) + Decimal(rest) / MONTH_DAYS


def parse_month_year(text: str) -> str | None:
    """'August 2026 hosting fee' -> '2026-08'."""
    m = re.search(r"\b(" + "|".join(MONTHS) + r")\s+(\d{4})\b", text, re.I)
    return f"{m.group(2)}-{MONTHS.index(m.group(1).lower()) + 1:02d}" if m else None


def parse_long_date(text: str) -> date | None:
    """'June 30, 2027' -> date(2027, 6, 30)."""
    m = re.search(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2}),\s*(\d{4})\b", text, re.I)
    if not m:
        return None
    return date(int(m.group(3)), MONTHS.index(m.group(1).lower()) + 1, int(m.group(2)))


@dataclass
class DayCount:
    """A deadline computed from an anchor and a day count."""

    calendar: date
    business: date
    chosen: date
    day_type: str
    flags: list[str] = field(default_factory=list)


class BusinessCalendar:
    def __init__(self, holidays: Iterable[Holiday]):
        self.by_observer: dict[str, set[date]] = {}
        for h in holidays:
            self.by_observer.setdefault(h.observed_by, set()).add(date.fromisoformat(h.date))
        years = {d.year for ds in self.by_observer.values() for d in ds}
        self.years = (min(years), max(years)) if years else None
        self._cache: dict[tuple[str, ...], np.ndarray] = {}

    def holidays_for(self, observers: Iterable[str]) -> np.ndarray:
        key = tuple(sorted(set(observers) | {"All"}))
        if key not in self._cache:
            days = sorted(set().union(*(self.by_observer.get(o, set()) for o in key)))
            self._cache[key] = np.array(days, dtype="datetime64[D]")
        return self._cache[key]

    def covers(self, d: date) -> bool:
        return bool(self.years) and self.years[0] <= d.year <= self.years[1]  # type: ignore[index]

    def coverage_flag(self, d: date) -> str | None:
        if self.covers(d):
            return None
        span = f"{self.years[0]}-{self.years[1]}" if self.years else "none"
        return f"holidays table covers {span} only; business days in {d.year} exclude weekends only"

    def is_business_day(self, d: date, observers: Iterable[str] = ("All",)) -> bool:
        return bool(np.is_busday(np.datetime64(d), holidays=self.holidays_for(observers)))

    def add_business_days(self, d: date, n: int, observers: Iterable[str] = ("All",)) -> date:
        """n > 0: the n-th business day after d (d itself is day 0). n < 0: the n-th business day before d."""
        hol = self.holidays_for(observers)
        roll = "backward" if n >= 0 else "forward"
        out = np.busday_offset(np.datetime64(d), n, roll=roll, holidays=hol)
        return out.astype(object)

    def first_business_day(self, year: int, month: int, observers: Iterable[str] = ("All",)) -> date:
        out = np.busday_offset(np.datetime64(date(year, month, 1)), 0, roll="forward", holidays=self.holidays_for(observers))
        return out.astype(object)

    def count(self, anchor: date, amount: int, *, day_type: str | None, direction: str = "after",
              observers: Iterable[str] = ("All",)) -> DayCount:
        """Deadline `amount` days after/before `anchor`, both ways; the day_type picks one (unspecified: earlier)."""
        sign = 1 if direction == "after" else -1
        cal = anchor + timedelta(days=sign * amount)
        bus = self.add_business_days(anchor, sign * amount, observers)
        flags = [f for f in (self.coverage_flag(bus),) if f]
        if day_type == "business":
            chosen = bus
        elif day_type == "calendar":
            chosen = cal
        else:
            chosen = min(cal, bus)
            flags.append(f"'{amount} days' does not say business or calendar days: calendar gives {cal}, business gives "
                         f"{bus}; the earlier ({chosen}) is used")
        if day_type != "business" and cal.weekday() >= 5 and chosen == cal:
            flags.append(f"{cal} falls on a {cal.strftime('%A')}; the contract does not move it to a business day")
        return DayCount(cal, bus, chosen, day_type or "unspecified", flags)

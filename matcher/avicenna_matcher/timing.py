"""Precision- and time-basis-aware clinical time (§4.4, PATIENT_MATCHING_FORMAT_STANDARD time rules).

A clinical time is a *span*: a reduced-precision point (year/month/day) stands for every
instant in its unit, never for its first instant. Spans on different time bases
(shifted_patient_local vs unshifted_verified) — or on an `unknown` basis — share no
chronology and are never compared.

Internal TimePoint: {"timestamp": RFC 3339, "precision"?: year|month|day|second,
"time_basis"?: shifted_patient_local|unshifted_verified|unknown}. Absent precision means
second; absent time_basis means the producer guarantees one consistent basis for the
packet (legacy internal fixtures). The canonical-packet adapter always sets both.

Comparisons return "in" / "out" / "uncertain"; callers must treat "uncertain" as UNKNOWN.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from .resolution import parse_time

PRECISIONS = ("year", "month", "day", "second")
_MICRO = timedelta(microseconds=1)


@dataclass(frozen=True)
class Span:
    start: datetime
    end: datetime
    precision: str
    basis: Optional[str]

    @property
    def exact(self) -> bool:
        return self.precision == "second"

    @property
    def first_day(self) -> date:
        return self.start.date()

    @property
    def last_day(self) -> date:
        return self.end.date()


def _span_of_point(tp) -> Optional[Span]:
    if tp is None:
        return None
    if isinstance(tp, dict) and "timestamp" in tp:
        t = parse_time(tp["timestamp"])
        precision = tp.get("precision", "second")
        basis = tp.get("time_basis")
    else:
        t = parse_time(tp)
        precision, basis = "second", None
    if t is None or precision not in PRECISIONS:
        return None
    if precision == "second":
        return Span(t, t, precision, basis)
    if precision == "day":
        start = datetime(t.year, t.month, t.day)
        return Span(start, start + timedelta(days=1) - _MICRO, precision, basis)
    if precision == "month":
        start = datetime(t.year, t.month, 1)
        nxt = datetime(t.year + (t.month == 12), t.month % 12 + 1, 1)
        return Span(start, nxt - _MICRO, precision, basis)
    start = datetime(t.year, 1, 1)
    return Span(start, datetime(t.year + 1, 1, 1) - _MICRO, precision, basis)


def span_of(value) -> Optional[Span]:
    """Span of a Fact.effective_time (TimePoint or TimeInterval; an interval uses its end
    bound — the latest point the assertion held — or its start when open-ended)."""
    if isinstance(value, dict) and ("start" in value or "end" in value) and "timestamp" not in value:
        return _span_of_point(value.get("end")) or _span_of_point(value.get("start"))
    return _span_of_point(value)


def comparable(a: Span, b: Span) -> bool:
    return a.basis == b.basis and a.basis != "unknown"


def strictly_later(a: Span, b: Span) -> Optional[bool]:
    """Is a definitely later than b? None when the two cannot be ordered (different basis)."""
    if not comparable(a, b):
        return None
    if a.exact and b.exact:
        return a.start > b.start
    return a.first_day > b.last_day


def position(fact: Span, anchor: Span, window_days: Optional[int]) -> str:
    """Where a fact lies relative to [anchor - window_days, anchor] (or (-inf, anchor] when
    window_days is None): "in" / "out" / "uncertain". Day-granular unless both are exact;
    a fact on the anchor's own day is not 'after' the anchor."""
    if not comparable(fact, anchor):
        return "uncertain"
    if fact.exact and anchor.exact:
        if fact.start > anchor.start:
            return "out"
        if window_days is not None and (anchor.start - fact.start).days > window_days:
            return "out"
        return "in"
    if fact.first_day > anchor.last_day:
        return "out"
    if window_days is not None and (anchor.first_day - fact.last_day).days > window_days:
        return "out"
    after_possible = fact.last_day > anchor.first_day
    window_breach_possible = window_days is not None and (anchor.last_day - fact.first_day).days > window_days
    return "uncertain" if (after_possible or window_breach_possible) else "in"

"""Set-based comparison for avicenna.matcher

§3.2: Patient values are intervals, bands, and inequalities, never scalars.
Comparison is between a patient **set** S and a predicate **region** R:
- TRUE iff S ⊆ R (wholly satisfies)
- FALSE iff S ∩ R = ∅ (wholly fails)
- UNKNOWN iff S straddles the boundary of R

Worked example:
- Age band [60,64] against "≥ 18" → TRUE
- Age band [60,64] against "≤ 62" → UNKNOWN (straddles 62)
- Age band [60,64] against "≤ 50" → FALSE
"""

from dataclasses import dataclass
from typing import Optional, Union
from .types import TriState


@dataclass
class Interval:
    """A numeric interval [start, end] with open/closed bounds
    
    Represents a region in the real numbers. Each bound can be:
    - None: unbounded (∓∞)
    - float: closed bound (inclusive)
    - The bound_type flags indicate if the bound is inclusive or exclusive
    """
    start: Optional[float] = None  # None = -∞
    end: Optional[float] = None  # None = +∞
    start_inclusive: bool = True  # Whether start bound is inclusive (≥) or exclusive (>)
    end_inclusive: bool = True  # Whether end bound is inclusive (≤) or exclusive (<)

    def is_point(self) -> bool:
        """True if this is a single point (start == end)"""
        return self.start is not None and self.end is not None and self.start == self.end

    def is_empty(self) -> bool:
        """True if interval is empty (start > end)"""
        return self.start is not None and self.end is not None and self.start > self.end

    def is_infinite(self) -> bool:
        """True if unbounded on both ends"""
        return self.start is None and self.end is None

    def contains(self, value: float) -> bool:
        """True if value is within the interval (respecting open/closed bounds)"""
        if self.start is not None:
            if self.start_inclusive and value < self.start:
                return False
            if not self.start_inclusive and value <= self.start:
                return False
        if self.end is not None:
            if self.end_inclusive and value > self.end:
                return False
            if not self.end_inclusive and value >= self.end:
                return False
        return True

    def subset_of(self, other: "Interval") -> bool:
        """True if self ⊆ other (respecting open/closed bounds)"""
        # self is subset of other iff:
        # - other's lower bound is at or to the left of self's lower bound
        # - self's upper bound is at or to the left of other's upper bound
        # - At boundary points, we need to respect inclusivity
        
        # Check left bound
        if other.start is not None and self.start is not None:
            if self.start < other.start:
                return False
            if self.start == other.start:
                # If they're equal, self's bound must be at least as inclusive as other's
                if not other.start_inclusive and self.start_inclusive:
                    return False
        if other.start is not None and self.start is None:  # self unbounded left, other bounded
            return False
        
        # Check right bound
        if other.end is not None and self.end is not None:
            if self.end > other.end:
                return False
            if self.end == other.end:
                # If they're equal, self's bound must be at least as inclusive as other's
                if not other.end_inclusive and self.end_inclusive:
                    return False
        if other.end is not None and self.end is None:  # self unbounded right, other bounded
            return False
        
        return True

    def intersects(self, other: "Interval") -> bool:
        """True if self ∩ other ≠ ∅ (respecting open/closed bounds)"""
        # Two intervals are disjoint iff:
        # - one ends before the other starts
        # - OR one ends exactly where the other starts with at least one exclusive boundary
        
        # Check if self ends before other starts
        if self.end is not None and other.start is not None:
            if self.end < other.start:
                return False
            if self.end == other.start:
                # They touch at a point; they intersect only if both are inclusive at that point
                if not (self.end_inclusive and other.start_inclusive):
                    return False
        
        # Check if other ends before self starts
        if other.end is not None and self.start is not None:
            if other.end < self.start:
                return False
            if other.end == self.start:
                # They touch at a point; they intersect only if both are inclusive at that point
                if not (other.end_inclusive and self.start_inclusive):
                    return False
        
        return True

    def straddles(self, other: "Interval") -> bool:
        """
        True if self straddles the boundary of other:
        - self partially overlaps with other but is not wholly contained
        """
        if not self.intersects(other):
            return False
        if self.subset_of(other):
            return False
        # Must overlap but not be contained
        return True


def compare_intervals(patient_interval: Interval, predicate_interval: Interval) -> TriState:
    """
    Compare patient interval S against predicate interval R.
    
    Returns:
    - TRUE if S ⊆ R (patient wholly satisfies)
    - FALSE if S ∩ R = ∅ (patient wholly fails)
    - UNKNOWN if S straddles R (ambiguous)
    """
    if patient_interval.subset_of(predicate_interval):
        return TriState.TRUE
    elif not patient_interval.intersects(predicate_interval):
        return TriState.FALSE
    else:
        return TriState.UNKNOWN


def compare_quantity_to_threshold(
    patient_value: float,
    comparator: str,  # "lt", "le", "gt", "ge", "eq", "ne"
    threshold: float,
) -> TriState:
    """
    Compare a patient quantity (point value) against a threshold.
    
    For a point value, we convert the comparator to an interval and compare.
    The point patient value is always inclusive [x, x].
    """
    if comparator == "lt":
        # x < threshold ⇔ x in (-∞, threshold) [open on right]
        predicate = Interval(start=None, end=threshold, start_inclusive=True, end_inclusive=False)
        patient = Interval(start=patient_value, end=patient_value, start_inclusive=True, end_inclusive=True)
    elif comparator == "le":
        # x ≤ threshold ⇔ x in (-∞, threshold] [closed on right]
        predicate = Interval(start=None, end=threshold, start_inclusive=True, end_inclusive=True)
        patient = Interval(start=patient_value, end=patient_value, start_inclusive=True, end_inclusive=True)
    elif comparator == "gt":
        # x > threshold ⇔ x in (threshold, ∞) [open on left]
        predicate = Interval(start=threshold, end=None, start_inclusive=False, end_inclusive=True)
        patient = Interval(start=patient_value, end=patient_value, start_inclusive=True, end_inclusive=True)
    elif comparator == "ge":
        # x ≥ threshold ⇔ x in [threshold, ∞) [closed on left]
        predicate = Interval(start=threshold, end=None, start_inclusive=True, end_inclusive=True)
        patient = Interval(start=patient_value, end=patient_value, start_inclusive=True, end_inclusive=True)
    elif comparator == "eq":
        # x == threshold ⇔ x in [threshold, threshold] [point]
        predicate = Interval(start=threshold, end=threshold, start_inclusive=True, end_inclusive=True)
        patient = Interval(start=patient_value, end=patient_value, start_inclusive=True, end_inclusive=True)
    elif comparator == "ne":
        # x ≠ threshold: NOT (x == threshold)
        # For a point value, TRUE if patient != threshold, FALSE otherwise
        if patient_value != threshold:
            return TriState.TRUE
        else:
            return TriState.FALSE
    else:
        raise ValueError(f"Unknown comparator: {comparator}")

    return compare_intervals(patient, predicate)


def compare_band_to_threshold(
    patient_band: tuple[Optional[float], Optional[float]],
    comparator: str,
    threshold: float,
) -> TriState:
    """
    Compare a patient band/interval (e.g., age_group=[60,64]) against a threshold.
    
    Args:
        patient_band: (lower_inclusive, upper_inclusive), either can be None
        comparator: "lt", "le", "gt", "ge", "eq", "ne"
        threshold: the threshold value
    
    Returns: TriState
    """
    lower, upper = patient_band
    # Patient band is always closed (inclusive on both ends)
    patient_interval = Interval(start=lower, end=upper, start_inclusive=True, end_inclusive=True)

    if comparator == "lt":
        # band < threshold ⇔ band in (-∞, threshold) [open on right]
        predicate = Interval(start=None, end=threshold, start_inclusive=True, end_inclusive=False)
    elif comparator == "le":
        # band ≤ threshold ⇔ band in (-∞, threshold] [closed on right]
        predicate = Interval(start=None, end=threshold, start_inclusive=True, end_inclusive=True)
    elif comparator == "gt":
        # band > threshold ⇔ band in (threshold, ∞) [open on left]
        predicate = Interval(start=threshold, end=None, start_inclusive=False, end_inclusive=True)
    elif comparator == "ge":
        # band ≥ threshold ⇔ band in [threshold, ∞) [closed on left]
        predicate = Interval(start=threshold, end=None, start_inclusive=True, end_inclusive=True)
    elif comparator == "eq":
        # Band == threshold is only TRUE if band is exactly [threshold, threshold]
        predicate = Interval(start=threshold, end=threshold, start_inclusive=True, end_inclusive=True)
    elif comparator == "ne":
        # Band ≠ threshold: only FALSE if band is exactly [threshold, threshold]
        if lower is not None and upper is not None and lower == upper == threshold:
            return TriState.FALSE
        elif lower is not None and upper is not None and (upper < threshold or lower > threshold):
            return TriState.TRUE
        else:
            return TriState.UNKNOWN
    else:
        raise ValueError(f"Unknown comparator: {comparator}")

    return compare_intervals(patient_interval, predicate)

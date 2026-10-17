"""Tests for P1: Evaluation algebra (K3 logic + set-based comparison)

Property tests on:
- K3 truth tables
- Flood-relief rule: any() with one TRUE → TRUE regardless of UNKNOWN siblings
- Set subset/intersection/straddle
- Worked example: age band [60,64] against various predicates
"""

import pytest
from avicenna_matcher import TriState
from avicenna_matcher.tristate import k3_and, k3_or, k3_not, k3_all, k3_any
from avicenna_matcher.sets import (
    Interval,
    compare_intervals,
    compare_quantity_to_threshold,
    compare_band_to_threshold,
)


class TestK3And:
    """Test K3 AND (all)"""

    def test_all_true(self):
        """all TRUE → TRUE"""
        assert k3_and(TriState.TRUE, TriState.TRUE) == TriState.TRUE

    def test_any_false(self):
        """any FALSE → FALSE"""
        assert k3_and(TriState.TRUE, TriState.FALSE) == TriState.FALSE
        assert k3_and(TriState.FALSE, TriState.TRUE) == TriState.FALSE
        assert k3_and(TriState.FALSE, TriState.FALSE) == TriState.FALSE

    def test_any_unknown_with_no_false(self):
        """UNKNOWN with no FALSE → UNKNOWN"""
        assert k3_and(TriState.TRUE, TriState.UNKNOWN) == TriState.UNKNOWN
        assert k3_and(TriState.UNKNOWN, TriState.TRUE) == TriState.UNKNOWN
        assert k3_and(TriState.UNKNOWN, TriState.UNKNOWN) == TriState.UNKNOWN

    def test_false_dominates(self):
        """FALSE dominates (checked first)"""
        assert k3_and(TriState.FALSE, TriState.UNKNOWN) == TriState.FALSE
        assert k3_and(TriState.UNKNOWN, TriState.FALSE) == TriState.FALSE

    def test_empty(self):
        """Empty AND → TRUE (identity)"""
        assert k3_and() == TriState.TRUE

    def test_sequence_all(self):
        """Test k3_all with sequence"""
        assert k3_all([TriState.TRUE, TriState.TRUE]) == TriState.TRUE
        assert k3_all([TriState.TRUE, TriState.FALSE]) == TriState.FALSE
        assert k3_all([TriState.TRUE, TriState.UNKNOWN]) == TriState.UNKNOWN


class TestK3Or:
    """Test K3 OR (any)"""

    def test_any_true(self):
        """any TRUE → TRUE (flood-relief)"""
        assert k3_or(TriState.TRUE, TriState.FALSE) == TriState.TRUE
        assert k3_or(TriState.FALSE, TriState.TRUE) == TriState.TRUE
        assert k3_or(TriState.TRUE, TriState.UNKNOWN) == TriState.TRUE
        assert k3_or(TriState.UNKNOWN, TriState.TRUE) == TriState.TRUE

    def test_all_false(self):
        """all FALSE → FALSE"""
        assert k3_or(TriState.FALSE, TriState.FALSE) == TriState.FALSE

    def test_any_unknown_with_no_true(self):
        """UNKNOWN with no TRUE → UNKNOWN"""
        assert k3_or(TriState.FALSE, TriState.UNKNOWN) == TriState.UNKNOWN
        assert k3_or(TriState.UNKNOWN, TriState.FALSE) == TriState.UNKNOWN
        assert k3_or(TriState.UNKNOWN, TriState.UNKNOWN) == TriState.UNKNOWN

    def test_empty(self):
        """Empty OR → FALSE (identity)"""
        assert k3_or() == TriState.FALSE

    def test_flood_relief_with_multiple_unknowns(self):
        """Flood-relief: one TRUE with many UNKNOWNs → TRUE"""
        result = k3_or(
            TriState.UNKNOWN,
            TriState.UNKNOWN,
            TriState.TRUE,
            TriState.UNKNOWN,
            TriState.UNKNOWN,
        )
        assert result == TriState.TRUE

    def test_sequence_any(self):
        """Test k3_any with sequence"""
        assert k3_any([TriState.FALSE, TriState.TRUE]) == TriState.TRUE
        assert k3_any([TriState.FALSE, TriState.FALSE]) == TriState.FALSE
        assert k3_any([TriState.FALSE, TriState.UNKNOWN]) == TriState.UNKNOWN


class TestK3Not:
    """Test K3 NOT"""

    def test_not_true(self):
        """NOT TRUE → FALSE"""
        assert k3_not(TriState.TRUE) == TriState.FALSE

    def test_not_false(self):
        """NOT FALSE → TRUE"""
        assert k3_not(TriState.FALSE) == TriState.TRUE

    def test_not_unknown(self):
        """NOT UNKNOWN → UNKNOWN (fixed point)"""
        assert k3_not(TriState.UNKNOWN) == TriState.UNKNOWN

    def test_double_negation(self):
        """NOT NOT x = x"""
        for val in (TriState.TRUE, TriState.FALSE, TriState.UNKNOWN):
            assert k3_not(k3_not(val)) == val


class TestIntervalSubset:
    """Test interval subset relation"""

    def test_equal_intervals(self):
        """[a,b] ⊆ [a,b]"""
        interval = Interval(start=10.0, end=20.0)
        assert interval.subset_of(interval)

    def test_strict_subset(self):
        """[12,18] ⊆ [10,20]"""
        subset = Interval(start=12.0, end=18.0)
        superset = Interval(start=10.0, end=20.0)
        assert subset.subset_of(superset)

    def test_not_subset(self):
        """[15,25] ⊄ [10,20] (extends beyond)"""
        larger = Interval(start=15.0, end=25.0)
        smaller = Interval(start=10.0, end=20.0)
        assert not larger.subset_of(smaller)

    def test_unbounded_intervals(self):
        """(-∞, +∞) ⊆ (-∞, +∞)"""
        unbounded = Interval(start=None, end=None)
        assert unbounded.subset_of(unbounded)

    def test_point_subset_of_interval(self):
        """[15,15] ⊆ [10,20]"""
        point = Interval(start=15.0, end=15.0)
        interval = Interval(start=10.0, end=20.0)
        assert point.subset_of(interval)

    def test_interval_not_subset_of_point(self):
        """[10,20] ⊄ [15,15]"""
        interval = Interval(start=10.0, end=20.0)
        point = Interval(start=15.0, end=15.0)
        assert not interval.subset_of(point)

    def test_unbounded_left(self):
        """(-∞, 20] ⊆ (-∞, 30]"""
        left = Interval(start=None, end=20.0)
        right = Interval(start=None, end=30.0)
        assert left.subset_of(right)

    def test_unbounded_right(self):
        """[10, +∞) ⊆ [5, +∞)"""
        left = Interval(start=10.0, end=None)
        right = Interval(start=5.0, end=None)
        assert left.subset_of(right)


class TestIntervalIntersection:
    """Test interval intersection"""

    def test_overlapping_intervals(self):
        """[10,20] ∩ [15,25] ≠ ∅"""
        i1 = Interval(start=10.0, end=20.0)
        i2 = Interval(start=15.0, end=25.0)
        assert i1.intersects(i2)
        assert i2.intersects(i1)

    def test_disjoint_intervals(self):
        """[10,15] ∩ [20,25] = ∅"""
        i1 = Interval(start=10.0, end=15.0)
        i2 = Interval(start=20.0, end=25.0)
        assert not i1.intersects(i2)

    def test_touching_intervals(self):
        """[10,15] ∩ [15,20] ≠ ∅ (touching at boundary)"""
        i1 = Interval(start=10.0, end=15.0)
        i2 = Interval(start=15.0, end=20.0)
        assert i1.intersects(i2)

    def test_subset_intersects(self):
        """If A ⊆ B then A ∩ B = A"""
        subset = Interval(start=12.0, end=18.0)
        superset = Interval(start=10.0, end=20.0)
        assert subset.intersects(superset)


class TestIntervalStraddle:
    """Test interval straddling (crossing boundary)"""

    def test_straddle_left_boundary(self):
        """[5,15] straddles [10,20] (crosses left boundary)"""
        patient = Interval(start=5.0, end=15.0)
        predicate = Interval(start=10.0, end=20.0)
        assert patient.straddles(predicate)

    def test_straddle_right_boundary(self):
        """[15,25] straddles [10,20] (crosses right boundary)"""
        patient = Interval(start=15.0, end=25.0)
        predicate = Interval(start=10.0, end=20.0)
        assert patient.straddles(predicate)

    def test_no_straddle_disjoint(self):
        """[5,8] does NOT straddle [10,20] (no intersection)"""
        patient = Interval(start=5.0, end=8.0)
        predicate = Interval(start=10.0, end=20.0)
        assert not patient.straddles(predicate)

    def test_no_straddle_contained(self):
        """[12,18] does NOT straddle [10,20] (wholly contained)"""
        patient = Interval(start=12.0, end=18.0)
        predicate = Interval(start=10.0, end=20.0)
        assert not patient.straddles(predicate)

    def test_no_straddle_equal(self):
        """[10,20] does NOT straddle [10,20] (equal)"""
        patient = Interval(start=10.0, end=20.0)
        predicate = Interval(start=10.0, end=20.0)
        assert not patient.straddles(predicate)


class TestCompareIntervals:
    """Test the full compare_intervals function"""

    def test_wholly_satisfies(self):
        """[12,18] against [10,20] → TRUE"""
        patient = Interval(start=12.0, end=18.0)
        predicate = Interval(start=10.0, end=20.0)
        assert compare_intervals(patient, predicate) == TriState.TRUE

    def test_wholly_fails(self):
        """[5,8] against [10,20] → FALSE"""
        patient = Interval(start=5.0, end=8.0)
        predicate = Interval(start=10.0, end=20.0)
        assert compare_intervals(patient, predicate) == TriState.FALSE

    def test_straddles_left(self):
        """[5,15] against [10,20] → UNKNOWN"""
        patient = Interval(start=5.0, end=15.0)
        predicate = Interval(start=10.0, end=20.0)
        assert compare_intervals(patient, predicate) == TriState.UNKNOWN

    def test_straddles_right(self):
        """[15,25] against [10,20] → UNKNOWN"""
        patient = Interval(start=15.0, end=25.0)
        predicate = Interval(start=10.0, end=20.0)
        assert compare_intervals(patient, predicate) == TriState.UNKNOWN


class TestWorkedExample:
    """Worked example from §3.2: age band [60,64] against various predicates"""

    def test_age_band_against_ge_18(self):
        """Age band [60,64] against "≥ 18" → TRUE"""
        patient = Interval(start=60.0, end=64.0)
        predicate = Interval(start=18.0, end=None)  # ≥ 18
        assert compare_intervals(patient, predicate) == TriState.TRUE

    def test_age_band_against_le_62(self):
        """Age band [60,64] against "≤ 62" → UNKNOWN (straddles)"""
        patient = Interval(start=60.0, end=64.0)
        predicate = Interval(start=None, end=62.0)  # ≤ 62
        assert compare_intervals(patient, predicate) == TriState.UNKNOWN

    def test_age_band_against_le_50(self):
        """Age band [60,64] against "≤ 50" → FALSE"""
        patient = Interval(start=60.0, end=64.0)
        predicate = Interval(start=None, end=50.0)  # ≤ 50
        assert compare_intervals(patient, predicate) == TriState.FALSE


class TestQuantityThresholdComparison:
    """Test point quantity comparison against thresholds"""

    def test_ge_threshold_satisfied(self):
        """13.5 ≥ 7 → TRUE"""
        assert compare_quantity_to_threshold(13.5, "ge", 7.0) == TriState.TRUE

    def test_ge_threshold_failed(self):
        """5.0 ≥ 7 → FALSE"""
        assert compare_quantity_to_threshold(5.0, "ge", 7.0) == TriState.FALSE

    def test_le_threshold_satisfied(self):
        """62 ≤ 100 → TRUE"""
        assert compare_quantity_to_threshold(62.0, "le", 100.0) == TriState.TRUE

    def test_le_threshold_failed(self):
        """150 ≤ 100 → FALSE"""
        assert compare_quantity_to_threshold(150.0, "le", 100.0) == TriState.FALSE

    def test_eq_exact(self):
        """50 == 50 → TRUE"""
        assert compare_quantity_to_threshold(50.0, "eq", 50.0) == TriState.TRUE

    def test_eq_not_exact(self):
        """50 == 51 → FALSE"""
        assert compare_quantity_to_threshold(50.0, "eq", 51.0) == TriState.FALSE

    def test_ne_not_equal(self):
        """50 ≠ 51 → TRUE"""
        assert compare_quantity_to_threshold(50.0, "ne", 51.0) == TriState.TRUE

    def test_ne_equal(self):
        """50 ≠ 50 → FALSE"""
        assert compare_quantity_to_threshold(50.0, "ne", 50.0) == TriState.FALSE


class TestBandThresholdComparison:
    """Test band (interval) comparison against thresholds"""

    def test_band_age_ge_18_true(self):
        """Age band [60,64] ≥ 18 → TRUE (wholly in region)"""
        assert compare_band_to_threshold((60.0, 64.0), "ge", 18.0) == TriState.TRUE

    def test_band_age_le_50_false(self):
        """Age band [60,64] ≤ 50 → FALSE (wholly outside region)"""
        assert compare_band_to_threshold((60.0, 64.0), "le", 50.0) == TriState.FALSE

    def test_band_age_le_62_unknown(self):
        """Age band [60,64] ≤ 62 → UNKNOWN (straddles)"""
        assert compare_band_to_threshold((60.0, 64.0), "le", 62.0) == TriState.UNKNOWN

    def test_band_eq_exact(self):
        """Band [50,50] == 50 → TRUE (point band)"""
        assert compare_band_to_threshold((50.0, 50.0), "eq", 50.0) == TriState.TRUE

    def test_band_eq_different(self):
        """Band [50,50] == 51 → FALSE (point band, different)"""
        assert compare_band_to_threshold((50.0, 50.0), "eq", 51.0) == TriState.FALSE

    def test_band_eq_interval(self):
        """Band [50,60] == 55 → UNKNOWN (interval, not point)"""
        assert compare_band_to_threshold((50.0, 60.0), "eq", 55.0) == TriState.UNKNOWN

    def test_band_ne_disjoint(self):
        """Band [50,60] ≠ 100 → TRUE (no overlap with point)"""
        assert compare_band_to_threshold((50.0, 60.0), "ne", 100.0) == TriState.TRUE

    def test_band_ne_contains_point(self):
        """Band [50,60] ≠ 55 → UNKNOWN (contains point)"""
        assert compare_band_to_threshold((50.0, 60.0), "ne", 55.0) == TriState.UNKNOWN


class TestMasterInvariant:
    """Master invariant: UNKNOWN never yields a hard outcome in aggregation

    Hard outcomes require all branches to resolve without UNKNOWN.
    """

    def test_and_with_unknown_never_hard(self):
        """TRUE AND UNKNOWN → UNKNOWN (not a hard outcome)"""
        result = k3_and(TriState.TRUE, TriState.UNKNOWN)
        assert result == TriState.UNKNOWN

    def test_or_with_unknown_false_never_hard(self):
        """FALSE OR UNKNOWN → UNKNOWN (not a hard outcome)"""
        result = k3_or(TriState.FALSE, TriState.UNKNOWN)
        assert result == TriState.UNKNOWN

    def test_or_with_true_always_hard(self):
        """TRUE OR UNKNOWN → TRUE (hard outcome via flood-relief)"""
        result = k3_or(TriState.TRUE, TriState.UNKNOWN)
        assert result == TriState.TRUE

    def test_and_with_false_always_hard(self):
        """FALSE AND UNKNOWN → FALSE (hard outcome, FALSE dominates)"""
        result = k3_and(TriState.FALSE, TriState.UNKNOWN)
        assert result == TriState.FALSE

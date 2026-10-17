"""Regression tests for F2: Strict vs non-strict inequality (§3.2)

Bug: Interval class had no open/closed flags, so `lt` ≡ `le` and `gt` ≡ `ge`.
Edge case: `x < 1.5` with `x = 1.5` returned TRUE (wrong, should be FALSE).

Fix: Add start_inclusive/end_inclusive flags to Interval class.
Map comparators: lt/le/gt/ge to correct open/closed bounds.
"""

import pytest
from avicenna_matcher.sets import Interval, compare_quantity_to_threshold, compare_band_to_threshold
from avicenna_matcher.types import TriState


class TestIntervalBoundInclusion:
    """Test that Interval respects open vs closed bounds"""
    
    def test_closed_interval_contains_endpoints(self):
        """Closed interval [10, 20] contains 10 and 20"""
        iv = Interval(start=10, end=20, start_inclusive=True, end_inclusive=True)
        assert iv.contains(10)
        assert iv.contains(20)
        assert iv.contains(15)
    
    def test_open_left_interval_excludes_left_endpoint(self):
        """Open-left interval (10, 20] excludes 10 but includes 20"""
        iv = Interval(start=10, end=20, start_inclusive=False, end_inclusive=True)
        assert not iv.contains(10)
        assert iv.contains(20)
        assert iv.contains(15)
    
    def test_open_right_interval_excludes_right_endpoint(self):
        """Open-right interval [10, 20) excludes 20 but includes 10"""
        iv = Interval(start=10, end=20, start_inclusive=True, end_inclusive=False)
        assert iv.contains(10)
        assert not iv.contains(20)
        assert iv.contains(15)
    
    def test_open_interval_excludes_both_endpoints(self):
        """Open interval (10, 20) excludes both 10 and 20"""
        iv = Interval(start=10, end=20, start_inclusive=False, end_inclusive=False)
        assert not iv.contains(10)
        assert not iv.contains(20)
        assert iv.contains(15)
    
    def test_point_interval_is_always_closed(self):
        """Point interval [x, x] always includes x"""
        iv = Interval(start=15, end=15, start_inclusive=True, end_inclusive=True)
        assert iv.contains(15)


class TestStrictLessThan:
    """Test that `lt` (strict less-than) works correctly at boundaries"""
    
    def test_lt_exact_boundary_false(self):
        """x < 1.5 with x=1.5 must return FALSE (the F2 bug case)"""
        result = compare_quantity_to_threshold(patient_value=1.5, comparator="lt", threshold=1.5)
        assert result == TriState.FALSE, "x < 1.5 with x=1.5 should be FALSE"
    
    def test_lt_below_boundary_true(self):
        """x < 1.5 with x=1.4 must return TRUE"""
        result = compare_quantity_to_threshold(patient_value=1.4, comparator="lt", threshold=1.5)
        assert result == TriState.TRUE
    
    def test_lt_above_boundary_false(self):
        """x < 1.5 with x=1.6 must return FALSE"""
        result = compare_quantity_to_threshold(patient_value=1.6, comparator="lt", threshold=1.5)
        assert result == TriState.FALSE


class TestStrictGreaterThan:
    """Test that `gt` (strict greater-than) works correctly at boundaries"""
    
    def test_gt_exact_boundary_false(self):
        """x > 1.5 with x=1.5 must return FALSE"""
        result = compare_quantity_to_threshold(patient_value=1.5, comparator="gt", threshold=1.5)
        assert result == TriState.FALSE
    
    def test_gt_below_boundary_false(self):
        """x > 1.5 with x=1.4 must return FALSE"""
        result = compare_quantity_to_threshold(patient_value=1.4, comparator="gt", threshold=1.5)
        assert result == TriState.FALSE
    
    def test_gt_above_boundary_true(self):
        """x > 1.5 with x=1.6 must return TRUE"""
        result = compare_quantity_to_threshold(patient_value=1.6, comparator="gt", threshold=1.5)
        assert result == TriState.TRUE


class TestNonStrictLessThanOrEqual:
    """Test that `le` (non-strict <=) still works correctly"""
    
    def test_le_exact_boundary_true(self):
        """x <= 1.5 with x=1.5 must return TRUE"""
        result = compare_quantity_to_threshold(patient_value=1.5, comparator="le", threshold=1.5)
        assert result == TriState.TRUE
    
    def test_le_below_boundary_true(self):
        """x <= 1.5 with x=1.4 must return TRUE"""
        result = compare_quantity_to_threshold(patient_value=1.4, comparator="le", threshold=1.5)
        assert result == TriState.TRUE
    
    def test_le_above_boundary_false(self):
        """x <= 1.5 with x=1.6 must return FALSE"""
        result = compare_quantity_to_threshold(patient_value=1.6, comparator="le", threshold=1.5)
        assert result == TriState.FALSE


class TestNonStrictGreaterThanOrEqual:
    """Test that `ge` (non-strict >=) still works correctly"""
    
    def test_ge_exact_boundary_true(self):
        """x >= 1.5 with x=1.5 must return TRUE"""
        result = compare_quantity_to_threshold(patient_value=1.5, comparator="ge", threshold=1.5)
        assert result == TriState.TRUE
    
    def test_ge_below_boundary_false(self):
        """x >= 1.5 with x=1.4 must return FALSE"""
        result = compare_quantity_to_threshold(patient_value=1.4, comparator="ge", threshold=1.5)
        assert result == TriState.FALSE
    
    def test_ge_above_boundary_true(self):
        """x >= 1.5 with x=1.6 must return TRUE"""
        result = compare_quantity_to_threshold(patient_value=1.6, comparator="ge", threshold=1.5)
        assert result == TriState.TRUE


class TestBandBoundaries:
    """Test band (interval) comparisons with open/closed bounds"""
    
    def test_band_lt_exact_right_boundary_unknown(self):
        """[60, 62] < 62 must return UNKNOWN (band straddles open boundary)"""
        result = compare_band_to_threshold(patient_band=(60, 62), comparator="lt", threshold=62)
        assert result == TriState.UNKNOWN
    
    def test_band_lt_below_boundary_true(self):
        """[60, 61] < 62 must return TRUE (wholly below)"""
        result = compare_band_to_threshold(patient_band=(60, 61), comparator="lt", threshold=62)
        assert result == TriState.TRUE
    
    def test_band_gt_exact_left_boundary_unknown(self):
        """[62, 64] > 62 must return UNKNOWN (band straddles open boundary)"""
        result = compare_band_to_threshold(patient_band=(62, 64), comparator="gt", threshold=62)
        assert result == TriState.UNKNOWN
    
    def test_band_gt_above_boundary_true(self):
        """[63, 65] > 62 must return TRUE (wholly above)"""
        result = compare_band_to_threshold(patient_band=(63, 65), comparator="gt", threshold=62)
        assert result == TriState.TRUE
    
    def test_band_le_exact_right_boundary_true(self):
        """[60, 62] <= 62 must return TRUE (includes boundary)"""
        result = compare_band_to_threshold(patient_band=(60, 62), comparator="le", threshold=62)
        assert result == TriState.TRUE
    
    def test_band_ge_exact_left_boundary_true(self):
        """[62, 64] >= 62 must return TRUE (includes boundary)"""
        result = compare_band_to_threshold(patient_band=(62, 64), comparator="ge", threshold=62)
        assert result == TriState.TRUE


class TestIntervalIntersectionWithBounds:
    """Test that intersects() respects open/closed bounds"""
    
    def test_touching_closed_closed_intersects(self):
        """[10, 20] ∩ [20, 30] should intersect (both closed at 20)"""
        iv1 = Interval(start=10, end=20, start_inclusive=True, end_inclusive=True)
        iv2 = Interval(start=20, end=30, start_inclusive=True, end_inclusive=True)
        assert iv1.intersects(iv2)
    
    def test_touching_open_closed_disjoint(self):
        """[10, 20) ∩ [20, 30] should be disjoint (one open, one closed at 20)"""
        iv1 = Interval(start=10, end=20, start_inclusive=True, end_inclusive=False)
        iv2 = Interval(start=20, end=30, start_inclusive=True, end_inclusive=True)
        assert not iv1.intersects(iv2)
    
    def test_touching_open_open_disjoint(self):
        """(10, 20) ∩ (20, 30) should be disjoint (both open at 20)"""
        iv1 = Interval(start=10, end=20, start_inclusive=False, end_inclusive=False)
        iv2 = Interval(start=20, end=30, start_inclusive=False, end_inclusive=False)
        assert not iv1.intersects(iv2)


class TestIntervalSubsetWithBounds:
    """Test that subset_of() respects open/closed bounds"""
    
    def test_closed_subset_of_open_at_boundary_false(self):
        """[20, 30] ⊆ (20, 40) should be FALSE (left endpoint not inclusive)"""
        self_iv = Interval(start=20, end=30, start_inclusive=True, end_inclusive=True)
        other_iv = Interval(start=20, end=40, start_inclusive=False, end_inclusive=True)
        assert not self_iv.subset_of(other_iv)
    
    def test_open_subset_of_closed_at_boundary_true(self):
        """(20, 30) ⊆ [20, 40] should be TRUE (open is stricter)"""
        self_iv = Interval(start=20, end=30, start_inclusive=False, end_inclusive=True)
        other_iv = Interval(start=20, end=40, start_inclusive=True, end_inclusive=True)
        assert self_iv.subset_of(other_iv)
    
    def test_equal_closed_intervals_subset(self):
        """[20, 30] ⊆ [20, 30] should be TRUE"""
        iv = Interval(start=20, end=30, start_inclusive=True, end_inclusive=True)
        assert iv.subset_of(iv)
    
    def test_equal_open_intervals_subset(self):
        """(20, 30) ⊆ (20, 30) should be TRUE"""
        iv = Interval(start=20, end=30, start_inclusive=False, end_inclusive=False)
        assert iv.subset_of(iv)


class TestClinicalScenario:
    """Test a realistic clinical scenario: lab threshold "bilirubin < 1.5×ULN"
    
    This is the scenario that triggered F2: a patient with bilirubin exactly 1.5
    should NOT satisfy "bilirubin < 1.5", but the old code returned TRUE.
    """
    
    def test_bilirubin_exact_1_5_fails_lt_1_5(self):
        """Patient with bilirubin=1.5 does NOT satisfy 'bilirubin < 1.5'"""
        result = compare_quantity_to_threshold(
            patient_value=1.5,
            comparator="lt",
            threshold=1.5
        )
        assert result == TriState.FALSE
    
    def test_bilirubin_1_4_satisfies_lt_1_5(self):
        """Patient with bilirubin=1.4 satisfies 'bilirubin < 1.5'"""
        result = compare_quantity_to_threshold(
            patient_value=1.4,
            comparator="lt",
            threshold=1.5
        )
        assert result == TriState.TRUE
    
    def test_bilirubin_exact_1_5_satisfies_le_1_5(self):
        """Patient with bilirubin=1.5 satisfies 'bilirubin ≤ 1.5'"""
        result = compare_quantity_to_threshold(
            patient_value=1.5,
            comparator="le",
            threshold=1.5
        )
        assert result == TriState.TRUE

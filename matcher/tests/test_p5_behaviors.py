"""P5 tests: Per-arm behaviors, study-type handling, jurisdiction guards, coverage.

§7: Three matcher behaviors:
1. Per-arm evaluation (§7.1) — criteria scoped to arms
2. Study-type-aware candidacy (§7.2) — healthy-volunteer inversion, observational labeling
3. Jurisdiction-keyed guards (§7.3) — site-specific context

Tests validate:
- Criterion applicability filtering (arm_scope + guards)
- Per-arm verdict computation
- Trial-level roll-up (conservative aggregation)
- Evidence coverage calculation (resolved vs unresolved applicable criteria)
- Healthy-volunteer study handling
- Site guard context passing
"""

import pytest
from avicenna_matcher import (
    PerArmMatcher,
    TrialAggregator,
    OutcomeEvaluator,
    TriState,
    Outcome,
    EligibilityState,
)


class TestPerArmFilteringArmScope:
    """Test criterion applicability filtering by arm_scope."""
    
    def test_criterion_with_null_arm_scope_applies_to_all_arms(self):
        """Criterion with arm_scope=null applies to every arm."""
        criterion = {
            "criterion_id": "crit_1",
            "arm_scope": None,
            "atoms": [],
        }
        
        is_applicable, reason = PerArmMatcher._is_criterion_applicable(
            criterion, "arm_a", {}
        )
        
        assert is_applicable is True
        assert reason is None
    
    def test_criterion_with_matching_arm_scope_applies(self):
        """Criterion with arm_scope matching arm_id applies."""
        criterion = {
            "criterion_id": "crit_1",
            "arm_scope": "arm_a",
            "atoms": [],
        }
        
        is_applicable, reason = PerArmMatcher._is_criterion_applicable(
            criterion, "arm_a", {}
        )
        
        assert is_applicable is True
    
    def test_criterion_with_non_matching_arm_scope_does_not_apply(self):
        """Criterion with arm_scope not matching arm_id does not apply."""
        criterion = {
            "criterion_id": "crit_1",
            "arm_scope": "arm_b",
            "atoms": [],
        }
        
        is_applicable, reason = PerArmMatcher._is_criterion_applicable(
            criterion, "arm_a", {}
        )
        
        assert is_applicable is False
        assert "arm_b" in reason
    
    def test_filter_criteria_for_arm_includes_only_applicable(self):
        """Filter criteria returns only those applicable to the arm."""
        criteria = [
            {
                "criterion_id": "crit_1",
                "arm_scope": None,  # applies to all
                "atoms": [],
            },
            {
                "criterion_id": "crit_2",
                "arm_scope": "arm_a",  # applies to arm_a
                "atoms": [],
            },
            {
                "criterion_id": "crit_3",
                "arm_scope": "arm_b",  # applies to arm_b, not arm_a
                "atoms": [],
            },
        ]
        
        filtered = PerArmMatcher._filter_criteria_for_arm(criteria, "arm_a", {})
        
        filtered_ids = {c.get("criterion_id") for c in filtered}
        assert filtered_ids == {"crit_1", "crit_2"}


class TestJurisdictionGuards:
    """Test jurisdiction-keyed guard handling (§7.3).
    
    Per §7.3 and §4.1: Guard evaluation happens at predicate time, not here.
    Criteria are always applicable to their arm_scope; guards are evaluated
    as part of the predicate, and missing site context → guard UNKNOWN.
    """
    
    def test_site_country_guard_criterion_still_applicable(self):
        """Criterion with site_country guard is still applicable to the arm.
        
        The guard itself may evaluate to UNKNOWN if site_context missing,
        but the criterion is applicable (just with a gate predicate).
        """
        criterion = {
            "criterion_id": "crit_age_czech",
            "arm_scope": None,
            "atoms": [
                {
                    "atom_id": "guard_1",
                    "predicate_type": "applicability_gate",
                    "guard": {
                        "fact_key": "site_country",
                        "operator": "==",
                        "reference_value": "CZ",
                    },
                }
            ],
        }
        
        # No site context provided
        is_applicable, reason = PerArmMatcher._is_criterion_applicable(
            criterion, "arm_a", {}, site_context=None
        )
        
        # Per §7.3: criterion is applicable; guard evaluation happens later
        assert is_applicable is True
        assert reason is None
    
    def test_site_country_guard_with_site_context_applicable(self):
        """Criterion with guard is applicable regardless of site_context.
        
        Site context is used during guard evaluation, not here.
        """
        criterion = {
            "criterion_id": "crit_age_czech",
            "arm_scope": None,
            "atoms": [
                {
                    "atom_id": "guard_1",
                    "predicate_type": "applicability_gate",
                    "guard": {
                        "fact_key": "site_country",
                        "operator": "==",
                        "reference_value": "CZ",
                    },
                }
            ],
        }
        
        is_applicable, reason = PerArmMatcher._is_criterion_applicable(
            criterion, "arm_a", {}, site_context={"country": "CZ"}
        )
        
        # Criterion still applicable; guard evaluation is separate
        assert is_applicable is True
    
    def test_no_guard_applicable_regardless_of_site_context(self):
        """Criterion without guards applies regardless of site context."""
        criterion = {
            "criterion_id": "crit_1",
            "arm_scope": None,
            "atoms": [],  # No guards
        }
        
        is_applicable, reason = PerArmMatcher._is_criterion_applicable(
            criterion, "arm_a", {}, site_context=None
        )
        
        assert is_applicable is True


class TestEvidenceCoverage:
    """Test evidence coverage calculation (resolved vs unresolved criteria)."""
    
    def test_all_resolved_criteria_100_percent_coverage(self):
        """All criteria with resolved outcomes → 100% coverage."""
        results = [
            {
                "criterion_id": "crit_1",
                "outcome": Outcome.SATISFIED.value,
                "hardness": "hard",
            },
            {
                "criterion_id": "crit_2",
                "outcome": Outcome.RESOLVED_DISQUALIFIER.value,
                "hardness": "hard",
            },
            {
                "criterion_id": "crit_3",
                "outcome": Outcome.CLEAR.value,
                "hardness": "hard",
            },
        ]
        
        coverage = PerArmMatcher._calculate_evidence_coverage(results)
        
        assert coverage["assessed_percentage"] == 100.0
        assert coverage["unassessed_criteria"] == []
        assert coverage["total"] == 3
        assert coverage["assessed"] == 3
    
    def test_unresolved_criteria_excluded_from_100_percent(self):
        """Unresolved criteria reduce coverage percentage."""
        results = [
            {
                "criterion_id": "crit_1",
                "outcome": Outcome.SATISFIED.value,
                "hardness": "hard",
            },
            {
                "criterion_id": "crit_2",
                "outcome": Outcome.UNRESOLVED.value,
                "hardness": "hard",
            },
        ]
        
        coverage = PerArmMatcher._calculate_evidence_coverage(results)
        
        assert coverage["assessed_percentage"] == 50.0
        assert coverage["unassessed_criteria"] == ["crit_2"]
        assert coverage["total"] == 2
        assert coverage["assessed"] == 1
    
    def test_procedural_criteria_excluded_from_denominator(self):
        """Procedural_pre_screen criteria excluded from coverage denominator."""
        results = [
            {
                "criterion_id": "crit_1",
                "outcome": Outcome.SATISFIED.value,
                "hardness": "hard",
            },
            {
                "criterion_id": "crit_proc",
                "outcome": Outcome.NON_BLOCKING.value,
                "hardness": "procedural_pre_screen",
            },
        ]
        
        coverage = PerArmMatcher._calculate_evidence_coverage(results)
        
        # Only crit_1 in denominator
        assert coverage["total"] == 1
        assert coverage["assessed_percentage"] == 100.0
    
    def test_not_applicable_criteria_excluded_from_denominator(self):
        """not_applicable outcomes excluded from denominator."""
        results = [
            {
                "criterion_id": "crit_1",
                "outcome": Outcome.SATISFIED.value,
                "hardness": "hard",
            },
            {
                "criterion_id": "crit_na",
                "outcome": "not_applicable",
                "hardness": "hard",
            },
        ]
        
        coverage = PerArmMatcher._calculate_evidence_coverage(results)
        
        # Only crit_1 in denominator
        assert coverage["total"] == 1
        assert coverage["assessed"] == 1


class TestPerArmEvaluation:
    """Test complete per-arm evaluation workflow."""
    
    def test_per_arm_result_structure(self):
        """Per-arm result contains all required fields."""
        criteria = [
            {
                "criterion_id": "crit_1",
                "arm_scope": None,
                "atoms": [],
                "criterion_type": "inclusion",
                "hardness": "hard",
            }
        ]
        
        results = [
            {
                "criterion_id": "crit_1",
                "criterion_type": "inclusion",
                "hardness": "hard",
                "outcome": Outcome.SATISFIED.value,
                "evaluation_state": "evaluable",
                "coverage": "full",
            }
        ]
        
        arm_result = PerArmMatcher.evaluate_arm(
            arm_id="arm_a",
            study_type="interventional",
            criteria=criteria,
            criterion_results=results,
            criteria_completeness="complete",
        )
        
        # Check required fields
        assert arm_result["arm_id"] == "arm_a"
        assert arm_result["arm_eligibility_state"] in [
            "ineligible",
            "eligible_pending_review",
            "needs_chart_review",
            "manual_review",
        ]
        assert isinstance(arm_result["blocking_criteria"], list)
        assert isinstance(arm_result["manual_review_criteria"], list)
        assert "assessed_percentage" in arm_result["evidence_coverage"]
        assert "unassessed_criteria" in arm_result["evidence_coverage"]
        assert arm_result["study_type"] == "interventional"
        assert arm_result["is_observational"] is False
    
    def test_all_hard_satisfied_complete_coverage_eligible_pending_review(self):
        """All hard satisfied + full coverage + complete → eligible_pending_review."""
        criteria = [
            {
                "criterion_id": "inc_1",
                "arm_scope": None,
                "atoms": [],
                "criterion_type": "inclusion",
                "hardness": "hard",
            },
            {
                "criterion_id": "exc_1",
                "arm_scope": None,
                "atoms": [],
                "criterion_type": "exclusion",
                "hardness": "hard",
            },
        ]
        
        results = [
            {
                "criterion_id": "inc_1",
                "criterion_type": "inclusion",
                "hardness": "hard",
                "outcome": Outcome.SATISFIED.value,
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
            {
                "criterion_id": "exc_1",
                "criterion_type": "exclusion",
                "hardness": "hard",
                "outcome": Outcome.CLEAR.value,
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
        ]
        
        arm_result = PerArmMatcher.evaluate_arm(
            arm_id="arm_a",
            study_type="interventional",
            criteria=criteria,
            criterion_results=results,
            criteria_completeness="complete",
        )
        
        assert arm_result["arm_eligibility_state"] == EligibilityState.ELIGIBLE_PENDING_REVIEW.value
    
    def test_hard_disqualifier_ineligible(self):
        """Hard resolved_disqualifier → ineligible."""
        criteria = [
            {
                "criterion_id": "exc_1",
                "arm_scope": None,
                "atoms": [],
                "criterion_type": "exclusion",
                "hardness": "hard",
            }
        ]
        
        results = [
            {
                "criterion_id": "exc_1",
                "criterion_type": "exclusion",
                "hardness": "hard",
                "outcome": Outcome.RESOLVED_DISQUALIFIER.value,
                "evaluation_state": "evaluable",
                "coverage": "full",
            }
        ]
        
        arm_result = PerArmMatcher.evaluate_arm(
            arm_id="arm_a",
            study_type="interventional",
            criteria=criteria,
            criterion_results=results,
            criteria_completeness="complete",
        )
        
        assert arm_result["arm_eligibility_state"] == EligibilityState.INELIGIBLE.value
        assert "exc_1" in arm_result["blocking_criteria"]
    
    def test_unresolved_hard_needs_chart_review(self):
        """Unresolved hard → needs_chart_review (not eligible_pending_review)."""
        criteria = [
            {
                "criterion_id": "crit_1",
                "arm_scope": None,
                "atoms": [],
                "criterion_type": "inclusion",
                "hardness": "hard",
            }
        ]
        
        results = [
            {
                "criterion_id": "crit_1",
                "criterion_type": "inclusion",
                "hardness": "hard",
                "outcome": Outcome.UNRESOLVED.value,
                "evaluation_state": "missing",
                "coverage": "unknown",
            }
        ]
        
        arm_result = PerArmMatcher.evaluate_arm(
            arm_id="arm_a",
            study_type="interventional",
            criteria=criteria,
            criterion_results=results,
            criteria_completeness="complete",
        )
        
        assert arm_result["arm_eligibility_state"] == EligibilityState.NEEDS_CHART_REVIEW.value
    
    def test_observational_arm_labeled_correctly(self):
        """Observational arm has is_observational=True."""
        criteria = [
            {
                "criterion_id": "crit_1",
                "arm_scope": None,
                "atoms": [],
                "criterion_type": "inclusion",
                "hardness": "hard",
            }
        ]
        
        results = [
            {
                "criterion_id": "crit_1",
                "criterion_type": "inclusion",
                "hardness": "hard",
                "outcome": Outcome.SATISFIED.value,
                "evaluation_state": "evaluable",
                "coverage": "full",
            }
        ]
        
        arm_result = PerArmMatcher.evaluate_arm(
            arm_id="arm_obs",
            study_type="observational_cohort",
            criteria=criteria,
            criterion_results=results,
            criteria_completeness="complete",
        )
        
        assert arm_result["is_observational"] is True
        assert arm_result["study_type"] == "observational_cohort"


class TestTrialLevelAggregation:
    """Test trial-level roll-up from per-arm results (§8.3).
    
    Per §8.3: "A trial is ineligible only when every arm is."
    Roll-up priority (best to worst):
    - Any eligible_pending_review → trial eligible_pending_review
    - Any needs_chart_review (and none better) → trial needs_chart_review
    - Any manual_review (and none better) → trial manual_review
    - All ineligible → trial ineligible
    
    Note: Trial aggregation uses TrialAggregator (aggregate.py), not TrialLevelAggregator.
    """
    
    def test_one_arm_eligible_trial_eligible_even_if_other_ineligible(self):
        """Patient eligible for any arm → trial eligible. (Not all ineligible means not ineligible.)"""
        per_arm = [
            {
                "arm_id": "arm_a",
                "arm_eligibility_state": EligibilityState.INELIGIBLE.value,
            },
            {
                "arm_id": "arm_b",
                "arm_eligibility_state": EligibilityState.ELIGIBLE_PENDING_REVIEW.value,
            },
        ]
        
        trial_state, _ = TrialAggregator.aggregate(per_arm)
        
        # Per §8.3: not all ineligible → trial NOT ineligible
        # Any eligible_pending_review → trial eligible_pending_review
        assert trial_state == EligibilityState.ELIGIBLE_PENDING_REVIEW.value
    
    def test_all_arms_ineligible_trial_ineligible(self):
        """Only when every arm ineligible → trial ineligible."""
        per_arm = [
            {
                "arm_id": "arm_a",
                "arm_eligibility_state": EligibilityState.INELIGIBLE.value,
            },
            {
                "arm_id": "arm_b",
                "arm_eligibility_state": EligibilityState.INELIGIBLE.value,
            },
        ]
        
        trial_state, _ = TrialAggregator.aggregate(per_arm)
        
        assert trial_state == EligibilityState.INELIGIBLE.value
    
    def test_any_arm_eligible_trial_eligible_pending_review(self):
        """Any arm eligible_pending_review → trial eligible_pending_review (best state)."""
        per_arm = [
            {
                "arm_id": "arm_a",
                "arm_eligibility_state": EligibilityState.NEEDS_CHART_REVIEW.value,
            },
            {
                "arm_id": "arm_b",
                "arm_eligibility_state": EligibilityState.ELIGIBLE_PENDING_REVIEW.value,
            },
        ]
        
        trial_state, _ = TrialAggregator.aggregate(per_arm)
        
        assert trial_state == EligibilityState.ELIGIBLE_PENDING_REVIEW.value
    
    def test_any_arm_needs_chart_review_trial_needs_chart_review(self):
        """Any arm needs_chart_review (and none eligible) → trial needs_chart_review."""
        per_arm = [
            {
                "arm_id": "arm_a",
                "arm_eligibility_state": EligibilityState.MANUAL_REVIEW.value,
            },
            {
                "arm_id": "arm_b",
                "arm_eligibility_state": EligibilityState.NEEDS_CHART_REVIEW.value,
            },
        ]
        
        trial_state, _ = TrialAggregator.aggregate(per_arm)
        
        # needs_chart_review > manual_review (priority)
        assert trial_state == EligibilityState.NEEDS_CHART_REVIEW.value
    
    def test_any_arm_manual_review_trial_manual_review(self):
        """Any arm manual_review (and none better) → trial manual_review."""
        per_arm = [
            {
                "arm_id": "arm_a",
                "arm_eligibility_state": EligibilityState.INELIGIBLE.value,
            },
            {
                "arm_id": "arm_b",
                "arm_eligibility_state": EligibilityState.MANUAL_REVIEW.value,
            },
        ]
        
        trial_state, _ = TrialAggregator.aggregate(per_arm)
        
        # manual_review > ineligible (not all ineligible)
        assert trial_state == EligibilityState.MANUAL_REVIEW.value


class TestStudyTypeAnnotation:
    """Test study-type context annotation on results."""
    
    def test_study_type_annotated_on_results(self):
        """Criterion results annotated with study_type and is_observational."""
        results = [
            {
                "criterion_id": "crit_1",
                "outcome": Outcome.SATISFIED.value,
            }
        ]
        
        annotated = PerArmMatcher._apply_study_type_inversion(results, "observational_cohort")
        
        assert annotated[0]["study_type"] == "observational_cohort"
        assert annotated[0]["is_observational"] is True
    
    def test_interventional_not_marked_observational(self):
        """Interventional study not marked as observational."""
        results = [
            {
                "criterion_id": "crit_1",
                "outcome": Outcome.SATISFIED.value,
            }
        ]
        
        annotated = PerArmMatcher._apply_study_type_inversion(results, "interventional")
        
        assert annotated[0]["study_type"] == "interventional"
        assert annotated[0]["is_observational"] is False


class TestIntegrationMultiArm:
    """Integration test: multi-arm trial with mixed states."""
    
    def test_three_arm_trial_best_arm_wins(self):
        """Three-arm trial: eligible wins (per §8.3 'not all ineligible means not ineligible')."""
        criteria = [
            {"criterion_id": "inc_all", "arm_scope": None, "atoms": []},
            {"criterion_id": "exc_a", "arm_scope": "arm_a", "atoms": []},
            {"criterion_id": "exc_b", "arm_scope": "arm_b", "atoms": []},
        ]
        
        # Arm A: hard disqualifier → ineligible
        arm_a_results = [
            {
                "criterion_id": "inc_all",
                "outcome": Outcome.SATISFIED.value,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
            {
                "criterion_id": "exc_a",
                "outcome": Outcome.RESOLVED_DISQUALIFIER.value,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
        ]
        
        # Arm B: unresolved → needs_chart_review
        arm_b_results = [
            {
                "criterion_id": "inc_all",
                "outcome": Outcome.SATISFIED.value,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
            {
                "criterion_id": "exc_b",
                "outcome": Outcome.UNRESOLVED.value,
                "hardness": "hard",
                "evaluation_state": "missing",
                "coverage": "unknown",
            },
        ]
        
        # Arm C: all satisfied → eligible_pending_review (BEST)
        arm_c_results = [
            {
                "criterion_id": "inc_all",
                "outcome": Outcome.SATISFIED.value,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
            }
        ]
        
        arm_a = PerArmMatcher.evaluate_arm(
            "arm_a", "interventional", criteria, arm_a_results, "complete"
        )
        arm_b = PerArmMatcher.evaluate_arm(
            "arm_b", "interventional", criteria, arm_b_results, "complete"
        )
        arm_c = PerArmMatcher.evaluate_arm(
            "arm_c", "interventional", criteria, arm_c_results, "complete"
        )
        
        # Arm states as expected
        assert arm_a["arm_eligibility_state"] == EligibilityState.INELIGIBLE.value
        assert arm_b["arm_eligibility_state"] == EligibilityState.NEEDS_CHART_REVIEW.value
        assert arm_c["arm_eligibility_state"] == EligibilityState.ELIGIBLE_PENDING_REVIEW.value
        
        # Trial level: best arm wins (arm_c is eligible)
        # Per §8.3: patient qualifies for ≥1 arm → trial NOT ineligible
        trial_state, _ = TrialAggregator.aggregate([arm_a, arm_b, arm_c])
        assert trial_state == EligibilityState.ELIGIBLE_PENDING_REVIEW.value

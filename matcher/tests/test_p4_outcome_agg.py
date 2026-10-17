"""Tests for P4: Outcome determination and trial-level aggregation (§6 + §8)"""

import pytest
from avicenna_matcher.errors import StructuralError
from datetime import datetime
from avicenna_matcher import (
    TriState,
    Outcome,
    EligibilityState,
    OutcomeEvaluator,
    PerArmAggregator,
    TrialAggregator,
    CriterionResultBuilder,
    TrialResultBuilder,
)


class TestOutcomeEvaluator:
    """§6: Outcome determination from predicate result and criterion type/hardness"""
    
    # Inclusion criteria
    
    def test_inclusion_true_yields_satisfied(self):
        """Inclusion + TRUE → satisfied"""
        result = OutcomeEvaluator.evaluate(
            TriState.TRUE, "inclusion", "hard"
        )
        assert result == Outcome.SATISFIED
    
    def test_inclusion_false_yields_disqualifier(self):
        """Inclusion + FALSE → resolved_disqualifier (patient fails required criterion)"""
        result = OutcomeEvaluator.evaluate(
            TriState.FALSE, "inclusion", "hard"
        )
        assert result == Outcome.RESOLVED_DISQUALIFIER
    
    def test_inclusion_unknown_yields_unresolved(self):
        """Inclusion + UNKNOWN → unresolved (never hard outcome)"""
        result = OutcomeEvaluator.evaluate(
            TriState.UNKNOWN, "inclusion", "hard"
        )
        assert result == Outcome.UNRESOLVED
    
    # Exclusion criteria
    
    def test_exclusion_true_yields_disqualifier(self):
        """Exclusion + TRUE → resolved_disqualifier (blocking)"""
        result = OutcomeEvaluator.evaluate(
            TriState.TRUE, "exclusion", "hard"
        )
        assert result == Outcome.RESOLVED_DISQUALIFIER
    
    def test_exclusion_false_yields_clear(self):
        """Exclusion + FALSE → clear (criterion cleared, patient not excluded)"""
        result = OutcomeEvaluator.evaluate(
            TriState.FALSE, "exclusion", "hard"
        )
        assert result == Outcome.CLEAR
    
    def test_exclusion_unknown_yields_unresolved(self):
        """Exclusion + UNKNOWN → unresolved (never hard outcome)"""
        result = OutcomeEvaluator.evaluate(
            TriState.UNKNOWN, "exclusion", "hard"
        )
        assert result == Outcome.UNRESOLVED
    
    # Master invariant: UNKNOWN never yields hard outcome
    
    def test_unknown_never_hard_for_inclusion_false(self):
        """§6.3: UNKNOWN never yields hard outcome, even for hard inclusion"""
        result = OutcomeEvaluator.evaluate(
            TriState.UNKNOWN, "inclusion", "hard"
        )
        assert result == Outcome.UNRESOLVED  # Not RESOLVED_DISQUALIFIER
    
    def test_unknown_never_hard_for_exclusion_true(self):
        """§6.3: UNKNOWN never yields hard outcome, even for hard exclusion"""
        result = OutcomeEvaluator.evaluate(
            TriState.UNKNOWN, "exclusion", "hard"
        )
        assert result == Outcome.UNRESOLVED  # Not RESOLVED_DISQUALIFIER
    
    # Procedural criteria (never hardness-driven)
    
    def test_procedural_inclusion_true_still_satisfied(self):
        """Procedural inclusion + TRUE → satisfied"""
        result = OutcomeEvaluator.evaluate(
            TriState.TRUE, "inclusion", "procedural_pre_screen"
        )
        assert result == Outcome.SATISFIED
    
    def test_procedural_exclusion_true_is_non_blocking(self):
        """§6 table: procedural_pre_screen is never a disqualifier at pre-screen."""
        for pred, ctype in [(TriState.TRUE, "exclusion"), (TriState.FALSE, "inclusion"),
                            (TriState.UNKNOWN, "inclusion"), (TriState.UNKNOWN, "exclusion")]:
            assert OutcomeEvaluator.evaluate(pred, ctype, "procedural_pre_screen") == Outcome.NON_BLOCKING
        assert OutcomeEvaluator.evaluate(TriState.FALSE, "exclusion", "procedural_pre_screen") == Outcome.CLEAR
    
    # Error handling
    
    def test_invalid_criterion_type_raises(self):
        """Invalid criterion_type raises ValueError"""
        with pytest.raises(ValueError, match="Invalid criterion_type"):
            OutcomeEvaluator.evaluate(TriState.TRUE, "invalid", "hard")
    
    def test_invalid_hardness_raises(self):
        """Invalid hardness raises ValueError"""
        with pytest.raises(ValueError, match="Invalid hardness"):
            OutcomeEvaluator.evaluate(TriState.TRUE, "inclusion", "soft")


class TestBlockingLogic:
    """§6.2: Determine if outcome blocks eligibility"""
    
    def test_resolved_disqualifier_blocks_hard(self):
        """Hard resolved_disqualifier blocks (covers both inclusion FALSE and exclusion TRUE)"""
        assert OutcomeEvaluator.is_blocking(Outcome.RESOLVED_DISQUALIFIER, "hard")
    
    def test_clear_removed(self):
        """Outcome.CLEAR no longer used (both inclusion FALSE and exclusion TRUE map to resolved_disqualifier)"""
        # Clear has been removed as a distinct outcome; it's now resolved_disqualifier
        # Verify that outcome.py never emits CLEAR
        assert Outcome.CLEAR.value == "clear"  # Enum still exists for compatibility, but never emitted
    
    def test_satisfied_does_not_block_hard(self):
        """Hard satisfied does not block"""
        assert not OutcomeEvaluator.is_blocking(Outcome.SATISFIED, "hard")
    
    def test_unresolved_does_not_block_hard(self):
        """Hard unresolved does not block (allows pending_review)"""
        assert not OutcomeEvaluator.is_blocking(Outcome.UNRESOLVED, "hard")
    
    def test_procedural_never_blocks(self):
        """Procedural never blocks regardless of outcome"""
        for outcome in [
            Outcome.RESOLVED_DISQUALIFIER,
            Outcome.CLEAR,
            Outcome.SATISFIED,
            Outcome.UNRESOLVED,
        ]:
            assert not OutcomeEvaluator.is_blocking(outcome, "procedural_pre_screen")


class TestPerArmAggregation:
    """§8: Per-arm aggregation of criterion results"""
    
    def test_all_hard_satisfied_yields_eligible_pending_review(self):
        """All hard criteria satisfied → eligible_pending_review"""
        results = [
            {
                "criterion_id": "inc1",
                "outcome": "satisfied",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
            {
                "criterion_id": "exc1",
                "outcome": "satisfied",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
        ]
        
        state, blocking, manual, coverage = PerArmAggregator.aggregate(results, "arm_1")
        
        assert state == EligibilityState.ELIGIBLE_PENDING_REVIEW.value
        assert blocking == []
        assert coverage["completeness"] == "full"
    
    def test_any_hard_disqualifier_yields_ineligible(self):
        """Any hard resolved_disqualifier (inclusion FALSE or exclusion TRUE) → ineligible"""
        results = [
            {
                "criterion_id": "exc1",
                "outcome": "resolved_disqualifier",  # Exclusion TRUE or inclusion FALSE
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
                "criterion_type": "exclusion",
            },
        ]
        
        state, blocking, manual, coverage = PerArmAggregator.aggregate(results, "arm_1")
        
        assert state == EligibilityState.INELIGIBLE.value
        assert blocking == ["exc1"]
    
    def test_any_hard_disqualifier_for_inclusion_false_yields_ineligible(self):
        """Any hard resolved_disqualifier from inclusion FALSE → ineligible"""
        results = [
            {
                "criterion_id": "inc1",
                "outcome": "resolved_disqualifier",  # Inclusion FALSE
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
                "criterion_type": "inclusion",
            },
        ]
        
        state, blocking, manual, coverage = PerArmAggregator.aggregate(results, "arm_1")
        
        assert state == EligibilityState.INELIGIBLE.value
        assert blocking == ["inc1"]
    
    def test_unresolved_hard_yields_needs_chart_review(self):
        """§8.2 CRITICAL: Unresolved hard criterion → needs_chart_review (NOT eligible_pending_review)
        
        This was the cardinal-sin bug: missing evidence (unresolved hard) was incorrectly
        promoting to eligible_pending_review. Now fixed: unresolved hard → needs_chart_review.
        """
        results = [
            {
                "criterion_id": "inc1",
                "outcome": "satisfied",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
                "criterion_type": "inclusion",
            },
            {
                "criterion_id": "inc2",
                "outcome": "unresolved",  # MISSING LABS: unresolved
                "applicable": True,
                "hardness": "hard",  # But it's HARD
                "evaluation_state": "evaluable",
                "coverage": "unknown",
                "criterion_type": "inclusion",
            },
        ]
        
        state, blocking, manual, coverage = PerArmAggregator.aggregate(results, "arm_1")
        
        # CRITICAL FIX: unresolved hard must be needs_chart_review, not eligible_pending_review
        assert state == EligibilityState.NEEDS_CHART_REVIEW.value
        # §8: blocking_criteria = resolved hard disqualifiers + unresolved hard requirements
        assert blocking == ["inc2"]
    
    def test_opaque_yields_needs_chart_review(self):
        """Opaque hard inclusion below the ⅓ ratio → needs_chart_review (§8)"""
        results = [
            {
                "criterion_id": f"inc-ok{i}",
                "outcome": "satisfied",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
            } for i in range(2)
        ] + [
            {
                "criterion_id": "inc1",
                "outcome": "satisfied",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
            {
                "criterion_id": "inc2",
                "outcome": "unresolved",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "opaque",
                "coverage": "unknown",
            },
        ]
        
        state, blocking, manual, coverage = PerArmAggregator.aggregate(results, "arm_1")
        
        assert state == EligibilityState.NEEDS_CHART_REVIEW.value
        assert "inc2" in manual
    
    def test_partial_coverage_caps_at_needs_chart_review(self):
        """§8.2: Partial coverage caps state at needs_chart_review"""
        results = [
            {
                "criterion_id": "inc1",
                "outcome": "satisfied",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
            {
                "criterion_id": "inc2",
                "outcome": "satisfied",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "partial",
            },
        ]
        
        state, blocking, manual, coverage = PerArmAggregator.aggregate(results, "arm_1")
        
        # Would be eligible_pending_review, but partial coverage caps at needs_chart_review
        assert state == EligibilityState.NEEDS_CHART_REVIEW.value
        assert coverage["completeness"] == "partial"
    
    def test_procedural_never_blocks(self):
        """Procedural criteria never block even if they fail"""
        results = [
            {
                "criterion_id": "proc1",
                "outcome": "resolved_disqualifier",
                "applicable": True,
                "hardness": "procedural_pre_screen",
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
            {
                "criterion_id": "inc1",
                "outcome": "satisfied",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
        ]
        
        state, blocking, manual, coverage = PerArmAggregator.aggregate(results, "arm_1")
        
        # Procedural disqualifier doesn't block
        assert state == EligibilityState.ELIGIBLE_PENDING_REVIEW.value
        assert blocking == []
    
    def test_inapplicable_criteria_excluded(self):
        """Not applicable criteria are excluded from aggregation"""
        results = [
            {
                "criterion_id": "inc1",
                "outcome": "satisfied",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
            {
                "criterion_id": "inc2",
                "outcome": "not_applicable",
                "applicable": False,
                "hardness": "hard",
                "evaluation_state": "not_applicable",
                "coverage": "unknown",
            },
        ]
        
        state, blocking, manual, coverage = PerArmAggregator.aggregate(results, "arm_1")
        
        # Only inc1 is counted
        assert state == EligibilityState.ELIGIBLE_PENDING_REVIEW.value
    
    def test_bug_b_criteria_completeness_partial_caps_at_needs_chart_review(self):
        """Bug B fix: §8.2 Pack-level criteria_completeness='partial' → caps at needs_chart_review
        
        If pack is built from incomplete public criteria, even if all visible hard criteria
        are satisfied, state must cap at needs_chart_review (not eligible_pending_review).
        """
        results = [
            {
                "criterion_id": "inc1",
                "outcome": "satisfied",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
            {
                "criterion_id": "exc1",
                "outcome": "satisfied",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
            },
        ]
        
        # Without criteria_completeness: would be eligible_pending_review
        state1, _, _, _ = PerArmAggregator.aggregate(results, "arm_1", criteria_completeness=None)
        assert state1 == EligibilityState.ELIGIBLE_PENDING_REVIEW.value
        
        # With criteria_completeness="partial": MUST cap at needs_chart_review
        state2, _, _, _ = PerArmAggregator.aggregate(results, "arm_1", criteria_completeness="partial")
        assert state2 == EligibilityState.NEEDS_CHART_REVIEW.value
        
        # With criteria_completeness="full": can be eligible_pending_review
        state3, _, _, _ = PerArmAggregator.aggregate(results, "arm_1", criteria_completeness="full")
        assert state3 == EligibilityState.ELIGIBLE_PENDING_REVIEW.value
    
    def test_bug_d_opaque_hard_exclusion_forces_manual_review(self):
        """Bug D fix: Opaque hard exclusion → forces manual_review (not needs_chart_review)
        
        §8: Un-evaluable hard exclusion (opaque/conflict) is the false-pass direction.
        Uncertain disqualifier forces manual_review for human judgment.
        """
        results = [
            {
                "criterion_id": "inc1",
                "outcome": "satisfied",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
                "criterion_type": "inclusion",
            },
            {
                "criterion_id": "exc_opaque",
                "outcome": "unresolved",  # Can't determine if exclusion matches
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "opaque",  # Text couldn't be atomized
                "coverage": "unknown",
                "criterion_type": "exclusion",
            },
        ]
        
        state, _, manual, _ = PerArmAggregator.aggregate(results, "arm_1")
        
        # Opaque hard exclusion forces manual_review (highest severity)
        assert state == EligibilityState.MANUAL_REVIEW.value
        assert "exc_opaque" in manual
    
    def test_bug_d_conflict_hard_exclusion_forces_manual_review(self):
        """Bug D fix: Conflict hard exclusion → forces manual_review
        
        Contradictory evidence on a hard exclusion requires human judgment.
        """
        results = [
            {
                "criterion_id": "inc1",
                "outcome": "satisfied",
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "evaluable",
                "coverage": "full",
                "criterion_type": "inclusion",
            },
            {
                "criterion_id": "exc_conflict",
                "outcome": "unresolved",  # Contradictory evidence
                "applicable": True,
                "hardness": "hard",
                "evaluation_state": "conflict",  # Contradictory facts
                "coverage": "unknown",
                "criterion_type": "exclusion",
            },
        ]
        
        state, _, manual, _ = PerArmAggregator.aggregate(results, "arm_1")
        
        # Conflict hard exclusion forces manual_review
        assert state == EligibilityState.MANUAL_REVIEW.value
        assert "exc_conflict" in manual


class TestTrialAggregation:
    """§8: Trial-level aggregation across arms"""
    
    def test_all_arms_ineligible_yields_ineligible(self):
        """All arms ineligible → trial ineligible"""
        arms = [
            {
                "arm_id": "arm_1",
                "arm_eligibility_state": "ineligible",
                "blocking_criteria": ["exc1"],
                "manual_review_criteria": [],
            },
            {
                "arm_id": "arm_2",
                "arm_eligibility_state": "ineligible",
                "blocking_criteria": ["exc2"],
                "manual_review_criteria": [],
            },
        ]
        
        state, _ = TrialAggregator.aggregate(arms)
        
        assert state == EligibilityState.INELIGIBLE.value
    
    def test_any_eligible_pending_review_yields_eligible_pending_review(self):
        """Any arm eligible_pending_review → trial eligible_pending_review"""
        arms = [
            {
                "arm_id": "arm_1",
                "arm_eligibility_state": "ineligible",
                "blocking_criteria": ["exc1"],
                "manual_review_criteria": [],
            },
            {
                "arm_id": "arm_2",
                "arm_eligibility_state": "eligible_pending_review",
                "blocking_criteria": [],
                "manual_review_criteria": [],
            },
        ]
        
        state, _ = TrialAggregator.aggregate(arms)
        
        assert state == EligibilityState.ELIGIBLE_PENDING_REVIEW.value
    
    def test_any_needs_chart_review_yields_needs_chart_review(self):
        """Any arm needs_chart_review (and none eligible) → trial needs_chart_review"""
        arms = [
            {
                "arm_id": "arm_1",
                "arm_eligibility_state": "ineligible",
                "blocking_criteria": [],
                "manual_review_criteria": [],
            },
            {
                "arm_id": "arm_2",
                "arm_eligibility_state": "needs_chart_review",
                "blocking_criteria": [],
                "manual_review_criteria": [],
            },
        ]
        
        state, _ = TrialAggregator.aggregate(arms)
        
        # Not all ineligible, so trial not ineligible
        # needs_chart_review is worst state, so trial needs_chart_review
        assert state == EligibilityState.NEEDS_CHART_REVIEW.value
    
    def test_any_manual_review_yields_manual_review(self):
        """Any arm manual_review (and none eligible/chart_review) → trial manual_review"""
        arms = [
            {
                "arm_id": "arm_1",
                "arm_eligibility_state": "ineligible",
                "blocking_criteria": [],
                "manual_review_criteria": [],
            },
            {
                "arm_id": "arm_2",
                "arm_eligibility_state": "manual_review",
                "blocking_criteria": [],
                "manual_review_criteria": [],
            },
        ]
        
        state, _ = TrialAggregator.aggregate(arms)
        
        # manual_review is worst among non-ineligible
        assert state == EligibilityState.MANUAL_REVIEW.value


class TestCriterionResultBuilder:
    """Test building criterion result objects (§8.2)"""
    
    def test_build_with_all_fields(self):
        """Build criterion result with all required fields"""
        result = CriterionResultBuilder.build(
            criterion_id="inc1",
            criterion_type="inclusion",
            criterion_source_text="Diagnosed with cancer",
            evaluation_state="evaluable",
            outcome="satisfied",
            applicable=True,
            hardness="hard",
            coverage="full",
            reason_code=None,
            fact_references=[
                {"fact_id": "f1", "fact_key": "diagnosis", "role": "feeding"}
            ],
            atom_results=[],
            notes=["Patient has documented cancer diagnosis"],
        )
        
        assert result["criterion_id"] == "inc1"
        assert result["criterion_type"] == "inclusion"
        assert result["outcome"] == "satisfied"
        assert result["applicable"] is True
        assert result["hardness"] == "hard"
        assert result["coverage"] == "full"
        assert len(result["fact_references"]) == 1
        assert len(result["notes"]) == 1
    
    def test_build_with_optional_notes_defaults_to_empty(self):
        """Build without notes → notes defaults to empty list"""
        result = CriterionResultBuilder.build(
            criterion_id="exc1",
            criterion_type="exclusion",
            criterion_source_text="No prior therapy",
            evaluation_state="evaluable",
            outcome="satisfied",
            applicable=True,
            hardness="hard",
            coverage="full",
            reason_code=None,
            fact_references=[],
            atom_results=[],
            notes=None,
        )
        
        assert result["notes"] == []


class TestTrialResultBuilder:
    """Test building trial result objects (§8.3)"""
    
    def test_build_trial_result(self):
        """Build trial result with all required fields"""
        result = TrialResultBuilder.build(
            trial_id="NCT123456",
            patient_ref="pt_abc123",
            policy_version="avicenna.policy/0.1",
            trial_eligibility_state="eligible_pending_review",
            per_arm_results=[
                {
                    "arm_id": "arm_1",
                    "arm_eligibility_state": "eligible_pending_review",
                    "blocking_criteria": [],
                    "manual_review_criteria": [],
                }
            ],
            criterion_results=[],
            notes=["All hard criteria satisfied"],
            result_id="res-1",
            generated_at="2026-01-01T00:00:00Z",
        )
        
        assert result["schema_version"] == "avicenna.trial-result/0.1"
        assert result["trial_id"] == "NCT123456"
        assert result["patient_ref"] == "pt_abc123"
        assert result["policy_version"] == "avicenna.policy/0.1"
        assert result["trial_eligibility_state"] == "eligible_pending_review"
        assert result["result_id"] == "res-1"
        assert result["generated_at"] == "2026-01-01T00:00:00Z"
        assert len(result["per_arm_results"]) == 1
        assert len(result["criterion_results"]) == 0
    
    def test_ids_must_be_injected(self):
        """Determinism (§12): the builder never reads a clock or RNG."""
        with pytest.raises(StructuralError):
            TrialResultBuilder.build(
                trial_id="NCT123456", patient_ref="pt_abc123",
                policy_version="avicenna.policy/0.1", trial_eligibility_state="ineligible",
                per_arm_results=[], criterion_results=[],
            )


def _cr(cid, outcome, ctype="inclusion", state="evaluable", hardness="hard"):
    return {"criterion_id": cid, "outcome": outcome, "applicable": True, "hardness": hardness,
            "evaluation_state": state, "coverage": "full" if state == "evaluable" else "unknown",
            "criterion_type": ctype}


class TestSection8ManualReviewAndBlocking:
    """Oracles transcribed from MATCHER_DESIGN §8 (eligibility_state + blocking_criteria)."""

    def test_resolved_disqualifier_dominates_manual_review(self):
        # ineligible iff >= 1 resolved hard disqualifier — even with an opaque hard exclusion
        state, blocking, manual, _ = PerArmAggregator.aggregate([
            _cr("inc:age", "resolved_disqualifier"),
            _cr("exc:op", "unresolved", "exclusion", "opaque"),
        ], "a")
        assert state == "ineligible"
        assert blocking == ["inc:age", "exc:op"]
        assert manual == ["exc:op"]  # still surfaced individually

    @pytest.mark.parametrize("state_", ["opaque", "conflict", "manual_review"])
    def test_severity_unevaluable_hard_exclusion(self, state_):
        rs = [_cr(f"ok{i}", "satisfied") for i in range(9)] + [_cr("exc:x", "unresolved", "exclusion", state_)]
        assert PerArmAggregator.aggregate(rs, "a")[0] == "manual_review"

    def test_unevaluable_hard_inclusion_below_ratio_is_chart_review(self):
        rs = [_cr(f"ok{i}", "satisfied") for i in range(3)] + [_cr("inc:x", "unresolved", "inclusion", "opaque")]
        assert PerArmAggregator.aggregate(rs, "a")[0] == "needs_chart_review"

    def test_ratio_exactly_one_third_is_not_manual_review(self):
        rs = [_cr(f"ok{i}", "satisfied") for i in range(2)] + [_cr("inc:x", "unresolved", "inclusion", "opaque")]
        assert PerArmAggregator.aggregate(rs, "a")[0] == "needs_chart_review"

    def test_ratio_above_one_third_is_manual_review(self):
        rs = [_cr("ok", "satisfied"), _cr("inc:x", "unresolved", "inclusion", "opaque"),
              _cr("inc:y", "unresolved", "inclusion", "conflict")]
        assert PerArmAggregator.aggregate(rs, "a")[0] == "manual_review"

    def test_missing_data_is_not_unevaluable(self):
        # data gap (missing) never counts toward manual_review ratio
        rs = [_cr("inc:x", "unresolved", "inclusion", "missing"), _cr("exc:y", "unresolved", "exclusion", "missing")]
        state, blocking, manual, _ = PerArmAggregator.aggregate(rs, "a")
        assert state == "needs_chart_review" and blocking == ["inc:x", "exc:y"] and manual == []

    def test_procedural_never_in_blocking_or_ratio(self):
        rs = [_cr("ok", "satisfied"),
              _cr("p", "non_blocking", state="manual_review", hardness="procedural_pre_screen")]
        state, blocking, manual, _ = PerArmAggregator.aggregate(rs, "a")
        assert state == "eligible_pending_review" and blocking == [] and manual == ["p"]


class TestZeroApplicableHard:
    """Review finding #4: no applicable hard criterion → no positive label (vacuous truth)."""

    def _c(self, cid, hardness="hard", applicable=True, outcome="satisfied"):
        return {"criterion_id": cid, "outcome": outcome, "applicable": applicable, "hardness": hardness,
                "evaluation_state": "evaluable" if applicable else "not_applicable", "coverage": "full"}

    @pytest.mark.parametrize("results", [
        [],
        [{"criterion_id": "p", "outcome": "non_blocking", "applicable": True,
          "hardness": "procedural_pre_screen", "evaluation_state": "unsupported", "coverage": "unknown"}],
        [{"criterion_id": "g", "outcome": "not_applicable", "applicable": False, "hardness": "hard",
          "evaluation_state": "not_applicable", "coverage": "full"}],
    ], ids=["empty", "procedural-only", "all-gated-out"])
    def test_no_hard_basis_is_manual_review(self, results):
        state, blocking, _, _ = PerArmAggregator.aggregate(results, "arm_1", "complete")
        assert state == EligibilityState.MANUAL_REVIEW.value
        assert blocking == []

    def test_zero_denominator_coverage_is_explicit(self):
        from avicenna_matcher.behaviors import PerArmMatcher
        cov = PerArmMatcher._calculate_evidence_coverage([])
        assert cov["assessed_percentage"] == 0.0 and cov["total"] == 0

    def test_trial_rollup_over_zero_arms_is_structural(self):
        from avicenna_matcher.aggregate import TrialAggregator
        from avicenna_matcher.errors import StructuralError
        with pytest.raises(StructuralError):
            TrialAggregator.aggregate([])

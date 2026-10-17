"""Trial-level and arm-level aggregation of criterion results (MATCHER_DESIGN.md §8).

Per arm, over applicable criteria, in precedence order (first match wins):
1. ineligible: at least one hard criterion is resolved_disqualifier. It never comes from UNKNOWN.
2. manual_review:
   - no hard criterion is applicable (a positive label would be vacuous); or
   - severity: an un-evaluable (opaque / conflict / manual_review) hard exclusion; or
   - un-evaluable hard criteria / applicable hard criteria > MANUAL_REVIEW_RATIO.
3. needs_chart_review:
   - any unresolved hard criterion; or
   - the pack's criteria_completeness is partial; or
   - any non-procedural criterion with coverage other than full.
4. eligible_pending_review: otherwise. Every hard criterion is satisfied or clear, with full coverage. "Pending
   review" is the residual: enrollment still needs human confirmation (consent, procedural items).

procedural_pre_screen criteria never block and are outside the coverage denominator. Un-evaluable criteria of any
hardness are listed in manual_review_criteria. blocking_criteria = resolved hard disqualifiers + unresolved hard
criteria.

Trial roll-up is the BEST arm state, with precedence eligible_pending_review > needs_chart_review > manual_review >
ineligible. A trial is ineligible only when every arm is.
"""

from typing import List, Dict, Any, Optional, Set, Tuple
from .types import EligibilityState, Outcome, Hardness
from .errors import StructuralError


# §8 manual_review line (a policy_version knob): ratio of un-evaluable hard criteria.
MANUAL_REVIEW_RATIO = 1 / 3
UNEVALUABLE_STATES = ("opaque", "conflict", "manual_review")


class PerArmAggregator:
    """Aggregate per-criterion results to per-arm eligibility state."""
    
    @staticmethod
    def aggregate(
        criterion_results: List[Dict[str, Any]],
        arm_id: str,
        criteria_completeness: Optional[str] = None,
    ) -> Tuple[str, List[str], List[str], Dict[str, Any]]:
        """
        Aggregate criterion results for a single arm.
        
        §8: Produce arm-level eligibility state, blocking criteria list,
        manual review criteria list, and evidence coverage assessment.
        
        §8.2: If criteria_completeness is "partial" (pack was built from incomplete
        public criteria), cap arm state at needs_chart_review.
        
        Args:
            criterion_results: List of criterion result dicts with keys:
                - criterion_id, criterion_type, outcome, applicable, hardness,
                  evaluation_state, coverage, atom_results
            arm_id: The arm being evaluated
            criteria_completeness: Optional pack-level completeness flag:
                - "full" | "partial" | "unknown" | None
                - From pack.criteria_completeness; if "partial", caps state at needs_chart_review
        
        Returns:
            Tuple of (arm_eligibility_state, blocking_criteria[], manual_review_criteria[], evidence_coverage)
        
        Returns values:
            arm_eligibility_state: "ineligible" | "eligible_pending_review" | "needs_chart_review" | "manual_review"
            blocking_criteria: resolved hard disqualifiers + unresolved hard criteria (§8)
            manual_review_criteria: list of criterion_ids requiring review
            evidence_coverage: {"full": bool, "partial_count": int, "unknown_count": int, "completeness": "full" | "partial" | "unknown"}
        """
        
        # Filter: only applicable criteria for this arm
        applicable = [cr for cr in criterion_results if cr.get("applicable", True)]
        
        disqualifiers = []      # resolved hard disqualifiers
        unresolved_hard = []
        manual_review_criteria = []
        unevaluable_hard = []   # opaque / conflict / investigator-judgment, hard
        severity = False        # un-evaluable hard exclusion (§8 severity rule)
        hard_count = 0

        coverage_stats = {
            "full_count": 0,
            "partial_count": 0,
            "unknown_count": 0,
        }

        for cr in applicable:
            cid = cr.get("criterion_id")
            outcome = cr.get("outcome")
            hardness = cr.get("hardness", "hard")
            eval_state = cr.get("evaluation_state", "evaluable")
            coverage = cr.get("coverage", "unknown")
            criterion_type = cr.get("criterion_type", "inclusion")

            # Procedural pre-screen items are visible but never cap the arm; they are
            # outside the evidence-coverage denominator.
            if hardness == "procedural_pre_screen":
                pass
            elif coverage == "full":
                coverage_stats["full_count"] += 1
            elif coverage == "partial":
                coverage_stats["partial_count"] += 1
            else:
                coverage_stats["unknown_count"] += 1

            # Individual un-evaluable criteria are always surfaced (§8).
            if eval_state in UNEVALUABLE_STATES:
                manual_review_criteria.append(cid)

            if hardness != "hard":
                continue
            hard_count += 1
            if outcome == Outcome.RESOLVED_DISQUALIFIER.value:
                disqualifiers.append(cid)
            elif outcome == Outcome.UNRESOLVED.value:
                unresolved_hard.append(cid)
                if eval_state in UNEVALUABLE_STATES:
                    unevaluable_hard.append(cid)
                    if criterion_type == "exclusion":
                        severity = True

        # §8 eligibility_state:
        # 1. ineligible iff >= 1 resolved hard disqualifier (dominates everything; never from UNKNOWN)
        # 2. manual_review on severity (un-evaluable hard exclusion) OR
        #    ratio (un-evaluable hard / applicable hard) > MANUAL_REVIEW_RATIO
        # 3. needs_chart_review on any unresolved hard (incl. un-evaluable hard inclusions),
        #    partial pack completeness, or non-full per-criterion coverage
        # 4. otherwise eligible_pending_review
        ratio = (len(unevaluable_hard) / hard_count) if hard_count else 0.0
        if disqualifiers:
            arm_state = EligibilityState.INELIGIBLE.value
        elif hard_count == 0:
            # Nothing hard was applicable/evaluated: "every hard criterion satisfied" would be
            # vacuous. No positive label without a basis — a human must read the protocol.
            arm_state = EligibilityState.MANUAL_REVIEW.value
        elif severity or ratio > MANUAL_REVIEW_RATIO:
            arm_state = EligibilityState.MANUAL_REVIEW.value
        elif unresolved_hard:
            arm_state = EligibilityState.NEEDS_CHART_REVIEW.value
        elif criteria_completeness == "partial":
            arm_state = EligibilityState.NEEDS_CHART_REVIEW.value
        elif coverage_stats["partial_count"] > 0 or coverage_stats["unknown_count"] > 0:
            arm_state = EligibilityState.NEEDS_CHART_REVIEW.value
        else:
            arm_state = EligibilityState.ELIGIBLE_PENDING_REVIEW.value

        # §8: blocking_criteria = resolved hard disqualifiers + unresolved hard requirements
        # (in input order). The state, not list membership, says which kind blocks.
        blocking_ids = set(disqualifiers) | set(unresolved_hard)
        blocking_criteria = [cr.get("criterion_id") for cr in applicable
                             if cr.get("criterion_id") in blocking_ids]

        # Determine evidence completeness
        total_applicable = len(applicable)
        if coverage_stats["partial_count"] > 0 or coverage_stats["unknown_count"] > 0:
            completeness = "partial" if coverage_stats["partial_count"] > 0 else "unknown"
        else:
            completeness = "full" if total_applicable > 0 else "unknown"
        
        evidence_coverage = {
            "full": coverage_stats["full_count"] == total_applicable if total_applicable > 0 else False,
            "partial_count": coverage_stats["partial_count"],
            "unknown_count": coverage_stats["unknown_count"],
            "completeness": completeness,
        }
        
        return arm_state, blocking_criteria, manual_review_criteria, evidence_coverage


class TrialAggregator:
    """Aggregate per-arm results to trial-level eligibility state."""
    
    @staticmethod
    def aggregate(
        per_arm_results: List[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Aggregate per-arm eligibility states to trial-level state.
        
        §8: the trial takes the BEST arm state. Precedence: eligible_pending_review >
        needs_chart_review > manual_review > ineligible. The trial is ineligible only if every
        arm is ineligible.
        
        Args:
            per_arm_results: List of per-arm result dicts with:
                - arm_id, arm_eligibility_state, blocking_criteria[], manual_review_criteria[]
        
        Returns:
            Tuple of (trial_eligibility_state, per_arm_results_with_metadata)
        """
        
        if not per_arm_results:
            # ineligible requires a resolved disqualifier (§8); no arms is a pack defect.
            raise StructuralError("trial roll-up over zero arms")
        
        # Collect states
        states = [ar.get("arm_eligibility_state") for ar in per_arm_results]
        
        # Per §8.3, best_eligibility_state rolls up by precedence (check BEST first):
        # eligible_pending_review > needs_chart_review > manual_review > ineligible
        # (Trial ineligible only when every arm is)
        
        # Check for any eligible_pending_review (best possible)
        if EligibilityState.ELIGIBLE_PENDING_REVIEW.value in states:
            trial_state = EligibilityState.ELIGIBLE_PENDING_REVIEW.value
        # Check for any needs_chart_review
        elif EligibilityState.NEEDS_CHART_REVIEW.value in states:
            trial_state = EligibilityState.NEEDS_CHART_REVIEW.value
        # Check for any manual_review
        elif EligibilityState.MANUAL_REVIEW.value in states:
            trial_state = EligibilityState.MANUAL_REVIEW.value
        # Check for all ineligible (only then is trial ineligible)
        elif all(s == EligibilityState.INELIGIBLE.value for s in states):
            trial_state = EligibilityState.INELIGIBLE.value
        else:
            # Fallback (shouldn't reach here)
            trial_state = EligibilityState.INELIGIBLE.value
        
        return trial_state, per_arm_results


class CriterionResultBuilder:
    """Build a criterion result dict from evaluation components."""
    
    @staticmethod
    def build(
        criterion_id: str,
        criterion_type: str,
        criterion_source_text: str,
        evaluation_state: str,
        outcome: str,
        applicable: bool,
        hardness: str,
        coverage: str,
        reason_code: Optional[str],
        fact_references: List[Dict[str, str]],
        atom_results: List[Dict[str, Any]],
        notes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Build a criterion result dictionary.
        
        §8.2: Ensure all required fields are present for schema validation.
        
        Args:
            criterion_id: Unique criterion identifier
            criterion_type: "inclusion" or "exclusion"
            criterion_source_text: Verbatim or paraphrased source text
            evaluation_state: One of the EvaluationState enum values
            outcome: One of the Outcome enum values
            applicable: Whether criterion applies to this patient × arm
            hardness: "hard" or "procedural_pre_screen"
            coverage: "full", "partial", or "unknown"
            reason_code: Reason code for outcome (null if not needed)
            fact_references: List of fact references used
            atom_results: List of atom evaluation results
            notes: Optional notes or warnings
        
        Returns:
            Dictionary conforming to criterion_result.schema.json
        """
        return {
            "criterion_id": criterion_id,
            "criterion_type": criterion_type,
            "criterion_source_text": criterion_source_text,
            "evaluation_state": evaluation_state,
            "outcome": outcome,
            "applicable": applicable,
            "hardness": hardness,
            "coverage": coverage,
            "reason_code": reason_code,
            "fact_references": fact_references,
            "atom_results": atom_results,
            "notes": notes or [],
        }


class TrialResultBuilder:
    """Build a trial result dict conforming to trial_result.schema.json."""
    
    @staticmethod
    def build(
        trial_id: str,
        patient_ref: str,
        policy_version: str,
        trial_eligibility_state: str,
        per_arm_results: List[Dict[str, Any]],
        criterion_results: List[Dict[str, Any]],
        notes: Optional[List[str]] = None,
        result_id: Optional[str] = None,  # required; Optional only for keyword ergonomics
        generated_at: Optional[str] = None,  # required
    ) -> Dict[str, Any]:
        """
        Build a trial result dictionary.
        
        §8.3: Conform to trial_result.schema.json with all required fields.
        
        Args:
            trial_id: Registry trial identifier
            patient_ref: Opaque pseudonymous patient reference
            policy_version: Evaluation policy version used
            trial_eligibility_state: Trial-level eligibility state
            per_arm_results: List of per-arm result dicts
            criterion_results: List of criterion result dicts
            notes: Optional notes or warnings
            result_id: Optional result UUID (auto-generated if None) — must be injected for determinism
            generated_at: Optional ISO 8601 timestamp (auto-generated if None) — must be injected for determinism
        
        Returns:
            Dictionary conforming to trial_result.schema.json
        """
        # Determinism (§12, A9): identifiers are injected, never read from a clock/RNG.
        if not result_id or not generated_at:
            raise StructuralError("result_id and generated_at must be injected by the caller")
        
        return {
            "schema_version": "avicenna.trial-result/0.1",
            "result_id": result_id,
            "generated_at": generated_at,
            "trial_id": trial_id,
            "patient_ref": patient_ref,
            "policy_version": policy_version,
            "trial_eligibility_state": trial_eligibility_state,
            "per_arm_results": per_arm_results,
            "criterion_results": criterion_results,
            "notes": notes or [],
        }

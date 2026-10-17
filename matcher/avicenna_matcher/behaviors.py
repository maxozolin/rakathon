"""Per-arm matcher behaviors: filtering, study-type handling, jurisdiction guards.

§7: Three behaviors that determine which criteria apply to which patient-arm pairs:
1. Per-arm evaluation (§7.1) — criteria scoped to arms
2. Study-type-aware candidacy (§7.2) — observational labeling (healthy-volunteer inversion deferred)
3. Jurisdiction-keyed guards (§7.3) — site-specific context

This module implements:
- Criterion applicability filtering (arm_scope)
- Study-type labeling (observational vs interventional)
- Per-arm aggregation (via wrapped PerArmAggregator)
- Evidence coverage calculation (resolved vs unresolved applicable criteria)

Note: Trial-level roll-up is delegated to TrialAggregator (aggregate.py).
This module does not re-implement trial aggregation.
"""

from typing import List, Dict, Any, Optional, Tuple
from .aggregate import PerArmAggregator
from .outcome import OutcomeEvaluator, Outcome
from .types import EligibilityState


class PerArmMatcher:
    """Evaluate criteria applicable to a specific arm with study-type awareness."""
    
    @staticmethod
    def _is_criterion_applicable(
        criterion: Dict[str, Any],
        arm_id: str,
        patient_packet: Dict[str, Any],
        site_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Determine if a criterion applies to this patient-arm pair.
        
        A criterion is applicable if:
        1. Its arm_scope is null (whole trial) OR matches the arm_id
        2. No arm_scope exclusion applies
        
        Note: Applicability is different from evaluability. A criterion may be
        applicable but have guards (§5.3) that evaluate to UNKNOWN if site context
        is missing. Per §7.3, missing site context → guard UNKNOWN → predicate UNKNOWN,
        not criterion inapplicable.
        
        Args:
            criterion: Criterion dict with arm_scope, atoms
            arm_id: The arm being evaluated
            patient_packet: Patient facts
            site_context: Optional {country, site_id, ...}
        
        Returns:
            (is_applicable, reason_if_not)
        """
        # Check arm scope (the only true applicability gate)
        arm_scope = criterion.get("arm_scope")
        if arm_scope is not None and arm_scope != arm_id:
            return False, f"criterion scoped to arm {arm_scope}, not {arm_id}"
        
        # Note: Guard evaluation happens during predicate evaluation, not here.
        # Per §7.3, missing site_context means guard → UNKNOWN, but criterion
        # is still applicable (it just can't be fully evaluated).
        
        # Criterion applies to this arm
        return True, None
    
    @staticmethod
    def _filter_criteria_for_arm(
        criteria: List[Dict[str, Any]],
        arm_id: str,
        patient_packet: Dict[str, Any],
        site_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Filter criteria to those applicable to this arm.
        
        §7.1: Criteria with arm_scope matching or null apply; others are filtered out.
        Applicability guards (§5.3) are evaluated; missing site context → not applicable.
        
        Returns:
            List of applicable criteria (possibly empty)
        """
        applicable_criteria = []
        for criterion in criteria:
            is_applicable, _reason = PerArmMatcher._is_criterion_applicable(
                criterion, arm_id, patient_packet, site_context
            )
            if is_applicable:
                applicable_criteria.append(criterion)
        return applicable_criteria
    
    @staticmethod
    def _apply_study_type_inversion(
        criterion_results: List[Dict[str, Any]],
        study_type: str,
    ) -> List[Dict[str, Any]]:
        """
        Apply study-type-aware outcome interpretation.
        
        §7.2: For non-interventional studies, the semantics change:
        - Observational studies are not treatment candidacy (research design differs)
        - Tag results appropriately so consumers don't rank them as treatments
        
        Note on "healthy-volunteer": This is orthogonal to study_type.
        - study_type: research design (interventional vs observational variants)
        - healthy-volunteer status: patient population (healthy vs diseased)
        
        An arm may be marked healthy_volunteers separately; if so, the outcome
        interpretation for disease-related criteria would invert (disease inclusion
        becomes disqualifying). This requires a separate healthy_volunteers flag
        on the arm, which is not yet in the schema.
        
        Current implementation: Annotate with study_type + is_observational flag
        for consumer-side interpretation. Full inversion awaits schema amendment.
        
        Args:
            criterion_results: List of criterion results
            study_type: "interventional" | "observational" | "observational_cohort" | etc.
        
        Returns:
            Modified criterion results with study_type_context annotation
        """
        is_observational = study_type != "interventional"
        
        modified_results = []
        for cr in criterion_results:
            cr_copy = cr.copy()
            cr_copy["study_type"] = study_type
            cr_copy["is_observational"] = is_observational
            # Note: Once schema includes healthy_volunteers flag, add inversion logic here:
            # if arm.healthy_volunteers and cr["criterion_type"] == "inclusion":
            #     # Invert disease-related inclusions (absence of disease becomes required)
            #     if cr["outcome"] == Outcome.SATISFIED:
            #         cr_copy["outcome"] = Outcome.RESOLVED_DISQUALIFIER
            #     elif cr["outcome"] == Outcome.RESOLVED_DISQUALIFIER:
            #         cr_copy["outcome"] = Outcome.SATISFIED
            modified_results.append(cr_copy)
        
        return modified_results
    
    @staticmethod
    def _calculate_evidence_coverage(
        criterion_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Calculate evidence coverage (resolved vs unresolved applicable criteria).
        
        §8.2, §8.3: Evidence coverage denominator = applicable criteria per arm
        **after filtering**, excluding procedural_pre_screen and not_applicable.
        
        Numerator = criteria with resolved outcomes (not UNKNOWN/unresolved).
        
        Args:
            criterion_results: Filtered, applicable criteria results
        
        Returns:
            {
                'assessed_percentage': float (0-100),
                'unassessed_criteria': [str],  # criterion_ids with unresolved outcomes
                'total': int,
                'assessed': int,
                'unassessed': int,
            }
        """
        # Exclude procedural_pre_screen and not_applicable from denominator
        evaluable_criteria = [
            cr for cr in criterion_results
            if cr.get("hardness") != "procedural_pre_screen"
            and cr.get("outcome") != "not_applicable"
        ]
        
        if not evaluable_criteria:
            # Zero denominator: nothing was assessed, so coverage is 0 %, not 100 %.
            return {
                "assessed_percentage": 0.0,
                "unassessed_criteria": [],
                "total": 0,
                "assessed": 0,
                "unassessed": 0,
            }
        
        unassessed_ids = []
        for cr in evaluable_criteria:
            outcome = cr.get("outcome")
            # Unresolved outcomes: those with UNKNOWN (mapped to "unresolved" in output)
            if outcome == Outcome.UNRESOLVED.value or outcome == "unresolved":
                unassessed_ids.append(cr.get("criterion_id"))
        
        total = len(evaluable_criteria)
        assessed = total - len(unassessed_ids)
        assessed_pct = assessed / total * 100.0
        
        return {
            "assessed_percentage": assessed_pct,
            "unassessed_criteria": unassessed_ids,
            "total": total,
            "assessed": assessed,
            "unassessed": len(unassessed_ids),
        }
    
    @staticmethod
    def evaluate_arm(
        arm_id: str,
        study_type: str,
        criteria: List[Dict[str, Any]],
        criterion_results: List[Dict[str, Any]],
        criteria_completeness: Optional[str] = None,
        patient_packet: Optional[Dict[str, Any]] = None,
        site_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate a single arm: filter criteria, aggregate results, compute coverage.
        
        §7.1: Per-arm evaluation of applicable criteria.
        §7.2: Study-type labeling and inversion.
        §7.3: Jurisdiction guard handling (site_context).
        
        Args:
            arm_id: The arm identifier
            study_type: "interventional" | "observational" | "observational_cohort" | etc.
            criteria: Full list of criteria from pack (for filtering by arm_scope)
            criterion_results: Per-criterion evaluation results
            criteria_completeness: Pack-level completeness flag
            patient_packet: Patient packet (for applicability context)
            site_context: Optional site information {country, site_id, ...}
        
        Returns:
            {
                'arm_id': str,
                'arm_eligibility_state': str,
                'blocking_criteria': [str],
                'manual_review_criteria': [str],
                'evidence_coverage': {'assessed_percentage': float, 'unassessed_criteria': [str], ...},
                'study_type': str,
                'is_observational': bool,
            }
        """
        patient_packet = patient_packet or {}
        
        # Step 1: Filter criteria applicable to this arm
        applicable_criteria = PerArmMatcher._filter_criteria_for_arm(
            criteria, arm_id, patient_packet, site_context
        )
        
        # Step 2: Filter results to only those applicable
        applicable_crit_ids = {c.get("criterion_id") for c in applicable_criteria}
        applicable_results = [
            cr for cr in criterion_results
            if cr.get("criterion_id") in applicable_crit_ids
        ]
        
        # Step 3: Apply study-type context
        annotated_results = PerArmMatcher._apply_study_type_inversion(
            applicable_results, study_type
        )
        
        # Step 4: Aggregate to arm-level state
        arm_state, blocking_crit, manual_review_crit, _coverage_dict = PerArmAggregator.aggregate(
            annotated_results,
            arm_id,
            criteria_completeness,
        )
        
        # Step 5: Calculate evidence coverage
        coverage = PerArmMatcher._calculate_evidence_coverage(annotated_results)
        
        # Step 6: Assemble per-arm result
        return {
            "arm_id": arm_id,
            "arm_eligibility_state": arm_state,
            "blocking_criteria": blocking_crit,
            "manual_review_criteria": manual_review_crit,
            "evidence_coverage": {
                "assessed_percentage": coverage["assessed_percentage"],
                "applicable_count": coverage["total"],
                "unassessed_criteria": coverage["unassessed_criteria"],
            },
            "study_type": study_type,
            "is_observational": study_type != "interventional",
            "_debug": {
                "total_evaluable": coverage["total"],
                "assessed_count": coverage["assessed"],
                "unassessed_count": coverage["unassessed"],
            },
        }

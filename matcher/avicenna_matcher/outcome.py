"""Outcome determination from predicate evaluation.

§6: Given a predicate's evaluated result (TRUE/FALSE/UNKNOWN) and the criterion's
type (inclusion/exclusion) + hardness (hard/procedural), determine the criterion
outcome and its blocking status.

§6.1: Polarity
- Inclusion criterion: TRUE→satisfied, FALSE→clear, UNKNOWN→unresolved
- Exclusion criterion: TRUE→resolved_disqualifier, FALSE→satisfied, UNKNOWN→unresolved

§6.2: Hardness
- Hard: blocking if resolved_disqualifier (exclusion) or clear (inclusion)
- Procedural: never blocking (always non_blocking in aggregate)

§6.3: Master Outcome Rule
UNKNOWN can never yield hard outcome.
- If result is UNKNOWN: outcome is always unresolved (never hard clear/disqualifier)
- If result is TRUE/FALSE: outcome applies polarity + check hardness consistency
"""

from typing import Optional
from .types import TriState, Outcome, Hardness


class OutcomeEvaluator:
    """Determine criterion outcome from predicate result and criterion metadata."""
    
    @staticmethod
    def evaluate(
        predicate_result: TriState,
        criterion_type: str,  # "inclusion" or "exclusion"
        hardness: str,  # "hard" or "procedural_pre_screen"
    ) -> Outcome:
        """
        Determine criterion outcome based on predicate evaluation result.
        
        §6.1–§6.3: Apply polarity (criterion_type) and check that hard outcomes
        never come from UNKNOWN.
        
        Args:
            predicate_result: The TriState result from predicate evaluation
            criterion_type: "inclusion" or "exclusion"
            hardness: "hard" or "procedural_pre_screen"
        
        Returns:
            Outcome enum value
        
        Raises:
            ValueError: if criterion_type or hardness is invalid
        """
        if criterion_type not in ("inclusion", "exclusion"):
            raise ValueError(f"Invalid criterion_type: {criterion_type}")
        if hardness not in ("hard", "procedural_pre_screen"):
            raise ValueError(f"Invalid hardness: {hardness}")
        
        # §6 table: procedural_pre_screen is never a disqualifier and never "unresolved"
        # at pre-screen; anything other than a positive result is carried as non_blocking.
        if hardness == "procedural_pre_screen":
            if criterion_type == "inclusion" and predicate_result == TriState.TRUE:
                return Outcome.SATISFIED
            if criterion_type == "exclusion" and predicate_result == TriState.FALSE:
                return Outcome.CLEAR
            return Outcome.NON_BLOCKING

        # §6.3: UNKNOWN never yields hard outcome
        if predicate_result == TriState.UNKNOWN:
            return Outcome.UNRESOLVED
        
        # Apply polarity (§6.1: inclusion TRUE/FALSE, exclusion TRUE/FALSE)
        if criterion_type == "inclusion":
            if predicate_result == TriState.TRUE:
                # Inclusion satisfied: patient passes this criterion
                return Outcome.SATISFIED
            else:  # predicate_result == TriState.FALSE
                # Inclusion FALSE: patient fails this required criterion (blocks eligibility)
                return Outcome.RESOLVED_DISQUALIFIER
        else:  # criterion_type == "exclusion"
            if predicate_result == TriState.TRUE:
                # Exclusion TRUE: patient fails this disqualifier (blocks eligibility)
                return Outcome.RESOLVED_DISQUALIFIER
            else:  # predicate_result == TriState.FALSE
                # Exclusion FALSE: patient is not excluded (criterion cleared)
                return Outcome.CLEAR
    
    @staticmethod
    def is_blocking(
        outcome: Outcome,
        hardness: str,
    ) -> bool:
        """
        Determine if an outcome blocks eligibility.
        
        §6.2: Hard outcomes that block:
        - resolved_disqualifier (exclusion TRUE or inclusion FALSE)
        
        Outcomes that don't block:
        - satisfied (inclusion TRUE or exclusion FALSE)
        - clear (inclusion satisfied; criterion cleared)
        - unresolved (missing evidence)
        
        Procedural outcomes never block.
        
        Args:
            outcome: Criterion outcome
            hardness: "hard" or "procedural_pre_screen"
        
        Returns:
            True if outcome blocks eligibility
        """
        if hardness == "procedural_pre_screen":
            # Procedural never blocks
            return False
        elif hardness != "hard":
            raise ValueError(f"Invalid hardness: {hardness}")
        
        # Hard: only resolved_disqualifier blocks
        return outcome == Outcome.RESOLVED_DISQUALIFIER
    
    @staticmethod
    def requires_manual_review(
        outcome: Outcome,
        evaluation_state: str,  # e.g., "opaque", "conflict"
    ) -> bool:
        """
        Determine if an outcome requires manual review.
        
        Manual review is needed when:
        - outcome is unresolved AND evaluation_state is opaque/conflict/manual_review
        - outcome is non_blocking AND evaluation_state is manual_review
        
        Args:
            outcome: Criterion outcome
            evaluation_state: State of the evaluation
        
        Returns:
            True if manual review is needed
        """
        if evaluation_state in ("opaque", "manual_review"):
            return outcome == Outcome.UNRESOLVED
        elif evaluation_state == "conflict":
            return outcome in (Outcome.UNRESOLVED, Outcome.NON_BLOCKING)
        return False

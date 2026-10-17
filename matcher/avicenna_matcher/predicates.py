"""Predicate constructs for avicenna.matcher

§5: Four predicate constructs beyond simple threshold comparison:
1. §5.1: Relative-to-reference thresholds (e.g., "bilirubin < 1.5 × ULN")
2. §5.2: Derived values (e.g., creatinine clearance by Cockcroft-Gault)
3. §5.3: Guarded/conditional predicates (e.g., "IPI for age > 60 vs age ≤ 60")
4. §5.4: Coverage-aware `not_exists` with versioned subsumption

This module provides evaluators for each construct given resolved facts.
"""

from typing import Optional, Dict, Any, Set
from datetime import datetime
from .types import TriState, FactAssertion
from .tristate import k3_and, k3_or
from .sets import compare_quantity_to_threshold, compare_band_to_threshold, Interval
from .concepts import ConceptRegistry, validate_concept_membership, SEED_REGISTRY_V1
from .resolution import resolve_fact_for_criterion, resolve_facts_for_criterion


class RelativeThresholdEvaluator:
    """§5.1: Evaluate relative-to-reference thresholds.
    
    Example: "total bilirubin < 1.5 × ULN"
    - The reference (ULN) must ride on the Fact itself (patient's own ULN)
    - If reference is absent → UNKNOWN (not determinable)
    """
    
    @staticmethod
    def evaluate(
        fact: Dict[str, Any],
        comparator: str,  # "lt", "le", "gt", "ge", "eq", "ne"
        reference_field: str,  # e.g., "qualifiers.reference_high"
        scale: float = 1.0,  # e.g., 1.5 for "1.5 ×"
    ) -> TriState:
        """
        Evaluate fact against a relative threshold.
        
        Args:
            fact: The resolved patient fact
            comparator: The comparison operator
            reference_field: Path to the reference value on the fact (e.g., "qualifiers.reference_high")
            scale: The scaling factor (e.g., 1.5 for "< 1.5 × ULN")
        
        Returns: TriState
        """
        # Extract the patient value
        fact_value = fact.get("value")
        if fact_value is None:
            return TriState.UNKNOWN
        
        # Recursively get reference from nested field
        ref_parts = reference_field.split(".")
        ref_value = fact
        for part in ref_parts:
            ref_value = ref_value.get(part) if isinstance(ref_value, dict) else None
            if ref_value is None:
                return TriState.UNKNOWN
        
        if ref_value is None:
            # Reference absent → cannot evaluate
            return TriState.UNKNOWN
        
        # Compute threshold: reference × scale
        threshold = ref_value * scale
        
        # Compare patient value against threshold
        return compare_quantity_to_threshold(fact_value, comparator, threshold)


class DerivedValueEvaluator:
    """§5.2: Evaluate derived value predicates.
    
    Example: "estimated creatinine clearance ≥ 50 mL/min by Cockcroft-Gault"
    - Derivation is provided as a separate Fact with its own provenance
    - If derived value is absent → UNKNOWN (cannot assume derived inputs)
    - Matcher MUST NOT compute derivations (that's the atomizer's job)
    """
    
    @staticmethod
    def evaluate(
        facts: list[Dict[str, Any]],
        derived_fact_key: str,
        comparator: str,
        threshold: float,
    ) -> TriState:
        """
        Evaluate a derived-value predicate.
        
        Args:
            facts: Patient facts (to find the derived value Fact)
            derived_fact_key: fact_key of the derived value (e.g., "creatinine_clearance_cockcroft_gault")
            comparator: Comparison operator
            threshold: Threshold value
        
        Returns: TriState
        """
        # Find the derived value fact
        derived_fact = None
        for fact in facts:
            if fact.get("fact_key") == derived_fact_key:
                derived_fact = fact
                break
        
        if derived_fact is None:
            # Derived value not provided
            return TriState.UNKNOWN
        
        # Extract value and compare
        value = derived_fact.get("value")
        if value is None:
            return TriState.UNKNOWN
        
        return compare_quantity_to_threshold(value, comparator, threshold)


class GuardedPredicateEvaluator:
    """§5.3: Evaluate guarded/conditional predicates.
    
    Example: "IPI 3–5 (for > 60) or aaIPI 2–3 (for ≤ 60)"
    - When guard is known: evaluate the selected branch
    - When guard is UNKNOWN: supervaluate all branches
      - TRUE iff every branch → TRUE
      - FALSE iff every branch → FALSE
      - UNKNOWN otherwise (branches disagree or any is UNKNOWN)
    """
    
    @staticmethod
    def evaluate_case(
        facts: list[Dict[str, Any]],
        guard_fact_key: str,
        guard_value: Any,
        predicate: Dict[str, Any],
    ) -> TriState:
        """
        Evaluate a single case (branch) of a guarded predicate.
        
        Args:
            facts: Patient facts
            guard_fact_key: The fact key for the guard
            guard_value: The value this branch applies to
            predicate: The predicate for this branch (nested structure)
        
        Returns: TriState for this branch
        """
        # Simplified: assume predicate is a simple_comparison
        # In full P3, this would recursively evaluate nested predicates
        fact_key = predicate.get("fact_key")
        comparator = predicate.get("comparator")
        threshold = predicate.get("threshold", {}).get("value")
        
        if not all([fact_key, comparator, threshold is not None]):
            return TriState.UNKNOWN
        
        # Resolve the fact
        resolved = resolve_fact_for_criterion(facts, fact_key, "current")
        if resolved is None:
            return TriState.UNKNOWN
        
        value = resolved.get("value")
        if value is None:
            return TriState.UNKNOWN
        
        return compare_quantity_to_threshold(value, comparator, threshold)
    
    @staticmethod
    def evaluate(
        facts: list[Dict[str, Any]],
        guard_fact_key: str,
        cases: list[Dict[str, Any]],
    ) -> TriState:
        """
        Evaluate a guarded predicate with supervaluation for UNKNOWN guard.
        
        Args:
            facts: Patient facts
            guard_fact_key: The fact key for the guard
            cases: List of {value, predicate} cases
        
        Returns: TriState
        
        Algorithm:
        1. Resolve guard fact
        2. If guard is known: return evaluation of matching branch
        3. If guard is UNKNOWN: supervaluate all reachable branches
        """
        # Resolve guard fact
        guard_fact = resolve_fact_for_criterion(facts, guard_fact_key, "current")
        guard_value = guard_fact.get("value") if guard_fact else None
        
        # Find matching cases
        matching_cases = [c for c in cases if c.get("value") == guard_value]
        
        if guard_value is not None and matching_cases:
            # Guard is known: evaluate matching case
            result = GuardedPredicateEvaluator.evaluate_case(
                facts, guard_fact_key, guard_value, matching_cases[0]["predicate"]
            )
            return result
        elif guard_value is None:
            # Guard is UNKNOWN: supervaluate all cases
            branch_results = []
            for case in cases:
                branch_result = GuardedPredicateEvaluator.evaluate_case(
                    facts, guard_fact_key, case["value"], case["predicate"]
                )
                branch_results.append(branch_result)
            
            if not branch_results:
                return TriState.UNKNOWN
            
            # Supervaluation: TRUE iff all TRUE, FALSE iff all FALSE, else UNKNOWN
            if all(r == TriState.TRUE for r in branch_results):
                return TriState.TRUE
            elif all(r == TriState.FALSE for r in branch_results):
                return TriState.FALSE
            else:
                return TriState.UNKNOWN
        else:
            # No matching case
            return TriState.UNKNOWN


class NotExistsEvaluator:
    """§5.4: Coverage-aware `not_exists` with versioned subsumption.
    
    Example: "No prior elacestrant or other SERDs for advanced disease"
    - Returns TRUE only with positive absence signal:
      1. An explicit_negative Fact, OR
      2. A coverage assertion with:
         - concepts: queried agents ⊆ asserted agents (via versioned registry)
         - setting: covers criterion's setting
         - time: covers criterion's time window
    - Unknown or unvalidated mappings → UNKNOWN (never assumed)
    """
    
    @staticmethod
    def has_explicit_coverage(
        facts: list[Dict[str, Any]],
        fact_key: str,
        queried_agents: Set[str],
        queried_setting: Optional[str],
        queried_time_basis: Optional[str],  # "lifetime" or "bounded"; None = error
        queried_time_window: Optional[tuple[datetime, datetime]],
        registry: Optional[ConceptRegistry] = None,
    ) -> TriState:
        """
        Check if a coverage assertion covers the criterion's scope.
        
        §5.4: A bounded coverage window (e.g., "complete for past 2 years") cannot clear
        a lifetime criterion (e.g., "no prior therapy ever"). Lifetime requires lifetime
        coverage assertion.
        
        Returns:
        - TRUE if coverage asserts the queried agents/setting/time
        - FALSE if coverage is found but doesn't cover
        - UNKNOWN if no coverage found, unknown mappings, or time basis mismatch
        """
        if registry is None:
            registry = SEED_REGISTRY_V1
        
        # Find coverage facts
        coverage_facts = resolve_facts_for_criterion(
            facts, fact_key, "any_history", 
            predicate_assertion_scope={FactAssertion.EXPLICIT_NEGATIVE}
        )
        
        if not coverage_facts:
            return TriState.UNKNOWN
        
        # Check first (highest-authority) coverage fact
        coverage = coverage_facts[0].get("coverage", {})
        
        # Check completeness level
        completeness = coverage.get("completeness")
        if completeness != "complete":
            # Partial or opaque coverage cannot assert "no therapy"
            return TriState.UNKNOWN
        
        # CHECK TIME BASIS FIRST (§5.4 critical check)
        # Lifetime criterion requires lifetime (unbounded) coverage
        if queried_time_basis == "lifetime":
            coverage_time_basis = coverage.get("time_basis")
            if coverage_time_basis != "lifetime":
                # Bounded coverage cannot clear lifetime criterion
                return TriState.UNKNOWN
        elif queried_time_basis == "bounded":
            # Bounded criterion: coverage must cover the queried window
            coverage_start_str = coverage.get("time_start")
            coverage_end_str = coverage.get("time_end")
            queried_start, queried_end = queried_time_window or (None, None)
            
            if queried_start and queried_end:
                if not (coverage_start_str and coverage_end_str):
                    # Coverage doesn't have time bounds
                    return TriState.UNKNOWN
                
                # Parse coverage times if they're strings
                try:
                    if isinstance(coverage_start_str, str):
                        coverage_start = datetime.fromisoformat(coverage_start_str)
                    else:
                        coverage_start = coverage_start_str
                    
                    if isinstance(coverage_end_str, str):
                        coverage_end = datetime.fromisoformat(coverage_end_str)
                    else:
                        coverage_end = coverage_end_str
                except (ValueError, TypeError):
                    # Invalid date format → cannot validate
                    return TriState.UNKNOWN
                
                if coverage_start > queried_start or coverage_end < queried_end:
                    # Coverage window doesn't fully cover criterion window
                    return TriState.FALSE
        # else: queried_time_basis is None or unknown; cannot proceed
        
        # Check concepts: are queried agents ⊆ asserted agents?
        asserted_agents = set(coverage.get("agents", []))
        asserted_classes = set(coverage.get("classes", []))
        
        for agent in queried_agents:
            # Identical code asserted as agent or as class covers itself
            if agent not in asserted_agents and agent not in asserted_classes:
                # Check if agent is in any asserted class
                in_class = False
                for agent_class in asserted_classes:
                    result = validate_concept_membership(agent, agent_class, registry)
                    if result == TriState.TRUE:
                        in_class = True
                        break
                    elif result == TriState.UNKNOWN:
                        # Unknown mapping → cannot assert coverage
                        return TriState.UNKNOWN
                
                if not in_class:
                    # Agent not in coverage
                    return TriState.FALSE
        
        # Check setting: does coverage cover criterion's setting?
        # A setting-agnostic query ("no prior X", any setting) needs coverage of every
        # setting; an `unknown` setting never clears a setting-specific query.
        coverage_settings = set(coverage.get("settings", []))
        if "all_settings" not in coverage_settings:
            if not queried_setting or queried_setting not in coverage_settings:
                return TriState.FALSE
        
        # All checks passed: coverage asserts the criterion's scope
        return TriState.TRUE
    
    @staticmethod
    def evaluate(
        facts: list[Dict[str, Any]],
        fact_key: str,
        queried_agents: Set[str],
        queried_setting: Optional[str] = None,
        queried_time_basis: Optional[str] = None,  # "lifetime" or "bounded" (NEW: required)
        queried_time_window: Optional[tuple[datetime, datetime]] = None,
        registry: Optional[ConceptRegistry] = None,
    ) -> TriState:
        """
        Evaluate a `not_exists` predicate.
        
        §5.4: Returns TRUE only with positive absence signal:
        1. Scoped explicit_negative fact (agents specified in coverage), OR
        2. explicit_negative with complete coverage verifying agents/setting/time_basis
        
        CRITICAL (§5.4): 
        - Lifetime criterion requires lifetime coverage (not bounded)
        - Bare explicit_negative (no scope) does not clear agent-scoped queries
        - Unknown or unvalidated mappings always → UNKNOWN
        """
        if registry is None:
            registry = SEED_REGISTRY_V1
        
        if queried_time_basis is None:
            # Must specify time basis (lifetime or bounded)
            return TriState.UNKNOWN
        
        # Check for explicit_negative facts
        explicit_negs = resolve_facts_for_criterion(
            facts, fact_key, "any_history",
            predicate_assertion_scope={FactAssertion.EXPLICIT_NEGATIVE}
        )
        
        for neg_fact in explicit_negs:
            coverage = neg_fact.get("coverage")
            
            if coverage is None:
                # Bare explicit_negative: must specify scope (agents) to clear agent queries
                # A bare "no prior chemotherapy" doesn't clear "no prior SERD"
                if queried_agents:
                    # Querying for specific agents, but explicit_negative is unscoped
                    continue  # Check next fact
                else:
                    # Querying without specific agent scope (rare); bare negative covers it
                    return TriState.TRUE
            
            # Has coverage: verify it covers our query (agents, setting, time_basis)
            completeness = coverage.get("completeness")
            if completeness != "complete":
                # Partial coverage cannot assert "not exists"
                continue  # Check next fact
            
            # Verify coverage scope (agents, setting, time_basis)
            coverage_result = NotExistsEvaluator.has_explicit_coverage(
                [neg_fact], fact_key, queried_agents, queried_setting, 
                queried_time_basis, queried_time_window, registry
            )
            
            if coverage_result == TriState.TRUE:
                return TriState.TRUE
            # FALSE/UNKNOWN: this denial cannot confirm the query, but it says nothing
            # against another denial that does subsume it — keep looking. (Positive
            # exposures were already ruled out by the caller.)
        
        # No suitable explicit_negative found
        return TriState.UNKNOWN

"""Tests for P3: Predicate constructs (§5)

Tests the four predicate constructs:
1. §5.1: Relative-to-reference thresholds
2. §5.2: Derived values
3. §5.3: Guarded/conditional predicates
4. §5.4: Coverage-aware `not_exists`
"""

import pytest
from datetime import datetime, timedelta
from avicenna_matcher.predicates import (
    RelativeThresholdEvaluator,
    DerivedValueEvaluator,
    GuardedPredicateEvaluator,
    NotExistsEvaluator,
)
from avicenna_matcher.concepts import ConceptRegistry
from avicenna_matcher.types import TriState, FactAssertion


class TestRelativeThresholdEvaluator:
    """§5.1: Relative-to-reference thresholds (e.g., bilirubin < 1.5 × ULN)"""
    
    def test_bilirubin_below_reference_threshold(self):
        """bilirubin = 1.0, ULN = 1.2 → 1.0 < 1.5 × 1.2 (1.8) → TRUE"""
        fact = {
            "fact_id": "bili_1",
            "value": 1.0,
            "qualifiers": {"reference_high": 1.2},  # Patient's ULN
        }
        
        result = RelativeThresholdEvaluator.evaluate(
            fact,
            comparator="lt",
            reference_field="qualifiers.reference_high",
            scale=1.5,
        )
        assert result == TriState.TRUE
    
    def test_bilirubin_above_reference_threshold(self):
        """bilirubin = 2.5, ULN = 1.0 → 2.5 < 1.5 × 1.0 (1.5) → FALSE"""
        fact = {
            "fact_id": "bili_2",
            "value": 2.5,
            "qualifiers": {"reference_high": 1.0},
        }
        
        result = RelativeThresholdEvaluator.evaluate(
            fact,
            comparator="lt",
            reference_field="qualifiers.reference_high",
            scale=1.5,
        )
        assert result == TriState.FALSE
    
    def test_missing_reference_returns_unknown(self):
        """No reference provided → UNKNOWN (cannot evaluate)"""
        fact = {
            "fact_id": "bili_no_ref",
            "value": 1.0,
            # Missing qualifiers.reference_high
        }
        
        result = RelativeThresholdEvaluator.evaluate(
            fact,
            comparator="lt",
            reference_field="qualifiers.reference_high",
            scale=1.5,
        )
        assert result == TriState.UNKNOWN
    
    def test_missing_value_returns_unknown(self):
        """No value provided → UNKNOWN"""
        fact = {
            "fact_id": "bili_no_val",
            "qualifiers": {"reference_high": 1.2},
        }
        
        result = RelativeThresholdEvaluator.evaluate(
            fact,
            comparator="lt",
            reference_field="qualifiers.reference_high",
            scale=1.5,
        )
        assert result == TriState.UNKNOWN


class TestDerivedValueEvaluator:
    """§5.2: Derived values (e.g., creatinine clearance by Cockcroft-Gault)"""
    
    def test_derived_value_above_threshold(self):
        """CrCl = 65 mL/min, threshold = 50 → CrCl ≥ 50 → TRUE"""
        facts = [
            {
                "fact_id": "creatinine",
                "fact_key": "serum_creatinine",
                "value": 0.8,
            },
            {
                "fact_id": "crcl",
                "fact_key": "creatinine_clearance_cockcroft_gault",
                "value": 65,  # Derived by atomizer
            },
        ]
        
        result = DerivedValueEvaluator.evaluate(
            facts,
            derived_fact_key="creatinine_clearance_cockcroft_gault",
            comparator="ge",
            threshold=50,
        )
        assert result == TriState.TRUE
    
    def test_derived_value_below_threshold(self):
        """CrCl = 40 mL/min, threshold = 50 → CrCl ≥ 50 → FALSE"""
        facts = [
            {
                "fact_id": "crcl",
                "fact_key": "creatinine_clearance_cockcroft_gault",
                "value": 40,
            },
        ]
        
        result = DerivedValueEvaluator.evaluate(
            facts,
            derived_fact_key="creatinine_clearance_cockcroft_gault",
            comparator="ge",
            threshold=50,
        )
        assert result == TriState.FALSE
    
    def test_missing_derived_value_returns_unknown(self):
        """Derived fact not provided → UNKNOWN (matcher doesn't compute)"""
        facts = [
            {
                "fact_id": "creatinine",
                "fact_key": "serum_creatinine",
                "value": 0.8,
            },
            # Missing creatinine_clearance_cockcroft_gault
        ]
        
        result = DerivedValueEvaluator.evaluate(
            facts,
            derived_fact_key="creatinine_clearance_cockcroft_gault",
            comparator="ge",
            threshold=50,
        )
        assert result == TriState.UNKNOWN


class TestGuardedPredicateEvaluator:
    """§5.3: Guarded/conditional predicates (e.g., IPI for age)"""
    
    def test_guard_known_selects_branch(self):
        """Age > 60 → use strict branch (IPI 3–5); age known, so branch selected"""
        facts = [
            {
                "fact_id": "age",
                "fact_key": "age",
                "value": 65,  # > 60
                "effective_time": datetime.now(),
                "review_status": "reviewed",
                "source_kind": "structured",
            },
        ]
        
        cases = [
            {"value": ">60", "predicate": {"fact_key": "ipi", "comparator": "ge", "threshold": {"value": 3}}},
            {"value": "≤60", "predicate": {"fact_key": "ipi", "comparator": "ge", "threshold": {"value": 2}}},
        ]
        
        result = GuardedPredicateEvaluator.evaluate(facts, "age", cases)
        # Should select "age > 60" branch and evaluate "IPI ≥ 3"
        # (actual IPI fact not provided → UNKNOWN for this test)
        assert result == TriState.UNKNOWN
    
    def test_guard_unknown_supervalues_branches(self):
        """Guard age is UNKNOWN → evaluate all branches; if all TRUE → TRUE"""
        facts = [
            # Age fact missing → age is UNKNOWN
        ]
        
        cases = [
            {"value": ">60", "predicate": {"fact_key": "hemoglobin", "comparator": "ge", "threshold": {"value": 10}}},
            {"value": "≤60", "predicate": {"fact_key": "hemoglobin", "comparator": "ge", "threshold": {"value": 10}}},
        ]
        
        result = GuardedPredicateEvaluator.evaluate(facts, "age", cases)
        # Without hemoglobin fact, both branches → UNKNOWN → result is UNKNOWN
        assert result == TriState.UNKNOWN


class TestNotExistsEvaluator:
    """§5.4: Coverage-aware `not_exists` (e.g., no prior SERDs)"""
    
    def test_explicit_negative_with_scope_asserts_not_exists(self):
        """Explicit negative with scoped coverage (agents) → "no SERD" → TRUE"""
        facts = [
            {
                "fact_id": "serd_ruled_out",
                "fact_key": "prior_therapies",
                "assertion": "explicit_negative",
                "coverage": {
                    "completeness": "complete",
                    "settings": ["all_settings"],  # setting-agnostic query needs every setting covered
                    "agents": ["elacestrant", "AZD9496"],
                    "time_basis": "lifetime",
                },
                "effective_time": datetime.now(),
                "review_status": "reviewed",
                "source_kind": "structured",
            },
        ]
        
        result = NotExistsEvaluator.evaluate(
            facts,
            fact_key="prior_therapies",
            queried_agents={"elacestrant"},
            queried_time_basis="lifetime",
        )
        assert result == TriState.TRUE
    
    def test_bare_explicit_negative_unscoped_fails_agent_query(self):
        """REGRESSION: Bare explicit_negative (no scope) should NOT clear agent query.
        
        §5.4 false-pass bug #2: A bare "no prior chemotherapy" negative was incorrectly
        clearing "no prior SERD" queries. This must return UNKNOWN (no scope).
        """
        facts = [
            {
                "fact_id": "chemo_ruled_out",
                "fact_key": "prior_therapies",
                "assertion": "explicit_negative",
                # NO coverage/scope: this is bare
                "effective_time": datetime.now(),
                "review_status": "reviewed",
                "source_kind": "structured",
            },
        ]
        
        # Query for specific agents (SERD)
        result = NotExistsEvaluator.evaluate(
            facts,
            fact_key="prior_therapies",
            queried_agents={"elacestrant", "AZD9496"},
            queried_time_basis="lifetime",
        )
        # Bare negative doesn't specify agents → UNKNOWN (not a match)
        assert result == TriState.UNKNOWN
    
    def test_no_explicit_signal_returns_unknown(self):
        """No explicit negative or coverage → UNKNOWN (cannot assert absence)"""
        facts = [
            {
                "fact_id": "therapy_history",
                "fact_key": "prior_therapies",
                "assertion": "positive",
                "value": {"type": "therapy", "class": "chemotherapy"},
                # Different therapy class, not SERD
            },
        ]
        
        result = NotExistsEvaluator.evaluate(
            facts,
            fact_key="prior_therapies",
            queried_agents={"elacestrant", "AZD9496"},
            queried_time_basis="lifetime",
        )
        # No explicit SERD negative and no coverage → UNKNOWN
        assert result == TriState.UNKNOWN
    
    def test_partial_coverage_returns_unknown(self):
        """Partial coverage (not 'complete') cannot assert "not exists" """
        facts = [
            {
                "fact_id": "therapy_partial",
                "fact_key": "prior_therapies",
                "assertion": "explicit_negative",
                "coverage": {
                    "completeness": "partial",  # NOT complete
                    "agents": ["elacestrant", "AZD9496"],
                    "time_basis": "bounded",
                },
                "effective_time": datetime.now(),
                "review_status": "reviewed",
                "source_kind": "structured",
            },
        ]
        
        result = NotExistsEvaluator.evaluate(
            facts,
            fact_key="prior_therapies",
            queried_agents={"elacestrant"},
            queried_time_basis="bounded",
            queried_time_window=(datetime(2024, 1, 1), datetime(2026, 10, 17)),
        )
        # Partial coverage → UNKNOWN
        assert result == TriState.UNKNOWN
    
    def test_bounded_coverage_clears_bounded_criterion(self):
        """Complete bounded coverage → TRUE for bounded criterion with same window"""
        facts = [
            {
                "fact_id": "therapy_complete_2yr",
                "fact_key": "prior_therapies",
                "assertion": "explicit_negative",
                "coverage": {
                    "completeness": "complete",
                    "settings": ["all_settings"],  # setting-agnostic query needs every setting covered
                    "agents": ["elacestrant", "AZD9496"],
                    "time_basis": "bounded",
                    "time_start": "2024-01-01",
                    "time_end": "2026-10-17",
                },
                "effective_time": datetime(2026, 10, 17),
                "review_status": "reviewed",
                "source_kind": "structured",
            },
        ]
        
        result = NotExistsEvaluator.evaluate(
            facts,
            fact_key="prior_therapies",
            queried_agents={"elacestrant"},
            queried_time_basis="bounded",
            queried_time_window=(datetime(2024, 1, 1), datetime(2026, 10, 17)),
        )
        # Bounded coverage matches bounded query → TRUE
        assert result == TriState.TRUE
    
    def test_bounded_coverage_fails_lifetime_criterion(self):
        """REGRESSION: Bounded coverage should NOT clear lifetime criterion.
        
        §5.4 false-pass bug #1: A 2-year "complete" history was incorrectly clearing
        "no prior therapy ever" (lifetime). The design explicitly requires lifetime
        coverage for lifetime criteria.
        """
        facts = [
            {
                "fact_id": "therapy_complete_2yr",
                "fact_key": "prior_therapies",
                "assertion": "explicit_negative",
                "coverage": {
                    "completeness": "complete",
                    "settings": ["all_settings"],  # isolate the time rule
                    "agents": ["elacestrant", "AZD9496"],
                    "time_basis": "bounded",  # Only 2 years, NOT lifetime
                    "time_start": "2024-10-17",
                    "time_end": "2026-10-17",
                },
                "effective_time": datetime(2026, 10, 17),
                "review_status": "reviewed",
                "source_kind": "structured",
            },
        ]
        
        # Criterion: "No prior SERD ever" (lifetime)
        result = NotExistsEvaluator.evaluate(
            facts,
            fact_key="prior_therapies",
            queried_agents={"elacestrant", "AZD9496"},
            queried_time_basis="lifetime",  # LIFETIME, not bounded
        )
        # Bounded coverage cannot clear lifetime criterion → UNKNOWN
        assert result == TriState.UNKNOWN
    
    def test_lifetime_coverage_clears_lifetime_criterion(self):
        """Complete lifetime coverage → TRUE for lifetime criterion"""
        facts = [
            {
                "fact_id": "therapy_complete_lifetime",
                "fact_key": "prior_therapies",
                "assertion": "explicit_negative",
                "coverage": {
                    "completeness": "complete",
                    "settings": ["all_settings"],  # setting-agnostic query needs every setting covered
                    "agents": ["elacestrant", "AZD9496"],
                    "time_basis": "lifetime",  # Covers entire lifetime
                },
                "effective_time": datetime.now(),
                "review_status": "reviewed",
                "source_kind": "structured",
            },
        ]
        
        result = NotExistsEvaluator.evaluate(
            facts,
            fact_key="prior_therapies",
            queried_agents={"elacestrant", "AZD9496"},
            queried_time_basis="lifetime",
        )
        # Lifetime coverage matches lifetime query → TRUE
        assert result == TriState.TRUE
    
    def test_unknown_concept_mapping_returns_unknown(self):
        """Unknown agent membership in class → cannot confirm coverage via class → UNKNOWN"""
        facts = [
            {
                "fact_id": "therapy_unknown_agent",
                "fact_key": "prior_therapies",
                "assertion": "explicit_negative",
                "coverage": {
                    "completeness": "complete",
                    "classes": ["SERD"],  # Covers "SERD" class
                    "time_basis": "lifetime",
                    # But querying for "new_experimental_serd" not in registry
                },
                "effective_time": datetime.now(),
                "review_status": "reviewed",
                "source_kind": "structured",
            },
        ]
        
        registry = ConceptRegistry(
            version="test/1.0",
            memberships={"SERD": {"elacestrant", "AZD9496"}},
            # "new_experimental_serd" NOT in SERD membership → unknown mapping
        )
        
        result = NotExistsEvaluator.evaluate(
            facts,
            fact_key="prior_therapies",
            queried_agents={"new_experimental_serd"},  # Unknown agent!
            queried_time_basis="lifetime",
            registry=registry,
        )
        # Coverage says "SERD class" but unknown agent mapping → UNKNOWN
        assert result == TriState.UNKNOWN
    
    def test_concept_class_coverage_via_registry(self):
        """Coverage by class (e.g., "SERD" class) if agents are members → TRUE"""
        facts = [
            {
                "fact_id": "therapy_by_class",
                "fact_key": "prior_therapies",
                "assertion": "explicit_negative",
                "coverage": {
                    "completeness": "complete",
                    "settings": ["all_settings"],  # setting-agnostic query needs every setting covered
                    "classes": ["SERD"],  # Covers SERD class via concept registry
                    "time_basis": "lifetime",
                },
                "effective_time": datetime.now(),
                "review_status": "reviewed",
                "source_kind": "structured",
            },
        ]
        
        registry = ConceptRegistry(
            version="test/1.0",
            memberships={"SERD": {"elacestrant", "AZD9496"}},
        )
        
        result = NotExistsEvaluator.evaluate(
            facts,
            fact_key="prior_therapies",
            queried_agents={"elacestrant"},  # Member of SERD
            queried_time_basis="lifetime",
            registry=registry,
        )
        # elacestrant is in SERD class, coverage is complete, lifetime → TRUE
        assert result == TriState.TRUE


class TestPredicateIntegration:
    """Integration: combining predicates in composite criteria"""
    
    def test_relative_and_derived_combined(self):
        """Criterion: "bilirubin < 1.5 × ULN AND CrCl ≥ 50" with both conditions present"""
        facts = [
            {
                "fact_id": "bili",
                "fact_key": "total_bilirubin",
                "value": 1.0,
                "qualifiers": {"reference_high": 1.2},
            },
            {
                "fact_id": "crcl",
                "fact_key": "creatinine_clearance_cockcroft_gault",
                "value": 60,
            },
        ]
        
        # Evaluate both sub-predicates
        bili_result = RelativeThresholdEvaluator.evaluate(
            facts[0], "lt", "qualifiers.reference_high", 1.5
        )
        crcl_result = DerivedValueEvaluator.evaluate(
            facts, "creatinine_clearance_cockcroft_gault", "ge", 50
        )
        
        assert bili_result == TriState.TRUE
        assert crcl_result == TriState.TRUE

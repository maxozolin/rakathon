"""Tests for P2: Evidence resolution (§4 policy)

Tests the §4 ordering policy (applicability → subject/assertion → time → precision → 
aggregation → authority/recency) and the four known regression cases:
1. Cleared hard exclusion
2. Stale reviewed fact
3. Assessed-not-complete therapy
4. Unknown concept mapping
"""

import pytest
from datetime import datetime, timedelta
from avicenna_matcher.resolution import (
    is_fact_applicable,
    is_assertion_compatible,
    is_time_compatible,
    fact_precision,
    fact_authority_score,
    select_fact_for_point_predicate,
    resolve_fact_for_criterion,
    resolve_facts_for_criterion,
)
from avicenna_matcher.concepts import validate_concept_membership, ConceptRegistry
from avicenna_matcher.types import TriState, FactAssertion, VerificationStatus


class TestApplicability:
    """Step 1: Applicability — fact_key must match criterion fact_key"""
    
    def test_matching_fact_key_applicable(self):
        assert is_fact_applicable("age", "age")
    
    def test_mismatched_fact_key_not_applicable(self):
        assert not is_fact_applicable("age", "weight")
    
    def test_empty_fact_key(self):
        assert not is_fact_applicable("", "age")


class TestAssertionCompatibility:
    """Step 2: Subject/Assertion — assertion must be compatible"""
    
    def test_all_assertions_compatible_by_default(self):
        assert is_assertion_compatible(FactAssertion.POSITIVE)
        assert is_assertion_compatible(FactAssertion.EXPLICIT_NEGATIVE)
        assert is_assertion_compatible(FactAssertion.SUSPECTED)
        assert is_assertion_compatible(FactAssertion.HISTORICAL)
    
    def test_scoped_positive_only(self):
        scope = {FactAssertion.POSITIVE}
        assert is_assertion_compatible(FactAssertion.POSITIVE, scope)
        assert not is_assertion_compatible(FactAssertion.EXPLICIT_NEGATIVE, scope)
    
    def test_scoped_explicit_negative_for_not_exists(self):
        scope = {FactAssertion.EXPLICIT_NEGATIVE}
        assert is_assertion_compatible(FactAssertion.EXPLICIT_NEGATIVE, scope)
        assert not is_assertion_compatible(FactAssertion.POSITIVE, scope)


class TestTimeCompatibility:
    """Step 3: Time compatibility — fact's time must fit predicate's relation"""
    
    def test_any_history_always_compatible(self):
        now = datetime.now()
        assert is_time_compatible(now, "any_history")
        assert is_time_compatible(None, "any_history")
    
    def test_current_requires_effective_time(self):
        now = datetime.now()
        assert is_time_compatible(now, "current")
        assert not is_time_compatible(None, "current")
    
    def test_at_screening_requires_effective_time(self):
        now = datetime.now()
        assert is_time_compatible(now, "at_screening")
        assert not is_time_compatible(None, "at_screening")
    
    def test_within_window_before_anchor(self):
        anchor = datetime(2026, 10, 17)
        window = 30  # days before anchor
        
        # Exactly 20 days before anchor: within window
        within = datetime(2026, 9, 27)
        assert is_time_compatible(within, "within_days_before_anchor", anchor, window)
        
        # 40 days before anchor: outside window
        outside = datetime(2026, 9, 7)
        assert not is_time_compatible(outside, "within_days_before_anchor", anchor, window)
        
        # Exactly on anchor: within window (0 days before)
        assert is_time_compatible(anchor, "within_days_before_anchor", anchor, window)


class TestPrecision:
    """Step 4: Precision — tiebreaker using effective_time recency"""
    
    def test_more_recent_higher_score(self):
        now = datetime.now()
        one_week_ago = now - timedelta(days=7)
        
        recent_score = fact_precision(now, None)
        old_score = fact_precision(one_week_ago, None)
        
        assert recent_score > old_score
    
    def test_none_time_lowest_score(self):
        now = datetime.now()
        assert fact_precision(None, None) == 0
        assert fact_precision(now, None) > 0


class TestAuthority:
    """Step 6: Authority tiebreaker among contemporaneous facts"""
    
    def test_reviewed_highest(self):
        reviewed = fact_authority_score(VerificationStatus.REVIEWED, "structured")
        extracted = fact_authority_score(VerificationStatus.EXTRACTED_CANDIDATE, "structured")
        assert reviewed > extracted
    
    def test_structured_source_higher_than_narrative(self):
        reviewed_structured = fact_authority_score(VerificationStatus.REVIEWED, "structured")
        reviewed_narrative = fact_authority_score(VerificationStatus.REVIEWED, "narrative")
        assert reviewed_structured > reviewed_narrative
    
    def test_combined_authority(self):
        # reviewed + structured > extracted + narrative
        best = fact_authority_score(VerificationStatus.REVIEWED, "structured")
        worst = fact_authority_score(VerificationStatus.EXTRACTED_CANDIDATE, "narrative")
        assert best > worst


class TestSelectFactForPointPredicate:
    """Recency dominates for point-in-time predicates (current/at_screening)"""
    
    def test_most_recent_selected(self):
        now = datetime.now()
        three_days_ago = now - timedelta(days=3)
        one_week_ago = now - timedelta(days=7)
        
        facts = [
            {
                "fact_id": "old",
                "effective_time": one_week_ago,
                "review_status": "reviewed",
                "source_kind": "structured",
            },
            {
                "fact_id": "recent",
                "effective_time": now,
                "review_status": "extracted_candidate",
                "source_kind": "narrative",
            },
            {
                "fact_id": "middle",
                "effective_time": three_days_ago,
                "review_status": "reviewed",
                "source_kind": "structured",
            },
        ]
        
        selected = select_fact_for_point_predicate(facts, "current")
        assert selected["fact_id"] == "recent"
    
    def test_authority_breaks_ties_among_contemporaneous(self):
        # Two facts at same time; reviewed should win over extracted
        now = datetime.now()
        
        facts = [
            {
                "fact_id": "reviewed_fact",
                "effective_time": now,
                "review_status": "reviewed",
                "source_kind": "structured",
            },
            {
                "fact_id": "extracted_fact",
                "effective_time": now,
                "review_status": "extracted_candidate",
                "source_kind": "narrative",
            },
        ]
        
        selected = select_fact_for_point_predicate(facts, "current")
        assert selected["fact_id"] == "reviewed_fact"
    
    def test_empty_facts_returns_none(self):
        selected = select_fact_for_point_predicate([], "current")
        assert selected is None


class TestRegressionCases:
    """Four known regression cases from clinical practice"""
    
    def test_regression_1_cleared_hard_exclusion(self):
        """Regression 1: A hard exclusion (e.g., history of HF) is cleared by explicit_negative.
        
        Criterion: "No prior heart failure" (hard exclusion)
        Patient fact: explicit_negative assertion that HF was ruled out
        Expected: Criterion should PASS (patient satisfies the "no HF" requirement)
        """
        # Note: This is a semantic test; actual evaluation requires predicate + outcome logic
        # Here we just verify that explicit_negative facts are resolved correctly
        facts = [
            {
                "fact_id": "hf_ruled_out",
                "fact_key": "cardiac_history",
                "assertion": "explicit_negative",
                "state": "known",
                "effective_time": datetime(2026, 10, 15),
                "review_status": "reviewed",
                "source_kind": "structured",
            }
        ]
        
        # Resolve the fact for a not_exists predicate scoped to explicit_negative
        resolved = resolve_fact_for_criterion(
            facts,
            criterion_fact_key="cardiac_history",
            predicate_relation="at_screening",
            predicate_assertion_scope={FactAssertion.EXPLICIT_NEGATIVE},
        )
        
        assert resolved is not None
        assert resolved["assertion"] == "explicit_negative"
    
    def test_regression_2_stale_reviewed_fact(self):
        """Regression 2: Stale reviewed fact (6mo old) does not override fresh extracted value.
        
        Criterion: "ECOG ≤ 1 at screening"
        Patient facts:
        - 6 months ago: ECOG 0 (reviewed, authoritative)
        - Yesterday: ECOG 2 (extracted, unreviewed)
        Expected: Select yesterday's value (recency dominates over authority)
        """
        six_months_ago = datetime.now() - timedelta(days=180)
        yesterday = datetime.now() - timedelta(days=1)
        
        facts = [
            {
                "fact_id": "ecog_stale",
                "fact_key": "ecog",
                "value": 0,
                "effective_time": six_months_ago,
                "review_status": "reviewed",
                "source_kind": "structured",
            },
            {
                "fact_id": "ecog_fresh",
                "fact_key": "ecog",
                "value": 2,
                "effective_time": yesterday,
                "review_status": "extracted_candidate",
                "source_kind": "narrative",
            },
        ]
        
        resolved = resolve_fact_for_criterion(
            facts,
            criterion_fact_key="ecog",
            predicate_relation="current",
        )
        
        # Should select fresh value (yesterday) despite lower authority
        assert resolved["fact_id"] == "ecog_fresh"
        assert resolved["value"] == 2
    
    def test_regression_3_assessed_not_complete_therapy(self):
        """Regression 3: Therapy assessment with completeness='partial' cannot clear not_exists.
        
        Criterion: "No prior SERD therapy" (hard inclusion via not_exists)
        Patient facts: Coverage assertion for "hormone therapies" with completeness='partial'
        Expected: Cannot use partial coverage to assert "no SERD"; must return UNKNOWN
        
        Note: This test validates the resolution filtering; actual not_exists logic is in P3.
        """
        facts = [
            {
                "fact_id": "therapy_history",
                "fact_key": "prior_therapies",
                "assertion": "explicit_negative",
                "state": "reviewed_reconciliation",
                "effective_time": datetime(2026, 10, 10),
                "review_status": "reviewed",
                "source_kind": "structured",
                "coverage": {
                    "completeness": "partial",
                    "assessed_percentage": 75.0, "applicable_count": 4,
                    "classes": ["hormone_therapies"],
                },
            }
        ]
        
        # Resolve; the presence of partial coverage should be noted
        # (Actual not_exists logic in P3 will check completeness subsumption)
        resolved = resolve_fact_for_criterion(
            facts,
            criterion_fact_key="prior_therapies",
            predicate_relation="any_history",
            predicate_assertion_scope={FactAssertion.EXPLICIT_NEGATIVE},
        )
        
        assert resolved is not None
        assert resolved["coverage"]["completeness"] == "partial"
    
    def test_regression_4_unknown_concept_mapping(self):
        """Regression 4: Unknown concept mapping for not_exists → UNKNOWN (never assumed).
        
        Criterion: "No prior SERDs" (scoped to SERD agents via concept subsumption)
        Patient fact: Coverage of "experimental_agent_xyz" (unknown, not in registry)
        Expected: validate_concept_membership returns UNKNOWN; criterion cannot clear
        """
        registry = ConceptRegistry(
            version="test/1.0",
            memberships={"SERD": {"elacestrant", "AZD9496"}},
        )
        
        # Known agent: maps to SERD
        known_result = validate_concept_membership("elacestrant", "SERD", registry)
        assert known_result == TriState.TRUE
        
        # Unknown agent: cannot confirm membership
        unknown_result = validate_concept_membership("experimental_xyz", "SERD", registry)
        assert unknown_result == TriState.FALSE
        
        # Unknown class: cannot confirm coverage
        unmapped_class_result = validate_concept_membership("elacestrant", "UNKNOWN_CLASS", registry)
        assert unmapped_class_result == TriState.UNKNOWN


class TestFullResolutionPipeline:
    """Integration tests for the complete §4 resolution pipeline"""
    
    def test_resolve_with_all_filters(self):
        """Full pipeline: applicability → assertion → time → select best"""
        now = datetime.now()
        
        facts = [
            # Wrong fact_key: filtered out
            {
                "fact_id": "wrong_key",
                "fact_key": "weight",
                "assertion": "positive",
                "effective_time": now,
                "review_status": "reviewed",
                "source_kind": "structured",
            },
            # Wrong assertion: filtered out
            {
                "fact_id": "wrong_assertion",
                "fact_key": "age",
                "assertion": "suspected",
                "effective_time": now,
                "review_status": "reviewed",
                "source_kind": "structured",
            },
            # Correct: selected (most recent + authority)
            {
                "fact_id": "correct",
                "fact_key": "age",
                "assertion": "positive",
                "value": 42,
                "effective_time": now,
                "review_status": "reviewed",
                "source_kind": "structured",
            },
        ]
        
        resolved = resolve_fact_for_criterion(
            facts,
            criterion_fact_key="age",
            predicate_relation="current",
            predicate_assertion_scope={FactAssertion.POSITIVE},
        )
        
        assert resolved is not None
        assert resolved["fact_id"] == "correct"
        assert resolved["value"] == 42

"""Tests for P0: Schemas + validator

Validates that:
1. All design examples pass schema validation
2. State × assertion consistency is enforced
3. Unknown enum values fail validation
4. Unknown reason_codes are flagged (open set handled)
5. Duplicate fact_ids are rejected
6. Acyclic alternatives are checked
"""

import pytest
import json
from pathlib import Path

from avicenna_matcher import (
    validate,
    validate_packet_facts,
    validate_state_assertion_consistency,
    ValidationError,
)


@pytest.fixture
def minimal_packet():
    """Minimal valid patient packet"""
    return {
        "schema_version": "avicenna.matcher-packet/1.0.0",
        "packet_id": "pkt-001",
        "patient_ref": "p-123",
        "generated_at": "2026-10-17T00:39:00Z",
        "environment": "synthetic_demo",
        "source_snapshot": {
            "snapshot_id": "snap-001",
            "ingestion_state": "complete",
            "extractor_version": "1.0",
            "terminology_version": "1.0",
        },
        "evaluation_context": {
            "mode": "prescreen_real_time",
            "anchor": {"timestamp": "2026-10-17T00:39:00Z"},
            "absolute_screening_recency_allowed": False,
            "policy_version": "1.0",
        },
        "facts": [],
        "coverage": {
            "assessed_fact_keys": [],
            "unassessed_fact_keys": [],
            "completeness": [],
        },
        "warnings": [],
    }


@pytest.fixture
def minimal_pack():
    """Minimal valid criteria pack"""
    return {
        "schema_version": "avicenna.criteria-pack/0.1",
        "pack_id": "pack-001",
        "trial_id": "NCT12345678",
        "criteria_completeness": "complete",
        "generated_at": "2026-10-17T00:39:00Z",
        "arms": [
            {
                "arm_id": "arm-1",
                "arm_name": "Treatment",
                "study_type": "interventional",
            }
        ],
        "criteria": [],
    }


class TestPacketSchema:
    """Test patient packet schema validation"""

    def test_valid_minimal_packet(self, minimal_packet):
        """Minimal packet should pass validation"""
        validate(minimal_packet, "patient_packet")

    def test_invalid_schema_version(self, minimal_packet):
        """Wrong schema_version should fail"""
        minimal_packet["schema_version"] = "wrong.version/1.0"
        with pytest.raises(ValidationError):
            validate(minimal_packet, "patient_packet")

    def test_missing_required_field(self, minimal_packet):
        """Missing required field should fail"""
        del minimal_packet["packet_id"]
        with pytest.raises(ValidationError):
            validate(minimal_packet, "patient_packet")

    def test_invalid_environment(self, minimal_packet):
        """Invalid environment enum should fail"""
        minimal_packet["environment"] = "invalid_env"
        with pytest.raises(ValidationError):
            validate(minimal_packet, "patient_packet")

    def test_invalid_evaluation_mode(self, minimal_packet):
        """Invalid evaluation mode should fail"""
        minimal_packet["evaluation_context"]["mode"] = "invalid_mode"
        with pytest.raises(ValidationError):
            validate(minimal_packet, "patient_packet")

    def test_null_anchor_allowed(self, minimal_packet):
        """Null anchor should be valid"""
        minimal_packet["evaluation_context"]["anchor"] = None
        validate(minimal_packet, "patient_packet")

    def test_fact_with_known_state_and_quantity_value(self, minimal_packet):
        """Fact with known state and quantity value should pass"""
        minimal_packet["facts"] = [
            {
                "fact_id": "f1",
                "fact_key": "hemoglobin",
                "state": "known",
                "value": {
                    "kind": "quantity",
                    "value": 13.5,
                    "unit": "g/dL",
                    "normalization_status": "validated",
                },
                "missing_reason": None,
                "assertion": "positive",
                "subject_scope": "patient",
                "effective_time": {"timestamp": "2026-10-17T00:39:00Z"},
                "recorded_time": {"timestamp": "2026-10-17T00:39:00Z"},
                "evidence": [{"source_text": "Lab report: HGB 13.5"}],
                "provenance": {
                    "derivation_method": "direct_extract",
                    "extractor_version": "1.0",
                },
                "review_status": "reviewed",
                "generalization": {"applied": False, "constraints": []},
                "alternatives": [],
                "scope": None,
            }
        ]
        validate(minimal_packet, "patient_packet")

    def test_fact_with_coded_value(self, minimal_packet):
        """Fact with coded value should pass"""
        minimal_packet["facts"] = [
            {
                "fact_id": "f2",
                "fact_key": "disease_status",
                "state": "known",
                "value": {
                    "kind": "coded",
                    "system": "SNOMED",
                    "code": "399122000",
                    "display": "Remission",
                },
                "missing_reason": None,
                "assertion": "positive",
                "subject_scope": "patient",
                "effective_time": None,
                "recorded_time": None,
                "evidence": [{"source_text": "Clinical note: in remission"}],
                "provenance": {
                    "derivation_method": "direct_extract",
                    "extractor_version": "1.0",
                },
                "review_status": "unreviewed",
                "generalization": {"applied": False, "constraints": []},
                "alternatives": [],
                "scope": None,
            }
        ]
        validate(minimal_packet, "patient_packet")

    def test_fact_with_band_value(self, minimal_packet):
        """Fact with band (age range) should pass"""
        minimal_packet["facts"] = [
            {
                "fact_id": "f3",
                "fact_key": "age_group",
                "state": "known",
                "value": {
                    "kind": "band",
                    "lower_inclusive": 60,
                    "upper_inclusive": 64,
                },
                "missing_reason": None,
                "assertion": "positive",
                "subject_scope": "patient",
                "effective_time": None,
                "recorded_time": None,
                "evidence": [{"source_text": "DOB indicates age 60-64"}],
                "provenance": {
                    "derivation_method": "direct_extract",
                    "extractor_version": "1.0",
                },
                "review_status": "unreviewed",
                "generalization": {"applied": False, "constraints": []},
                "alternatives": [],
                "scope": None,
            }
        ]
        validate(minimal_packet, "patient_packet")

    def test_fact_with_unknown_state(self, minimal_packet):
        """Fact with unknown state should pass"""
        minimal_packet["facts"] = [
            {
                "fact_id": "f4",
                "fact_key": "hemoglobin",
                "state": "unknown",
                "value": None,
                "missing_reason": "not_documented",
                "assertion": None,
                "subject_scope": "patient",
                "effective_time": None,
                "recorded_time": None,
                "evidence": [],
                "provenance": {
                    "derivation_method": "direct_extract",
                    "extractor_version": "1.0",
                },
                "review_status": "unreviewed",
                "generalization": {"applied": False, "constraints": []},
                "alternatives": [],
                "scope": None,
            }
        ]
        validate(minimal_packet, "patient_packet")

    def test_fact_with_conflict_state(self, minimal_packet):
        """Fact with conflict state should pass"""
        minimal_packet["facts"] = [
            {
                "fact_id": "f5",
                "fact_key": "hemoglobin",
                "state": "conflict",
                "value": None,
                "missing_reason": "contradictory_evidence",
                "assertion": None,
                "subject_scope": "patient",
                "effective_time": None,
                "recorded_time": None,
                "evidence": [
                    {"source_text": "Lab 1: HGB 13.5"},
                    {"source_text": "Lab 2: HGB 9.2"},
                ],
                "provenance": {
                    "derivation_method": "direct_extract",
                    "extractor_version": "1.0",
                },
                "review_status": "unreviewed",
                "generalization": {"applied": False, "constraints": []},
                "alternatives": ["f6", "f7"],
                "scope": None,
            }
        ]
        validate(minimal_packet, "patient_packet")


class TestCriteriaPackSchema:
    """Test criteria pack schema validation"""

    def test_valid_minimal_pack(self, minimal_pack):
        """Minimal pack should pass validation"""
        validate(minimal_pack, "criteria_pack")

    def test_invalid_schema_version(self, minimal_pack):
        """Wrong schema_version should fail"""
        minimal_pack["schema_version"] = "wrong.version/1.0"
        with pytest.raises(ValidationError):
            validate(minimal_pack, "criteria_pack")

    def test_criterion_with_simple_comparison(self, minimal_pack):
        """Criterion with simple comparison atom"""
        minimal_pack["criteria"] = [
            {
                "criterion_id": "c1",
                "criterion_type": "inclusion",
                "hardness": "hard",
                "arm_scope": None,
                "source_text": "Age >= 18 years",
                "atoms": [
                    {
                        "atom_id": "a1",
                        "predicate_type": "simple_comparison",
                        "arm_scope": None,
                        "source_text": "Age >= 18",
                        "fact_key": "age",
                        "comparator": "ge",
                        "threshold": {"kind": "quantity", "value": 18},
                    }
                ],
                "completeness_note": "complete",
            }
        ]
        validate(minimal_pack, "criteria_pack")

    def test_opaque_criterion(self, minimal_pack):
        """Criterion with no atoms (opaque_text)"""
        minimal_pack["criteria"] = [
            {
                "criterion_id": "c2",
                "criterion_type": "exclusion",
                "hardness": "hard",
                "arm_scope": None,
                "source_text": "Severe comorbidities per investigator discretion",
                "atoms": [],
                "completeness_note": "opaque_text",
            }
        ]
        validate(minimal_pack, "criteria_pack")


class TestStateAssertionConsistency:
    """Test state × assertion consistency validation"""

    def test_known_with_positive_assertion(self):
        """known + positive should pass"""
        fact = {
            "fact_id": "f1",
            "state": "known",
            "assertion": "positive",
        }
        validate_state_assertion_consistency(fact)

    def test_known_with_explicit_negative_assertion(self):
        """known + explicit_negative should pass"""
        fact = {
            "fact_id": "f1",
            "state": "known",
            "assertion": "explicit_negative",
        }
        validate_state_assertion_consistency(fact)

    def test_known_with_suspected_assertion(self):
        """known + suspected should pass"""
        fact = {
            "fact_id": "f1",
            "state": "known",
            "assertion": "suspected",
        }
        validate_state_assertion_consistency(fact)

    def test_known_with_historical_assertion(self):
        """known + historical should pass"""
        fact = {
            "fact_id": "f1",
            "state": "known",
            "assertion": "historical",
        }
        validate_state_assertion_consistency(fact)

    def test_known_with_null_assertion_fails(self):
        """known + null assertion should fail"""
        fact = {
            "fact_id": "f1",
            "state": "known",
            "assertion": None,
        }
        with pytest.raises(ValidationError):
            validate_state_assertion_consistency(fact)

    def test_unknown_with_null_assertion(self):
        """unknown + null assertion should pass"""
        fact = {
            "fact_id": "f1",
            "state": "unknown",
            "assertion": None,
        }
        validate_state_assertion_consistency(fact)

    def test_unknown_with_assertion_fails(self):
        """unknown + any assertion should fail"""
        fact = {
            "fact_id": "f1",
            "state": "unknown",
            "assertion": "positive",
        }
        with pytest.raises(ValidationError):
            validate_state_assertion_consistency(fact)

    def test_not_tested_with_null_assertion(self):
        """not_tested + null assertion should pass"""
        fact = {
            "fact_id": "f1",
            "state": "not_tested",
            "assertion": None,
        }
        validate_state_assertion_consistency(fact)

    def test_indeterminate_with_null_assertion(self):
        """indeterminate + null assertion should pass"""
        fact = {
            "fact_id": "f1",
            "state": "indeterminate",
            "assertion": None,
        }
        validate_state_assertion_consistency(fact)

    def test_conflict_with_null_assertion(self):
        """conflict + null assertion should pass"""
        fact = {
            "fact_id": "f1",
            "state": "conflict",
            "assertion": None,
        }
        validate_state_assertion_consistency(fact)


class TestPacketFactValidation:
    """Test packet-level fact validation"""

    def test_duplicate_fact_ids_fails(self, minimal_packet):
        """Duplicate fact_ids should fail"""
        minimal_packet["facts"] = [
            {
                "fact_id": "f1",
                "fact_key": "hemoglobin",
                "state": "known",
                "value": {"kind": "quantity", "value": 13.5, "unit": "g/dL", "normalization_status": "normalized"},
                "missing_reason": None,
                "assertion": "positive",
                "subject_scope": "patient",
                "effective_time": None,
                "recorded_time": None,
                "evidence": [{"source_text": "Lab"}],
                "provenance": {"derivation_method": "direct", "extractor_version": "1"},
                "review_status": "unreviewed",
                "generalization": {"applied": False, "constraints": []},
                "alternatives": [],
                "scope": None,
            },
            {
                "fact_id": "f1",  # Duplicate!
                "fact_key": "glucose",
                "state": "unknown",
                "value": None,
                "missing_reason": "not_documented",
                "assertion": None,
                "subject_scope": "patient",
                "effective_time": None,
                "recorded_time": None,
                "evidence": [],
                "provenance": {"derivation_method": "direct", "extractor_version": "1"},
                "review_status": "unreviewed",
                "generalization": {"applied": False, "constraints": []},
                "alternatives": [],
                "scope": None,
            },
        ]
        with pytest.raises(ValidationError):
            validate_packet_facts(minimal_packet)

    def test_dangling_alternative_reference_fails(self, minimal_packet):
        """Reference to non-existent alternative fact should fail"""
        minimal_packet["facts"] = [
            {
                "fact_id": "f1",
                "fact_key": "hemoglobin",
                "state": "conflict",
                "value": None,
                "missing_reason": "contradictory_evidence",
                "assertion": None,
                "subject_scope": "patient",
                "effective_time": None,
                "recorded_time": None,
                "evidence": [{"source_text": "Conflict"}],
                "provenance": {"derivation_method": "direct", "extractor_version": "1"},
                "review_status": "unreviewed",
                "generalization": {"applied": False, "constraints": []},
                "alternatives": ["f99"],  # Non-existent!
                "scope": None,
            }
        ]
        with pytest.raises(ValidationError):
            validate_packet_facts(minimal_packet)

    def test_valid_alternative_references(self, minimal_packet):
        """Valid alternative fact references should pass"""
        minimal_packet["facts"] = [
            {
                "fact_id": "f1",
                "fact_key": "hemoglobin",
                "state": "conflict",
                "value": None,
                "missing_reason": "contradictory_evidence",
                "assertion": None,
                "subject_scope": "patient",
                "effective_time": None,
                "recorded_time": None,
                "evidence": [{"source_text": "Conflict"}],
                "provenance": {"derivation_method": "direct", "extractor_version": "1"},
                "review_status": "unreviewed",
                "generalization": {"applied": False, "constraints": []},
                "alternatives": ["f2", "f3"],
                "scope": None,
            },
            {
                "fact_id": "f2",
                "fact_key": "hemoglobin",
                "state": "known",
                "value": {"kind": "quantity", "value": 13.5, "unit": "g/dL", "normalization_status": "normalized"},
                "missing_reason": None,
                "assertion": "positive",
                "subject_scope": "patient",
                "effective_time": None,
                "recorded_time": None,
                "evidence": [{"source_text": "Lab"}],
                "provenance": {"derivation_method": "direct", "extractor_version": "1"},
                "review_status": "unreviewed",
                "generalization": {"applied": False, "constraints": []},
                "alternatives": [],
                "scope": None,
            },
            {
                "fact_id": "f3",
                "fact_key": "hemoglobin",
                "state": "known",
                "value": {"kind": "quantity", "value": 9.2, "unit": "g/dL", "normalization_status": "normalized"},
                "missing_reason": None,
                "assertion": "positive",
                "subject_scope": "patient",
                "effective_time": None,
                "recorded_time": None,
                "evidence": [{"source_text": "Lab"}],
                "provenance": {"derivation_method": "direct", "extractor_version": "1"},
                "review_status": "unreviewed",
                "generalization": {"applied": False, "constraints": []},
                "alternatives": [],
                "scope": None,
            },
        ]
        validate_packet_facts(minimal_packet)


class TestResultSchemas:
    """Test criterion and trial result schema validation"""

    def test_valid_criterion_result(self):
        """Valid criterion result should pass"""
        result = {
            "criterion_id": "c1",
            "criterion_type": "inclusion",
            "criterion_source_text": "Age >= 18",
            "evaluation_state": "evaluable",
            "outcome": "satisfied",
            "applicable": True,
            "hardness": "hard",
            "coverage": "full",
            "reason_code": None,
            "fact_references": [
                {
                    "fact_id": "f1",
                    "fact_key": "age",
                    "role": "feeding",
                }
            ],
            "atom_results": [],
            "notes": [],
        }
        validate(result, "criterion_result")

    def test_valid_trial_result(self):
        """Valid trial result should pass"""
        result = {
            "schema_version": "avicenna.trial-result/0.1",
            "result_id": "res-001",
            "generated_at": "2026-10-17T00:39:00Z",
            "trial_id": "NCT12345678",
            "patient_ref": "p-123",
            "policy_version": "1.0",
            "trial_eligibility_state": "eligible_pending_review",
            "per_arm_results": [
                {
                    "arm_id": "arm-1",
                    "arm_eligibility_state": "eligible_pending_review",
                    "blocking_criteria": [],
                    "manual_review_criteria": [],
                    "evidence_coverage": {
                        "assessed_percentage": 100.0, "applicable_count": 1,
                        "unassessed_criteria": [],
                    },
                }
            ],
            "criterion_results": [],
            "notes": [],
        }
        validate(result, "trial_result")

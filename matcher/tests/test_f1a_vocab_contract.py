"""F1a: Vocabulary contract test — pins §8.1/§8.2/§6 enums to prevent drift

This test explicitly asserts that the enum sets in types.py and schemas
equal the normative definitions from MATCHER_DESIGN.md §8.1, §8.2, §6.
If the design changes, this test will fail loudly, preventing silent drift.
"""

import json
import pytest
from pathlib import Path

from avicenna_matcher import (
    EvaluationState,
    EligibilityState,
    Outcome,
    Hardness,
    FactAssertion,
    NormalizationStatus,
)


SCHEMA_DIR = Path(__file__).parent.parent / "schemas"


# §8.1 definitions (normative)
EXPECTED_EVALUATION_STATE = {"evaluable", "missing", "stale", "conflict", "unsupported", "not_applicable", "opaque", "manual_review"}
EXPECTED_ELIGIBILITY_STATE = {"ineligible", "eligible_pending_review", "needs_chart_review", "manual_review"}

# §8.2 definitions (normative)
EXPECTED_OUTCOME = {"satisfied", "resolved_disqualifier", "clear", "unresolved", "non_blocking", "not_applicable"}

# §6 definitions (hardness dropped "soft")
EXPECTED_HARDNESS = {"hard", "procedural_pre_screen"}

# Assertion types (§PATIENT_MATCHING_FORMAT_STANDARD with not_applicable added)
EXPECTED_FACT_ASSERTION = {"positive", "explicit_negative", "suspected", "historical", "not_applicable"}

# Normalization status (§A5, corrected from {normalized, original, unknown})
EXPECTED_NORMALIZATION_STATUS = {"validated", "unmapped", "unsupported"}


class TestVocabContract:
    """Verify types.py enums match §8.1/§8.2/§6 normative definitions"""

    def test_evaluation_state_enum_matches_design(self):
        """EvaluationState enum must equal §8.1"""
        actual = {e.value for e in EvaluationState}
        assert actual == EXPECTED_EVALUATION_STATE, (
            f"EvaluationState mismatch (§8.1)\n"
            f"Expected: {sorted(EXPECTED_EVALUATION_STATE)}\n"
            f"Actual: {sorted(actual)}\n"
            f"Missing: {EXPECTED_EVALUATION_STATE - actual}\n"
            f"Extra: {actual - EXPECTED_EVALUATION_STATE}"
        )

    def test_eligibility_state_enum_matches_design(self):
        """EligibilityState enum must equal §8.1 (no bare 'eligible' or 'undetermined')"""
        actual = {e.value for e in EligibilityState}
        assert actual == EXPECTED_ELIGIBILITY_STATE, (
            f"EligibilityState mismatch (§8.1)\n"
            f"Expected: {sorted(EXPECTED_ELIGIBILITY_STATE)}\n"
            f"Actual: {sorted(actual)}\n"
            f"Missing: {EXPECTED_ELIGIBILITY_STATE - actual}\n"
            f"Extra: {actual - EXPECTED_ELIGIBILITY_STATE}"
        )

    def test_outcome_enum_matches_design(self):
        """Outcome enum must equal §8.2 (not pass/fail/unknown)"""
        actual = {e.value for e in Outcome}
        assert actual == EXPECTED_OUTCOME, (
            f"Outcome mismatch (§8.2)\n"
            f"Expected: {sorted(EXPECTED_OUTCOME)}\n"
            f"Actual: {sorted(actual)}\n"
            f"Missing: {EXPECTED_OUTCOME - actual}\n"
            f"Extra: {actual - EXPECTED_OUTCOME}"
        )

    def test_hardness_enum_matches_design(self):
        """Hardness enum must equal §6 (no 'soft')"""
        actual = {e.value for e in Hardness}
        assert actual == EXPECTED_HARDNESS, (
            f"Hardness mismatch (§6)\n"
            f"Expected: {sorted(EXPECTED_HARDNESS)}\n"
            f"Actual: {sorted(actual)}\n"
            f"Missing: {EXPECTED_HARDNESS - actual}\n"
            f"Extra: {actual - EXPECTED_HARDNESS}"
        )

    def test_fact_assertion_enum_matches_design(self):
        """FactAssertion enum must include not_applicable"""
        actual = {e.value for e in FactAssertion}
        assert actual == EXPECTED_FACT_ASSERTION, (
            f"FactAssertion mismatch\n"
            f"Expected: {sorted(EXPECTED_FACT_ASSERTION)}\n"
            f"Actual: {sorted(actual)}\n"
            f"Missing: {EXPECTED_FACT_ASSERTION - actual}\n"
            f"Extra: {actual - EXPECTED_FACT_ASSERTION}"
        )

    def test_normalization_status_enum_matches_design(self):
        """NormalizationStatus enum must equal §A5 (not normalized/original/unknown)"""
        actual = {e.value for e in NormalizationStatus}
        assert actual == EXPECTED_NORMALIZATION_STATUS, (
            f"NormalizationStatus mismatch (§A5)\n"
            f"Expected: {sorted(EXPECTED_NORMALIZATION_STATUS)}\n"
            f"Actual: {sorted(actual)}\n"
            f"Missing: {EXPECTED_NORMALIZATION_STATUS - actual}\n"
            f"Extra: {actual - EXPECTED_NORMALIZATION_STATUS}"
        )


class TestSchemasMatch:
    """Verify schemas match types.py and design"""

    def test_patient_packet_schema_normalization_status(self):
        """patient_packet.schema.json must have correct normalization_status enum"""
        with open(SCHEMA_DIR / "patient_packet.schema.json") as f:
            schema = json.load(f)
        
        # Find QuantityValue definition
        quantity_def = schema["definitions"]["QuantityValue"]
        norm_status_enum = quantity_def["properties"]["normalization_status"]["enum"]
        
        assert set(norm_status_enum) == EXPECTED_NORMALIZATION_STATUS, (
            f"patient_packet normalization_status mismatch\n"
            f"Expected: {sorted(EXPECTED_NORMALIZATION_STATUS)}\n"
            f"Actual: {sorted(norm_status_enum)}"
        )

    def test_criterion_result_schema_evaluation_state(self):
        """criterion_result.schema.json evaluation_state must match design"""
        with open(SCHEMA_DIR / "criterion_result.schema.json") as f:
            schema = json.load(f)
        
        eval_state_enum = schema["properties"]["evaluation_state"]["enum"]
        
        assert set(eval_state_enum) == EXPECTED_EVALUATION_STATE, (
            f"criterion_result evaluation_state mismatch\n"
            f"Expected: {sorted(EXPECTED_EVALUATION_STATE)}\n"
            f"Actual: {sorted(eval_state_enum)}"
        )

    def test_criterion_result_schema_outcome(self):
        """criterion_result.schema.json outcome must match §8.2"""
        with open(SCHEMA_DIR / "criterion_result.schema.json") as f:
            schema = json.load(f)
        
        outcome_enum = schema["properties"]["outcome"]["enum"]
        
        assert set(outcome_enum) == EXPECTED_OUTCOME, (
            f"criterion_result outcome mismatch\n"
            f"Expected: {sorted(EXPECTED_OUTCOME)}\n"
            f"Actual: {sorted(outcome_enum)}"
        )

    def test_criterion_result_schema_hardness(self):
        """criterion_result.schema.json hardness must match §6"""
        with open(SCHEMA_DIR / "criterion_result.schema.json") as f:
            schema = json.load(f)
        
        hardness_enum = schema["properties"]["hardness"]["enum"]
        
        assert set(hardness_enum) == EXPECTED_HARDNESS, (
            f"criterion_result hardness mismatch\n"
            f"Expected: {sorted(EXPECTED_HARDNESS)}\n"
            f"Actual: {sorted(hardness_enum)}"
        )

    def test_trial_result_schema_trial_eligibility_state(self):
        """trial_result.schema.json trial_eligibility_state must match §8.1"""
        with open(SCHEMA_DIR / "trial_result.schema.json") as f:
            schema = json.load(f)
        
        trial_elig_enum = schema["properties"]["trial_eligibility_state"]["enum"]
        
        assert set(trial_elig_enum) == EXPECTED_ELIGIBILITY_STATE, (
            f"trial_result trial_eligibility_state mismatch\n"
            f"Expected: {sorted(EXPECTED_ELIGIBILITY_STATE)}\n"
            f"Actual: {sorted(trial_elig_enum)}"
        )

    def test_trial_result_schema_arm_eligibility_state(self):
        """trial_result.schema.json PerArmResult arm_eligibility_state must match §8.1"""
        with open(SCHEMA_DIR / "trial_result.schema.json") as f:
            schema = json.load(f)
        
        arm_elig_enum = schema["definitions"]["PerArmResult"]["properties"]["arm_eligibility_state"]["enum"]
        
        assert set(arm_elig_enum) == EXPECTED_ELIGIBILITY_STATE, (
            f"trial_result arm_eligibility_state mismatch\n"
            f"Expected: {sorted(EXPECTED_ELIGIBILITY_STATE)}\n"
            f"Actual: {sorted(arm_elig_enum)}"
        )

    def test_criteria_pack_schema_hardness(self):
        """criteria_pack.schema.json hardness must match §6"""
        with open(SCHEMA_DIR / "criteria_pack.schema.json") as f:
            schema = json.load(f)
        
        criterion_hardness = schema["definitions"]["Criterion"]["properties"]["hardness"]["enum"]
        
        assert set(criterion_hardness) == EXPECTED_HARDNESS, (
            f"criteria_pack criterion hardness mismatch\n"
            f"Expected: {sorted(EXPECTED_HARDNESS)}\n"
            f"Actual: {sorted(criterion_hardness)}"
        )

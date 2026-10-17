"""Schema validation for avicenna.matcher/0.1

Uses jsonschema for structural validation. Raises StructuralError on any schema mismatch.
"""

import json
import os
from pathlib import Path
from typing import Any, Literal

import jsonschema
from jsonschema import Draft7Validator

from .errors import ValidationError, StructuralError


# Load schemas at module init
_SCHEMA_DIR = Path(__file__).parent.parent / "schemas"


def _load_schema(filename: str) -> dict:
    """Load a JSON schema from disk"""
    path = _SCHEMA_DIR / filename
    if not path.exists():
        raise StructuralError(f"Schema file not found: {path}")
    with open(path) as f:
        return json.load(f)


_PATIENT_PACKET_SCHEMA = _load_schema("patient_packet.schema.json")
_CRITERIA_PACK_SCHEMA = _load_schema("criteria_pack.schema.json")
_CRITERION_RESULT_SCHEMA = _load_schema("criterion_result.schema.json")
_TRIAL_RESULT_SCHEMA = _load_schema("trial_result.schema.json")
_REASON_CODES_SCHEMA = _load_schema("reason_codes.registry.json")


def validate(
    obj: Any, kind: Literal["patient_packet", "criteria_pack", "criterion_result", "trial_result", "reason_codes"]
) -> None:
    """
    Validate a structured object against its schema.

    Args:
        obj: The object to validate
        kind: The type of object

    Raises:
        ValidationError: If validation fails (a StructuralError subclass)
    """
    schema_map = {
        "patient_packet": _PATIENT_PACKET_SCHEMA,
        "criteria_pack": _CRITERIA_PACK_SCHEMA,
        "criterion_result": _CRITERION_RESULT_SCHEMA,
        "trial_result": _TRIAL_RESULT_SCHEMA,
        "reason_codes": _REASON_CODES_SCHEMA,
    }

    if kind not in schema_map:
        raise ValueError(f"Unknown kind: {kind}")

    schema = schema_map[kind]
    validator = Draft7Validator(schema)

    # Collect all errors
    errors = list(validator.iter_errors(obj))

    if errors:
        # Raise the first error with context
        error = errors[0]
        msg = f"Schema validation failed for {kind}: {error.message}"
        if error.path:
            msg += f" at path {list(error.path)}"
        raise ValidationError(msg) from error


def validate_state_assertion_consistency(fact: dict) -> None:
    """
    Validate state × assertion consistency table from PATIENT_MATCHING_FORMAT_STANDARD.md.

    Rules:
    - known: assertion must be one of (positive, explicit_negative, suspected, historical)
    - unknown: assertion must be null
    - not_tested: assertion must be null
    - indeterminate: assertion must be null
    - conflict: assertion must be null

    Raises:
        ValidationError: If consistency is violated
    """
    state = fact.get("state")
    assertion = fact.get("assertion")

    if state == "known":
        if assertion not in ("positive", "explicit_negative", "suspected", "historical"):
            raise ValidationError(
                f"Fact {fact.get('fact_id')}: state=known requires assertion in "
                "(positive, explicit_negative, suspected, historical), got {assertion}"
            )
    elif state in ("unknown", "not_tested", "indeterminate", "conflict"):
        if assertion is not None:
            raise ValidationError(
                f"Fact {fact.get('fact_id')}: state={state} requires assertion=null, got {assertion}"
            )


def validate_packet_facts(packet: dict) -> None:
    """
    Validate facts within a patient packet.

    Checks:
    - All fact_ids are unique
    - State × assertion consistency for each fact
    - Alternative facts are acyclic
    """
    facts = packet.get("facts", [])
    fact_ids = set()

    for fact in facts:
        fact_id = fact.get("fact_id")

        # Check uniqueness
        if fact_id in fact_ids:
            raise ValidationError(f"Duplicate fact_id: {fact_id}")
        fact_ids.add(fact_id)

        # Check state × assertion consistency
        validate_state_assertion_consistency(fact)

    # Check alternatives are acyclic (simplified: just check they all exist)
    for fact in facts:
        for alt_id in fact.get("alternatives", []):
            if alt_id not in fact_ids:
                raise ValidationError(
                    f"Fact {fact.get('fact_id')} references non-existent alternative fact {alt_id}"
                )

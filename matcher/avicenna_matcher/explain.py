"""Reason codes and fact references for explainable results (MATCHER_DESIGN §8.1, §9 step 7).

Every UNKNOWN or not_applicable criterion/atom result carries exactly one reason
code from REASON_CODES. The registry document produced by `registry_document()`
validates against `schemas/reason_codes.registry.json`.
"""

from typing import Any, Dict, List

REGISTRY_SCHEMA_VERSION = "avicenna.reason-codes/0.1"

# code -> (category, description)
_CODES: Dict[str, tuple] = {
    # structural / logic
    "logic_unspecified": ("evaluation_blocking", "Criterion has several atoms but no logic.op; fold is not assumed"),
    "logic_custom": ("evaluation_blocking", "Criterion logic.op is 'custom'; needs human interpretation"),
    "logic_not_arity": ("evaluation_blocking", "logic.op 'not' requires exactly one non-gate atom"),
    "opaque_text": ("evaluation_blocking", "Criterion arrived as opaque text or without atoms"),
    "partial_atomization": ("evaluation_blocking", "Criterion only partially atomized; a disqualifier is not asserted from a subset of its conditions"),
    "procedural_not_evaluable": ("evaluation_blocking", "Procedural/consent requirement is not evaluable from the patient packet"),
    "predicate_unsupported": ("evaluation_blocking", "Atom shape is not supported by this matcher version"),
    # applicability
    "gate_not_met": ("applicability", "Applicability gate resolved FALSE; criterion does not apply"),
    "gate_unresolved": ("applicability", "Applicability gate could not be resolved"),
    # evidence absent / stale
    "fact_missing": ("evidence_absent", "No compatible patient fact for the required fact_key"),
    "fact_not_known": ("evidence_absent", "Selected fact has state unknown / not_tested / indeterminate"),
    "reference_missing": ("evidence_absent", "Patient-specific reference (e.g. ULN) is absent or not from the same measurement"),
    "absence_not_established": ("evidence_absent", "No criterion-scoped explicit negative or subsuming reviewed completeness"),
    "guard_unresolved": ("evidence_ambiguous", "Guard is unknown and branches disagree under supervaluation"),
    "anchor_missing": ("evidence_stale", "Anchor-relative predicate with null evaluation anchor"),
    "recency_unbounded": ("evidence_stale", "Screening-state predicate with no recency bound (no atom window_days "
                          "and no site screening_recency_days for the key); an old value cannot stand for now"),
    # ambiguity / conflict
    "value_straddles_threshold": ("evidence_ambiguous", "Patient value/band straddles the threshold"),
    "assertion_uncertain": ("evidence_ambiguous", "Fact assertion is suspected/uncertain"),
    "ref_unresolved": ("evidence_ambiguous", "Referenced criterion is unresolved"),
    "exposure_scope_ambiguous": ("evidence_ambiguous", "Positive exposure found but its setting is not established"),
    "concept_unspecified": ("concept_unsupported", "Atom on a generic multi-concept key (biomarker.result, lab.result) "
                            "without a concept; any marker/analyte could answer"),
    "relation_unsupported_for_key": ("temporal", "Existential/windowed relation on a single-valued snapshot key "
                                     "(age, administrative gender); use current / at_screening"),
    "window_quantifier_unspecified": ("temporal", "Windowed predicate without an explicit quantifier "
                                      "(exists | latest); the window alone does not fix its semantics"),
    "time_precision_insufficient": ("temporal", "Fact time is too coarse to place it inside/outside the "
                                    "anchor or window, and it may be decisive"),
    "time_basis_incompatible": ("temporal", "Fact time is on a different or unknown time basis "
                                "(shifted vs unshifted); no shared chronology"),
    "exposure_membership_unknown": ("evidence_ambiguous", "Positive exposure whose membership in the queried concepts "
                                    "is not established under the pinned registry (§5.4)"),
    "fact_conflict": ("evidence_conflict", "Fact is in conflict state, or contemporaneous equal-authority facts disagree"),
    "assay_discordant": ("evidence_ambiguous", "Latest biomarker results from different assays/specimens disagree; "
                         "recency does not supersede across assays"),
    # concept / unit support
    "unit_unsupported": ("concept_unsupported", "Quantity normalization is not validated"),
    "unit_mismatch": ("concept_unsupported", "Fact unit differs from threshold unit; no conversion is attempted"),
    "value_type_unsupported": ("concept_unsupported", "Fact value type cannot be compared with this comparator/threshold"),
    "concept_system_mismatch": ("concept_unsupported", "Coded value system differs from the criterion's code system"),
}

REASON_CODES = frozenset(_CODES)


def category(code: str) -> str:
    return _CODES[code][0]


def registry_document() -> Dict[str, Any]:
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "codes": {
            code: {"category": cat, "description": desc}
            for code, (cat, desc) in sorted(_CODES.items())
        },
    }


def merge_fact_refs(atom_refs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Deduplicate (fact_id, fact_key, role) triples, preserving first-seen order."""
    seen = set()
    out = []
    for r in atom_refs:
        key = (r["fact_id"], r["fact_key"], r["role"])
        if key not in seen:
            seen.add(key)
            out.append({"fact_id": r["fact_id"], "fact_key": r["fact_key"], "role": r["role"]})
    return out

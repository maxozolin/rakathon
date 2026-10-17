"""Enrollment-likelihood heuristic — a separate, explicitly uncalibrated axis.

The matcher deliberately emits no score (MATCHER_DESIGN §8/§12): its verdict is the three-valued
`eligibility_state`. Clinicians still need to triage a long list, so this module attaches a rough
*estimated probability that the patient will pass screening* to every non-excluded trial:

    w      = resolved hard criteria / applicable hard criteria          (evidence weight)
    p_open = Π prior(unresolved hard criterion)
    p      = (w · p_open + (1 − w) · BASE_RATE) × Π penalties,  capped at P_CAP

With no evidence the estimate falls back to BASE_RATE (a typical screen-pass rate for a
diagnosis-matched referral); every criterion the matcher resolves moves it toward the evidence.

- resolved criteria (satisfied / clear / not applicable / procedural) contribute 1.0 — the risk
  they carried is gone;
- each unresolved hard criterion contributes a prior pass rate that depends on polarity (inclusion
  bullets are where trials select; exclusions rarely bite) and on whether it was atomized (only
  the patient data is missing) or is opaque text (not even the requirement is machine-readable);
- registry sex / CTIS age-group restrictions that disagree with the record contribute strong
  penalties (the matcher itself refuses to disqualify on those semantic mismatches);
- a pack that is known to be incomplete (CTIS publishes only *principal* criteria, or no criteria
  are in the snapshot at all) contributes a penalty for criteria we cannot see;
- if the patient's coded diagnosis maps to search terms and none appears in the trial's title or
  conditions, a relevance penalty applies.

So curating a trial (atomizing it with the `trial-data-format` skill) and completing the patient
packet both move the estimate toward evidence, which is the intended incentive.

Hard rules: `ineligible` → p = 0 (it is in the excluded list, never ranked). The probability can
never promote a trial's eligibility_state, and it must be presented as an estimate.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .catalog import fold
from .packs import MAX_AGE_CRITERION_ID, MIN_AGE_CRITERION_ID, SEX_CRITERION_ID, UNPUBLISHED_CRITERION_ID

MODEL_VERSION = "avicenna-prob-heuristic/0.1"

PRIORS = {
    ("inclusion", "atomized"): 0.80,
    ("inclusion", "opaque"): 0.85,
    ("exclusion", "atomized"): 0.90,
    ("exclusion", "opaque"): 0.95,
}
BASE_RATE = 0.35
SEX_MISMATCH = 0.05
AGE_GROUP_MISMATCH = 0.40
PRINCIPAL_CRITERIA_ONLY = 0.70
CRITERIA_UNPUBLISHED = 0.50
DIAGNOSIS_MISMATCH = 0.30
P_CAP = 0.95
_RESOLVED = {"satisfied", "clear", "non_blocking", "not_applicable"}

DISCLAIMER = ("Heuristic estimate (" + MODEL_VERSION + "), not calibrated on outcomes. It ranks candidates for "
              "review; it is not an eligibility decision. eligibility_state is the matcher's verdict; final "
              "eligibility is decided by the study team at screening.")


def _confidence(resolved: int, applicable: int) -> str:
    if applicable == 0:
        return "low"
    r = resolved / applicable
    return "high" if r >= 0.7 else "medium" if r >= 0.4 else "low"


def diagnosis_relevant(profile: Dict[str, Any], trial: Optional[Dict[str, Any]]) -> Optional[bool]:
    terms = profile.get("diagnosis_terms") or []
    if not terms or not trial:
        return None
    hay = fold(" ".join([trial.get("title") or "", trial.get("short_title") or ""] + list(trial.get("conditions") or [])))
    return any(fold(t) in hay for t in terms)


def estimate(result: Dict[str, Any], pack: Dict[str, Any], profile: Dict[str, Any],
             trial: Optional[Dict[str, Any]] = None, pack_source: Optional[str] = None) -> Dict[str, Any]:
    state = result["trial_eligibility_state"]
    by_id = {c["criterion_id"]: c for c in pack["criteria"]}
    if state == "ineligible":
        return {"probability": 0.0, "confidence": "high", "model_version": MODEL_VERSION,
                "factors": [], "explanation": "A hard criterion is resolved against the patient."}

    criterion_factors: List[Dict[str, Any]] = []
    penalties: List[Dict[str, Any]] = []
    p_open = 1.0
    resolved = applicable = 0
    for cr in result["criterion_results"]:
        if cr["hardness"] != "hard" or cr["outcome"] == "not_applicable":
            continue
        applicable += 1
        if cr["outcome"] in _RESOLVED:
            resolved += 1
            continue
        crit = by_id.get(cr["criterion_id"], {})
        entry = {"criterion_id": cr["criterion_id"], "criterion_type": cr["criterion_type"],
                 "source_text": cr["criterion_source_text"]}
        if cr["criterion_id"] in (MIN_AGE_CRITERION_ID, MAX_AGE_CRITERION_ID) and \
                crit.get("completeness_note") == "partial" and cr.get("fact_references"):
            penalties.append({**entry, "factor": AGE_GROUP_MISMATCH,
                              "why": "patient's age is not within the trial's declared population age groups "
                                     "(indicative only; confirm the protocol's age limits)"})
            continue
        if cr["criterion_id"] == SEX_CRITERION_ID and profile.get("gender"):
            allowed = ((crit.get("atoms") or [{}])[0].get("threshold") or {}).get("code")
            if allowed and allowed != profile["gender"]:
                penalties.append({**entry, "factor": SEX_MISMATCH,
                                  "why": f"trial enrolls {allowed} participants; the record's administrative "
                                         f"gender is {profile['gender']}"})
                continue
        kind = "opaque" if crit.get("completeness_note") == "opaque_text" or not crit.get("atoms") else "atomized"
        f = PRIORS[(cr["criterion_type"], kind)]
        p_open *= f
        criterion_factors.append({**entry, "factor": f, "why": (
            "requirement is free text, not machine-checked yet" if kind == "opaque"
            else f"patient data missing or ambiguous ({cr.get('reason_code') or cr['evaluation_state']})")})

    if any(c["criterion_id"] == UNPUBLISHED_CRITERION_ID for c in pack["criteria"]):
        penalties.append({"criterion_id": None, "criterion_type": "unseen_criteria", "source_text": None,
                          "factor": CRITERIA_UNPUBLISHED,
                          "why": "no eligibility criteria in the local registry snapshot"})
    elif (trial or {}).get("registry") == "ctis" and pack_source == "registry":
        penalties.append({"criterion_id": None, "criterion_type": "unseen_criteria", "source_text": None,
                          "factor": PRINCIPAL_CRITERIA_ONLY,
                          "why": "CTIS publishes only the principal criteria; the protocol has more"})
    rel = diagnosis_relevant(profile, trial)
    if rel is False:
        penalties.append({"criterion_id": None, "criterion_type": "relevance", "source_text": None,
                          "factor": DIAGNOSIS_MISMATCH,
                          "why": "patient's coded diagnosis not found in the trial title/conditions"})

    w = resolved / applicable if applicable else 0.0
    p = w * p_open + (1.0 - w) * BASE_RATE
    for pen in penalties:
        p *= pen["factor"]
    p = min(p, P_CAP)
    factors = sorted(penalties + criterion_factors, key=lambda x: x["factor"])
    expl = (f"{resolved}/{applicable} hard criteria resolved in the patient's favour (evidence weight {w:.2f}); "
            f"{len(criterion_factors)} open criteria, {len(penalties)} penalty factor(s).")
    # Registry-derived packs only check structured age/sex: never more than low confidence.
    confidence = "low" if pack_source == "registry" else _confidence(resolved, applicable)
    return {"probability": round(p, 3), "confidence": confidence,
            "model_version": MODEL_VERSION, "diagnosis_relevant": rel,
            "hard_resolved": resolved, "hard_applicable": applicable, "evidence_weight": round(w, 3),
            "base_rate": BASE_RATE, "factors": factors, "explanation": expl}

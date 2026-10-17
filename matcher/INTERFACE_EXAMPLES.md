# Matcher interface — worked examples

**For:** `avicenna.matcher/0.1` (`matcher/avicenna_matcher`).
**Purpose:** show the shapes that go in and come out, with fully **invented** data.
**Safety:** every patient object here is synthetic (`environment: "synthetic_demo"`). No real patient data appears in this repo, ever.

---

## 1. The interface in one picture

```
   CriteriaPack P            Patient packet Q            Evaluation context
 (one trial, per-arm      (synthetic facts +           (anchor, mode,
  typed criteria)          coverage + completeness)     policy_version, site)
         \                        |                        /
          \                       |                       /
           +--------->   avicenna_matcher   <------------+
                                  |
                                  v
                          Trial result
            (per-criterion outcomes + per-arm eligibility_state
                   + trial roll-up, every result traceable)
```

Three inputs in, one `trial_result` out. The evaluator is deterministic and offline: same inputs + `policy_version` ⇒ same output; no network, no clock (timestamps/ids are injected).

---

## 2. Input A — a (made-up) CriteriaPack

Invented trial `demo:TRIAL-001`, one arm, four criteria chosen to exercise the engine: a simple threshold, a relative-to-reference lab, a coverage-aware `not_exists`, and a procedural item.

```jsonc
{
  "schema_version": "avicenna.criteria-pack/0.1",
  "pack_id": "pack-demo-001",
  "trial_id": "demo:TRIAL-001",
  "criteria_completeness": "complete",      // pack built from full public text
  "generated_at": "2026-10-17T00:00:00Z",
  "arms": [{ "arm_id": "A", "label": "Main cohort" }],
  "criteria": [
    {
      "criterion_id": "demo:TRIAL-001:inc:1",
      "criterion_type": "inclusion",
      "hardness": "hard",
      "arm_scope": null,                     // null = whole trial
      "source_text": "Adult patients aged ≥ 18 years.",
      "completeness_note": "complete",
      "atoms": [
        {
          "atom_id": "demo:TRIAL-001:inc:1:a",
          "predicate_type": "simple_comparison",
          "arm_scope": null,
          "source_text": "aged ≥ 18 years",
          "fact_key": "demographics.age",
          "comparator": "ge",
          "threshold": 18
        }
      ]
    },
    {
      "criterion_id": "demo:TRIAL-001:inc:2",
      "criterion_type": "inclusion",
      "hardness": "hard",
      "arm_scope": null,
      "source_text": "Total bilirubin < 1.5 × ULN.",
      "completeness_note": "complete",
      "atoms": [
        {
          "atom_id": "demo:TRIAL-001:inc:2:a",
          "predicate_type": "relative_to_reference",
          "arm_scope": null,
          "source_text": "bilirubin < 1.5 × ULN",
          "fact_key": "lab.bilirubin",
          "comparator": "lt",
          "reference_key": "lab.bilirubin.reference_high",   // the patient's own ULN
          "reference_offset": 1.5                            // 1.5 × that ULN
        }
      ]
    },
    {
      "criterion_id": "demo:TRIAL-001:exc:1",
      "criterion_type": "exclusion",
      "hardness": "hard",
      "arm_scope": null,
      "source_text": "No prior PARP inhibitor for advanced disease.",
      "completeness_note": "complete",
      "atoms": [
        {
          "atom_id": "demo:TRIAL-001:exc:1:a",
          "predicate_type": "not_exists",
          "arm_scope": null,
          "source_text": "no prior PARP inhibitor (advanced)",
          "fact_key": "therapy.event",
          "threshold": { "classes": ["parp_inhibitor"], "setting": "advanced", "time_basis": "lifetime" }
        }
      ]
    },
    {
      "criterion_id": "demo:TRIAL-001:proc:1",
      "criterion_type": "inclusion",
      "hardness": "procedural_pre_screen",
      "arm_scope": null,
      "source_text": "Signed informed consent.",
      "completeness_note": "complete",
      "atoms": [
        { "atom_id": "demo:TRIAL-001:proc:1:a", "predicate_type": "procedural",
          "arm_scope": null, "source_text": "informed consent" }
      ]
    }
  ]
}
```

---

## 3. Input B — a (synthetic) patient packet

Fictional patient `synthetic-patient-001`. Facts are abbreviated to the fields that drive matching; each real fact also carries `provenance`, `review_status`, and `generalization` per `PATIENT_MATCHING_FORMAT_STANDARD.md`.

```jsonc
{
  "schema_version": "avicenna.patient-packet/1.1.0",
  "packet_id": "synthetic-packet-001",
  "patient_ref": "synthetic-patient-001",
  "generated_at": "2026-10-17T09:00:00Z",
  "environment": "synthetic_demo",
  "source_snapshot": { "snapshot_id": "syn-v1", "ingestion_state": "complete",
                       "extractor_version": "syn-ex-v1", "terminology_version": "syn-term-v1" },
  "evaluation_context": {
    "mode": "shifted_demo",
    "anchor": { "kind": "point", "value": "2026-04-01", "precision": "day",
                "time_basis": "shifted_patient_local" },
    "absolute_screening_recency_allowed": false,
    "policy_version": "eval-policy-v1"
  },
  "facts": [
    {
      "fact_id": "age-1", "fact_key": "demographics.age", "state": "known",
      "value": { "kind": "band", "lower_inclusive": 60, "upper_inclusive": 64, "unit": "years" },
      "missing_reason": null, "assertion": "positive", "subject_scope": "patient",
      "effective_time": null, "recorded_time": null,
      "evidence": [{ "source_kind": "structured", "verification_status": "source_assertion" }]
      // + provenance / review_status / generalization per schema
    },
    {
      "fact_id": "bili-1", "fact_key": "lab.bilirubin", "state": "known",
      "value": { "kind": "quantity", "value": 0.8, "unit": "mg/dL", "normalization_status": "validated" },
      "missing_reason": null, "assertion": "positive", "subject_scope": "patient",
      "effective_time": { "kind": "point", "value": "2026-03-15", "precision": "day",
                          "time_basis": "shifted_patient_local" }, "recorded_time": null,
      "evidence": [{ "source_kind": "lab", "verification_status": "reviewed" }],
      "qualifiers": { "reference_high": 1.2 }        // this patient's ULN
    }
    // No therapy.event facts, and no completeness assertion for therapy → see §5 scenario 4.
  ],
  "coverage": {
    "assessed_fact_keys": ["demographics.age", "lab.bilirubin"],
    "unassessed_fact_keys": ["therapy.event"],
    "completeness": []                               // nothing certified comprehensive
  },
  "warnings": ["shifted_dates_not_real_screening_time"]
}
```

---

## 4. Output — the `trial_result`

Evaluating the packet above against the pack:

```jsonc
{
  "schema_version": "avicenna.trial-result/0.1",
  "result_id": "<injected>",                 // injected, not clock/uuid-generated, for determinism
  "generated_at": "<injected>",
  "trial_id": "demo:TRIAL-001",
  "patient_ref": "synthetic-patient-001",
  "policy_version": "eval-policy-v1",
  "trial_eligibility_state": "needs_chart_review",
  "per_arm_results": [
    {
      "arm_id": "A",
      "arm_eligibility_state": "needs_chart_review",
      "blocking_criteria": [],
      "manual_review_criteria": [],
      "evidence_coverage": { "completeness": "full", "partial_count": 0, "unknown_count": 0 }
    }
  ],
  "criterion_results": [
    { "criterion_id": "demo:TRIAL-001:inc:1", "criterion_type": "inclusion", "hardness": "hard",
      "evaluation_state": "evaluable", "outcome": "satisfied", "applicable": true,
      "reason_code": null, "fact_references": [{ "fact_id": "age-1", "role": "feeding" }],
      "criterion_source_text": "Adult patients aged ≥ 18 years.", "coverage": "full",
      "atom_results": [], "notes": [] },

    { "criterion_id": "demo:TRIAL-001:inc:2", "criterion_type": "inclusion", "hardness": "hard",
      "evaluation_state": "evaluable", "outcome": "satisfied", "applicable": true,
      "reason_code": null, "fact_references": [{ "fact_id": "bili-1", "role": "feeding" }],
      "criterion_source_text": "Total bilirubin < 1.5 × ULN.", "coverage": "full",
      "atom_results": [], "notes": ["0.8 < 1.5 × 1.2 (=1.8)"] },

    { "criterion_id": "demo:TRIAL-001:exc:1", "criterion_type": "exclusion", "hardness": "hard",
      "evaluation_state": "missing", "outcome": "unresolved", "applicable": true,
      "reason_code": "absence_not_established", "fact_references": [],
      "criterion_source_text": "No prior PARP inhibitor for advanced disease.", "coverage": "unknown",
      "atom_results": [], "notes": ["therapy.event not assessed as complete; absence-from-silence blocked"] },

    { "criterion_id": "demo:TRIAL-001:proc:1", "criterion_type": "inclusion",
      "hardness": "procedural_pre_screen", "evaluation_state": "missing", "outcome": "non_blocking",
      "applicable": true, "reason_code": "procedural_outstanding", "fact_references": [],
      "criterion_source_text": "Signed informed consent.", "coverage": "unknown",
      "atom_results": [], "notes": ["consent pending; never blocks at pre-screen"] }
  ],
  "notes": []
}
```

**Why `needs_chart_review`, not `eligible_pending_review`:** age and bilirubin are satisfied, consent is non-blocking — but the PARP exclusion is `unresolved` because *no prior-therapy completeness was certified* (absence-from-silence is blocked, §5.4). One unresolved **hard** criterion ⇒ the trial can't reach the near-positive state. This is the engine refusing to promote uncertainty.

---

## 5. Scenario variations (change one thing)

Same pack; toggle one input and watch the verdict move:

| # | Change to the packet | `exc:1` (PARP) | Trial state | Why |
|---|---|---|---|---|
| 1 | *(baseline above)* | `unresolved` | **needs_chart_review** | absence not certified |
| 2 | Add a reviewed, lifetime, advanced-setting completeness assertion for `therapy.event` covering PARP inhibitors, with **no** PARP events | `clear` (predicate false) | **eligible_pending_review** | absence now positively established (§5.4) |
| 3 | Add a `therapy.event` fact: a PARP inhibitor in the advanced setting | `resolved_disqualifier` | **ineligible** | hard exclusion triggered from a *resolved* fact |
| 4 | Add only a **bounded** (last-2-years) completeness assertion | `unresolved` | **needs_chart_review** | bounded window can't clear a *lifetime* criterion |
| 5 | Change age fact to band `[16,17]` | — | **ineligible** | hard inclusion `inc:1` resolves FALSE → disqualifier |
| 6 | Remove the bilirubin `reference_high` qualifier | `inc:2` → `unresolved` | **needs_chart_review** | relative threshold needs the patient's ULN; won't assume one |
| 7 | Set pack `criteria_completeness: "partial"` | (same criteria) | **needs_chart_review** (capped) | incomplete public criteria cap the best achievable state |

Note scenarios 1, 4, 6, 7 all land on `needs_chart_review` for *different* reasons — the `reason_code` and per-criterion `notes` say which, so a clinician sees exactly what to check.

---

## 6. Calling it (library interface)

The current build exposes the pieces; the P6 pipeline will wrap them into one `evaluate(pack, packet, context)` entry. Today:

```python
from avicenna_matcher import (
    validate, OutcomeEvaluator, PerArmAggregator, TrialAggregator,
    CriterionResultBuilder, TrialResultBuilder, TriState,
)

validate(pack, "criteria_pack")        # StructuralError if malformed (A1)
validate(packet, "patient_packet")

# per criterion: resolve facts → evaluate predicate → outcome
outcome = OutcomeEvaluator.evaluate(TriState.FALSE, "inclusion", "hard")   # → Outcome.RESOLVED_DISQUALIFIER
cr = CriterionResultBuilder.build(criterion_id=..., criterion_type=..., outcome=outcome.value, ...)

# per arm, then roll up — note criteria_completeness is passed so the cap applies
arm_state, blocking, manual, coverage = PerArmAggregator.aggregate(
    criterion_results, arm_id="A", criteria_completeness=pack["criteria_completeness"],
)
trial_state, arms = TrialAggregator.aggregate(per_arm_results)

result = TrialResultBuilder.build(
    trial_id=..., patient_ref=..., policy_version="eval-policy-v1",
    trial_eligibility_state=trial_state, per_arm_results=arms,
    criterion_results=criterion_results,
    generated_at="2026-10-17T09:05:00Z", result_id="fixed-id-for-determinism",
)
```

**Reading the output:** branch on `trial_eligibility_state`
(`ineligible | needs_chart_review | manual_review | eligible_pending_review`),
then show `blocking_criteria` and each criterion's `reason_code` + `notes`.
There is no bare `eligible` — promoting a patient to enrolled is a human step, never the matcher's.

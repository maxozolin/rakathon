---
name: patient-data-format
description: Defines how patient data must look before it can be matched to clinical trials — the canonical avicenna.patient-packet/1.1.0 JSON (facts with evidence, time and uncertainty). Use when building, reviewing or fixing a patient packet for the Avicenna trial matcher MCP (screen_patient, match_trial, validate_patient_packet).
license: Proprietary (Rakathon 2026 team 16)
compatibility: Avicenna matcher MCP (avicenna-mcp); avicenna.matcher/0.1
metadata:
  schema_version: "avicenna.patient-packet/1.1.0"
  normative_source: "PATIENT_MATCHING_FORMAT_STANDARD.md; prompts/PATIENT_PACKET_BUILDER_PROMPT.md"
---

# Patient data format for trial matching

The matcher never reads charts. It reads one **patient packet**: a JSON list of *facts*, each with
evidence, time and uncertainty. The matcher is deterministic and fail-closed: anything unknown
stays unresolved and goes to a human. **An honest `unknown` is always safe; an invented or
over-confident fact is the only way to cause harm.**

Full builder prompt: MCP resource `avicenna://docs/patient-packet-builder`.
Complete, valid example: [`example_packet.json`](example_packet.json) (fictional patient).

## Privacy boundary (read first)

- Packets built from real records stay inside the hospital / authorized EU environment.
- Prefer `packet_path` (a local file) over pasting a packet into a chat. Never commit real packets.
- Only pseudonymous `patient_ref`; no names, birth numbers, addresses or free-text copies in locators.
- Examples and few-shot material must be synthetic (`environment: "synthetic_demo"`).

## Envelope

```json
{
  "schema_version": "avicenna.patient-packet/1.1.0",
  "packet_id": "<unique>", "patient_ref": "<pseudonymous>", "generated_at": "<RFC 3339>",
  "environment": "hospital | approved_event | synthetic_demo",
  "source_snapshot": {"snapshot_id": "…", "ingestion_state": "complete | partial | unknown",
                      "extractor_version": "patient-packet-builder/1.0.0+<tool>", "terminology_version": "…"},
  "evaluation_context": {"mode": "prescreen_real_time | shifted_demo | historical_review",
                         "anchor": null, "absolute_screening_recency_allowed": false, "policy_version": "…"},
  "facts": [],
  "coverage": {"assessed_fact_keys": [], "unassessed_fact_keys": [], "completeness": []},
  "warnings": []
}
```

- `anchor` = the screening time, **supplied by the caller**. Never default it to "today". If none,
  `null` (screening-time criteria then stay unresolved — correct).
- De-identified (shifted) dates: `mode: "shifted_demo"`, every `time_basis: "shifted_patient_local"`,
  `absolute_screening_recency_allowed: false`. Never mix shifted and real dates.
- `generated_at` is also used as the result timestamp (the matcher reads no clock).

## Fact anatomy — every field is required

```json
{"fact_id": "ps-1", "fact_key": "performance.status", "state": "known",
 "value": {"kind": "scored_instrument", "instrument": {"system": "http://loinc.org", "code": "89247-1"},
           "registry_version": "avicenna-instruments/1.0.0", "representation": "numeric",
           "no_interconversion": true, "value": 1, "value_high": null, "scale_min": 0, "scale_max": 4, "step": 1},
 "missing_reason": null, "assertion": "positive", "subject_scope": "patient",
 "effective_time": {"kind": "point", "value": "2026-03-25", "precision": "day", "time_basis": "shifted_patient_local"},
 "recorded_time": null,
 "evidence": [{"resource_type": "Observation", "resource_id": "obs-77", "version_id": "1", "locator": "valueInteger",
               "source_kind": "structured", "verification_status": "source_assertion"}],
 "provenance": {"method": "source_projection", "method_version": "…", "model_id": null, "confidence": null,
                "input_fact_refs": []},
 "review_status": "unreviewed", "generalization": {"applied": false, "constraints": []},
 "alternatives": [], "scope": null}
```

### State × assertion (enforced)

| `state` | `value` | `missing_reason` | `assertion` | `evidence` |
|---|---|---|---|---|
| `known` | typed value | null | `positive` / `explicit_negative` / `suspected` / `historical` | ≥ 1 |
| `unknown` | null | `not_documented` / `not_assessed` / `source_incomplete` / `generalized` / `unavailable` | null | may be empty |
| `not_tested` | null | `explicitly_not_tested` | null | ≥ 1 saying the test was **not done** |
| `indeterminate` | null | `ambiguous` / `unsupported_code` / `unsupported_unit` / `insufficient_precision` / `insufficient_inputs` | null | ≥ 1 |
| `conflict` | null | `contradictory_evidence` | null | ≥ 1, plus ≥ 2 existing `alternatives` |

- Boolean `false` needs `assertion: "explicit_negative"` and evidence that explicitly denies.
- `suspected` (differential, "?", "probable") never decides a hard criterion.
- Family history → `subject_scope: "family"`; only `patient` facts count.
- `review_status: "reviewed"` only when a human actually reviewed the fact.

## Fact keys the matcher understands

| `fact_key` | `value.kind` | Notes |
|---|---|---|
| `demographics.age` | `integer` (unit `years`) or `interval` (unit `a`) | Keep privacy bands as intervals; never reconstruct exact age. |
| `demographics.administrative_gender` | `coded`, system `http://hl7.org/fhir/administrative-gender` | Administrative only; never infer pregnancy/WOCBP from it. |
| `disease.primary` | `coded`, system `ICD-10`, dotted (`C18.7`) | One fact per supported primary. Also drives trial search terms. |
| `disease.histology` | `coded`, system `ICD-O-3` (`8140/3`) | From pathology. |
| `disease.stage` | `stage` | Preserved but not interpreted (→ unresolved). Never derive booleans from it. |
| `disease.metastatic`, `disease.locally_advanced`, `disease.recurrent`, `disease.refractory`, `disease.cns_metastases`, `disease.recist_measurable` | `boolean` | `false` only with an explicit all-sites denial. "No liver mets" ≠ not metastatic. |
| `disease.condition`, `safety.condition` | `coded` (SNOMED-CT or `avicenna-condition/1`) | One fact per condition; absence of a code ≠ absence of the condition. |
| `performance.status` | `scored_instrument` | ECOG LOINC `89247-1` (0–4), Karnofsky `89243-0` (0–100, step 10). Never convert. |
| `biomarker.result` | `biomarker` | `marker` (`avicenna-marker/1`: `KRAS_G12C`, `ERBB2`, `ESR1`, `PGR`, `FGFR3`, HGNC…), `result` (`avicenna-result/1`: `positive negative detected not_detected equivocal low`). Do **not** set `Fact.concept`. |
| `lab.result` | `quantity` + `concept` (LOINC) | UCUM `ucum_code` + `normalization_status: "validated"` only from the validated unit table; reference range in `qualifiers` on the **same** fact. |
| `cardiac.qtc`, `cardiac.lvef` | `quantity` | QTc needs `qualifiers.qtc_method`. |
| `safety.pregnant`, `safety.wocbp` | `boolean` | Explicit evidence only. |
| `therapy.event` | `therapy_event` or `scoped_absence` | See below. |
| `logistics.treating_center` | `coded` | Local site code. |

### Therapy history and "no prior X" (the dangerous direction)

- One `therapy_event` per regimen: `agents` (`{"system": "inn", "code": "<lowercase INN>"}`), `classes`
  (only `chemotherapy immunotherapy endocrine targeted adc parp_inhibitor radiation surgery transplant other unknown`),
  `evidence_kind` (`administration`/`review` = really given; `prescription`/`billing`/`narrative` = not proven),
  `intent` only if stated, `line` only if stated.
- A trial exclusion "no prior X" is cleared **only** by:
  1. a `scoped_absence` fact (`assertion: "explicit_negative"`, `value: {"kind": "scoped_absence", "absent": true}`)
     whose `scope` names exactly what was denied, with evidence that explicitly denies it; or
  2. an authorized `coverage.completeness` reconciliation record supplied by a human/approved process.
- **Never create a completeness record yourself.** Silence in the chart is never a negative.

## Coverage

Every required slot is listed in exactly one of `assessed_fact_keys` (you looked) or
`unassessed_fact_keys`: `demographics.age`, `demographics.administrative_gender`, `disease.primary`,
`disease.histology`, `disease.stage`, `disease.metastatic`, `performance.status`, `therapy.event`,
`biomarker.result`, `lab.result`, `logistics.treating_center`. "Assessed" ≠ complete.

## Time

- `effective_time` = when it is clinically true (specimen, measurement, diagnosis); `recorded_time` = when documented.
- Partial dates keep their precision (`"2024-02"`, `precision: "month"`) — no 1st-of-month fill-ins.
- An old fact restated in a new report keeps its old effective time (or null).

## Workflow with the MCP

1. Build the packet (local extractor following the full prompt resource).
2. `validate_patient_packet(packet_path=…)` → fix every structural error; read `adapter_losses`.
3. `screen_patient(packet_path=…)` or `match_trial(trial_id, packet_path=…)`.
4. Unresolved criteria list exactly which facts would move a trial forward — collect those from the
   chart, not by guessing.

## Self-check

- [ ] Every `known` fact has evidence; nothing rests on silence.
- [ ] No invented date, precision, unit, code, line, intent or setting.
- [ ] Booleans `false` only with explicit denial; organ-specific negatives are not global negatives.
- [ ] Disagreements are `conflict` facts with existing alternatives — never silently pick one.
- [ ] Labs carry `concept` + reference range on the same fact; biomarkers carry a coded `marker`.
- [ ] `coverage.completeness` is empty unless an authorized reconciliation was supplied.
- [ ] `anchor` was supplied by the caller or is null.
- [ ] `validate_patient_packet` passes.

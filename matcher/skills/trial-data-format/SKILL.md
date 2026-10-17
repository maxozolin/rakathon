---
name: trial-data-format
description: Defines how clinical-trial eligibility data must look for the Avicenna matcher — the avicenna.criteria-pack/0.1 CriteriaPack JSON (per-arm inclusion/exclusion criteria split into typed atoms, opaque when unsafe). Use when curating/atomizing a trial from CT.gov or CTIS text, reviewing a pack, or calling validate_criteria_pack / save_criteria_pack on the Avicenna MCP.
license: Proprietary (Rakathon 2026 team 16)
compatibility: Avicenna matcher MCP (avicenna-mcp); avicenna.matcher/0.1
metadata:
  schema_version: "avicenna.criteria-pack/0.1"
  normative_source: "TRIAL_DATA_STANDARD.md v1.3; prompts/TRIAL_PACK_BUILDER_PROMPT.md"
---

# Trial data format (CriteriaPack)

A **CriteriaPack** is one trial's eligibility, structured so a deterministic, fail-closed matcher can
evaluate it against a patient packet. Input is **public registry text only** — never put patient data
into a pack or into the conversation used to build it.

Full builder prompt: MCP resource `avicenna://docs/trial-pack-builder`. Schema: `avicenna://schemas/criteria_pack`.
Worked pack: [`example_pack.json`](example_pack.json) (NCT06252649, hand-atomized from public text).

**Golden rule: a wrong atom is worse than an opaque one.** An unresolved criterion goes to a human;
a wrong atom silently excludes an eligible patient or passes an ineligible one. When in doubt, opaque.

## Where packs come from

| Source | How | Quality |
|---|---|---|
| `curated` | atomized by a curator/LLM with this skill, stored via `save_criteria_pack` in `matcher/packs/<trial_id>.json` | evaluable criteria |
| `registry` (automatic) | built by the MCP for every catalog trial: structured age/sex + each bullet as verbatim opaque text | only age/sex are checked; everything else → human review |

Curating a trial upgrades it from `registry` to `curated` for every future screening.

## Curation workflow with the MCP

1. `get_trial(trial_id)` → verbatim `inclusion_criteria` / `exclusion_criteria` plus age/sex fields.
2. `get_criteria_pack(trial_id)` → the current pack (registry skeleton is a good starting point: it
   already has one verbatim criterion per bullet).
3. Atomize bullet by bullet using the decision procedure below.
4. `validate_criteria_pack(pack)` → fix errors and warnings.
5. Optional: `match_trial(trial_id, packet_path=<synthetic packet>)` with the patient-data-format example.
6. `save_criteria_pack(pack)` (use `overwrite: true` to replace an existing curated pack).

## Envelope

```json
{
  "schema_version": "avicenna.criteria-pack/0.1",
  "pack_id": "<trial_id>@<registry last-update>/trial-pack-builder/1.0.0",
  "trial_id": "NCT… | EU CT number (e.g. 2025-524202-15-00)",
  "criteria_completeness": "complete | partial",
  "generated_at": "<RFC 3339>",
  "arms": [{"arm_id": "main", "arm_name": "All participants", "study_type": "interventional"}],
  "criteria": []
}
```

- `complete` only if every bullet is present (opaque counts) and the registry text is the full list.
  CTIS publishes only *principal* criteria → `partial`. `partial` caps the result at `needs_chart_review`.
- One `main` arm unless the text has cohort-specific criteria; then declare every arm and set `arm_scope`.
- No extra fields anywhere — the schema rejects them.

## Criterion

```json
{"criterion_id": "exc:g12ci", "criterion_type": "exclusion", "hardness": "hard", "arm_scope": null,
 "source_text": "Previous treatment with a KRAS p.G12C inhibitor",
 "atoms": [{"atom_id": "n", "predicate_type": "not_exists", "arm_scope": null,
            "source_text": "prior sotorasib/adagrasib", "fact_key": "therapy.event",
            "scope": {"time_extent": "lifetime", "concepts": ["sotorasib", "adagrasib"],
                      "ontology_version_pin": "avicenna-seed/1.0.0"}}],
 "completeness_note": "complete", "logic": {"op": "not"}}
```

- `criterion_type` comes from the section (Inclusion/Exclusion). **Never flip polarity.**
- `hardness`: `hard`, except investigator judgment / informed consent / willingness → `procedural_pre_screen`.
- `source_text`: verbatim; use "…" when you split a sentence. Never paraphrase.
- `logic.op`: `all` (AND), `any` (OR), `not` (exactly one atom). Required with > 1 non-gate atom. Never `custom`.
- `completeness_note`: `complete` | `partial` | `opaque_text` (then `atoms: []`).

## Decision procedure (per bullet)

1. **Opaque** if it is: protocol-defined but unpublished ("adequate organ function"); a screening-visit or
   central-lab finding; number of prior lines; response/progression; CTCAE grade; stage; specimen/assay
   requirements; or anything needing a guess.
2. **Split only when sound**: inclusion "A and B" → two inclusions; exclusion "A or B" → two exclusions.
   Never split inclusion-OR or exclusion-AND (use one criterion with `logic`).
3. **`partial` soundness**: allowed only if the encoded part is *sufficient* for an inclusion or
   *necessary* for an exclusion (it may then only resolve in the non-disqualifying direction).
   "Active, untreated brain metastases" → `disease.cns_metastases eq true`, `partial` ✔.
4. **Encode** with the vocabulary below. Every threshold/unit/window/agent must be in the text.

## Atom vocabulary

| `predicate_type` | Fields | Use for |
|---|---|---|
| `simple_comparison` | `fact_key`, `comparator` (`eq ne lt le gt ge in_set`), `threshold`, opt. `concept`, `relation`, `window_days`, `quantifier` | age, diagnosis, booleans, ECOG, biomarkers, labs |
| `relative_to_reference` | `fact_key: "lab.result"`, `concept`, `comparator`, `threshold` (multiplier), `reference_qualifier` (`reference_high`/`reference_low`) | "≤ 2.5 × ULN" |
| `not_exists` | `fact_key: "therapy.event"`, `scope` {`time_extent` lifetime/bounded(+`bounded_days`), `setting`?, `concepts`, `ontology_version_pin`} | "no prior X" |
| `guarded_case` | `guard_fact_key`, `guard_scope`, `cases[]`, `else` | "AST ≤ 5×ULN if liver mets, else ≤ 2.5×ULN" |
| `applicability_gate` | `gate_fact_key`, `gate_value` | "Women of childbearing potential must…" |
| `criterion_ref` | `ref: {criterion_id, as}` | "unless exclusion 16 applies" |
| `procedural` | — | consent / logistics |

Thresholds: numeric `{"value": 18, "unit": "a"}`; coded `{"system": "ICD-10", "code": "C18.7"}`; `in_set` = list
of coded objects (no hierarchy — list every code); boolean `true/false`.

Relations: `current` (default, no staleness bound — don't use for screening state), `at_screening`,
`ever`/`any_history`, `within_days_before_anchor` (+ `window_days` + `quantifier: latest|exists`, only when the
text states the window).

Fact keys: `demographics.age`, `demographics.administrative_gender`, `disease.primary`, `disease.histology`,
`disease.metastatic`, `disease.locally_advanced`, `disease.recurrent`, `disease.refractory`,
`disease.cns_metastases`, `disease.recist_measurable`, `disease.condition`, `safety.condition`,
`performance.status`, `biomarker.result` (**must** carry `concept`), `lab.result` (**must** carry `concept`),
`cardiac.qtc`, `cardiac.lvef`, `safety.pregnant`, `safety.wocbp`, `therapy.event` (only via `not_exists`).

## Shared terminology binding (must match the patient packet)

| Domain | `system` | Code |
|---|---|---|
| Primary diagnosis | `ICD-10` | dotted `C18.7` |
| Histology | `ICD-O-3` | `8140/3` |
| Conditions | `SNOMED-CT` or `avicenna-condition/1` | concept id |
| Lab analyte (`concept`) | `http://loinc.org` | LOINC |
| Biomarker marker (`concept`) | `avicenna-marker/1` | `KRAS_G12C`, `ERBB2`, `ESR1`, `PGR`, `FGFR3`, HGNC |
| Biomarker result | `avicenna-result/1` | `positive negative detected not_detected equivocal low` |
| Administrative gender | `http://hl7.org/fhir/administrative-gender` | `female` / `male` |
| Therapy agents | code only | lowercase INN |
| Therapy classes | — | `chemotherapy immunotherapy endocrine targeted adc parp_inhibitor radiation surgery transplant` |
| Performance | unit `{ECOG}` / `{Karnofsky}` | never convert between them |

A code outside the binding → keep the criterion opaque; note the needed code in `logic.notes`.

## Worked fragments

| Text | Encoding |
|---|---|
| "ECOG performance status 0–1." | `performance.status le {"value":1,"unit":"{ECOG}"}`, `relation: "at_screening"` |
| "Adequate organ function." | hard, `opaque_text` |
| "Any condition that, in the investigator's opinion…" | `procedural_pre_screen`, `opaque_text` |
| "Prior KRAS G12C inhibitor (e.g., sotorasib, adagrasib)" | **opaque** ("e.g." = open list) |
| "Prior sotorasib or adagrasib" | `logic not` + `not_exists concepts ["sotorasib","adagrasib"]`, `complete` |
| "> 2 prior lines of systemic therapy" | hard, `opaque_text` (line counting unsupported) |

## Self-check

- [ ] Every bullet maps to ≥ 1 criterion, or `criteria_completeness` is `partial`.
- [ ] No value absent from the text or the binding; nothing "typical" imported.
- [ ] Every `partial` passes the sufficient/necessary test; splits are AND-inclusion / OR-exclusion only.
- [ ] `biomarker.result`/`lab.result` atoms have `concept`; labs use UCUM.
- [ ] Screening-state atoms use `at_screening` or a stated window.
- [ ] Every `not_exists` has `time_extent` + `ontology_version_pin: "avicenna-seed/1.0.0"`.
- [ ] Only judgment/consent/willingness are `procedural_pre_screen`.
- [ ] `validate_criteria_pack` returns no errors and no warnings you cannot explain.

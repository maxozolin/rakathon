# Response to patient matching data needs

## Audience and privacy boundary

This document responds to `PATIENT_MATCHING_DATA_NEEDS.md` and is intended for a model **without approved access to patient data**. It contains source-schema capabilities, engineering limitations, and proposed contracts only. It contains no patient identifiers, excerpts, individual values, patient-linked results, exact patient/resource counts, or clinical cohort distributions.

Read this response and `reports/GENERAL_DATA_GUIDE.md`, not the restricted report, source patient files, ingestion checkpoints, or patient-derived features. Develop with wholly synthetic fixtures. Do not ask another model to supply patient examples or infer withheld details from this document.

The required architecture is unchanged: public trial criteria may be structured in the cloud and pushed into the hospital; patient extraction, matching, evidence, explanations, ranking, and clinician UI remain inside the approved hospital/event boundary. **No cloud fetching, including narrow fields or patient packets.** EU model hosting alone is not permission to export patient information.

## Verdict

**Partly: we have source material for several requested facts, but not an already-produced, validated minimum patient packet.**

- **Structured foundation exists:** demographics with possible generalization, coded diagnoses, laboratory results, prescription/billing-derived treatment events, procedures, and imaging/report metadata.
- **Narrative source exists:** clinical reports and imaging findings are available as text-bearing FHIR resources. That does not establish that any specific histology, biomarker, ECOG, stage, or treatment-line fact is present or reliably extractable for a given patient.
- **Matching-ready extraction is still needed:** local terminology/unit normalization, uncertainty-aware demographics, temporal evidence, narrative extraction/review, and a conservative criterion evaluator.
- **Some facts need fresh confirmation:** willingness, consent, tissue availability, current pregnancy/safety status, and actual site availability cannot be assumed from the export.

At the time this response was prepared, the HTTPS FHIR repository had been verified and ingestion had started, but the protected checkpoint did **not** indicate complete ingestion. This is not a claim that all source records are already stored or that the matcher exists. Uploading FHIR does not automatically create normalized matching facts.

The practical answer to “do we have A+B+C+D already?” is: **A partially structured; B largely an extraction/review task; C has structured evidence needing normalization and freshness checks; D largely unknown or manual, with some protocol-hard requirements.** No numerical completeness claims are made here.

## Availability by requested fact

Legend:
- **Structured source:** a relevant exported field/resource exists; not a guarantee of patient-level coverage or clinical validity.
- **Extraction candidate:** a relevant narrative/evidence source exists; extraction coverage is unverified.
- **Confirmation needed:** not reliably supported as a current, decisive fact by the export alone.

| Requested fact | What we already have | What must still happen hospital-side |
|---|---|---|
| Age / birth date | Patient demographics and custom exact-age/age-band extensions; birth date can have reduced precision | Preserve exact vs interval vs unknown. Never fabricate month/day, narrow a deliberately generalized age using narrative, or calculate present age from a partial birth date |
| Sex / administrative gender | Patient.gender as an administrative field | Preserve semantics and unknown values. Administrative gender does not establish sex assigned at birth, reproductive anatomy, WOCBP status, pregnancy, or a protocol-specific sex definition |
| Primary diagnosis | ICD-10 Condition evidence, possibly generalized/suppressed | Normalize codes and distinguish primary tumor from metastatic/comorbid diagnoses. A code or first-listed Condition does not establish primary site, histology, active disease, or disease trajectory |
| Histology / morphology / histo-cytological confirmation | Clinical DocumentReference text is an extraction candidate | Extract only explicit local evidence, retain specimen/method/date/context if stated, resolve conflicts, and permit missing. No validated histology packet has been produced |
| Diagnosis / recurrence dates | Event timestamps and narratives can provide evidence | Keep date precision and shifted-time basis; distinguish diagnosis, encounter, recurrence, progression, and recording dates. Do not use first recorded code as diagnosis onset |
| Stage / TNM / extent | Diagnosis and narrative/imaging sources can supply candidates | Extract explicit stage system, version, components, disease context, and effective time. Do not infer a complete TNM stage from metastatic coding alone |
| Metastatic / recurrent / refractory / locally advanced state | Coded and narrative evidence candidates | Distinguish historical vs current, suspected vs confirmed, and progression vs recurrence. Missing or generalized diagnosis codes cannot establish absence |
| Measurable disease / RECIST | Imaging findings as text and imaging metadata, not DICOM images | A scan or lesion mention does not establish RECIST measurability or response. Require explicit criteria-compatible evidence or clinician assessment; otherwise unknown |
| CNS / brain metastases | Diagnosis/narrative/imaging evidence candidates | Distinguish absent, present, treated, stable, symptomatic, steroid-dependent, and unknown, with dates and criterion-specific qualifiers |
| ER/PR/HER2, mutations/fusions, PD-L1, MSI/MMR, TMB | Report text is a possible extraction source; generic lab presence is not proof of molecular coverage | Build diagnosis-relevant local extractors and preserve assay, specimen, numeric/categorical result, interpretation and timing. No validated structured biomarker collection has been established |
| Tissue / archival FFPE availability | Reports may document historic specimens; some specimen descriptions are display-only | Historic pathology/specimen mention does not prove remaining tissue availability or biopsy willingness. Treat as confirmation needed |
| Prior agents / classes | MedicationRequest, MedicationAdministration and Procedure; local SÚKL/ATC coding where supplied; narrative candidates | Map codes to generic agents/classes with reviewed vocabularies. Distinguish prescription, billing, actual administration and planned therapy; preserve evidence limitations |
| Therapy line / intent / dates / response / progression | Individual events and reports, not a curated treatment protocol/line-of-therapy summary | Reconstruct locally with evidence, uncertainty and review. Never equate drug count with treatment line or billing status with completed regimen |
| ECOG / Karnofsky | Clinical reports are extraction candidates | Extract explicitly documented scale/value/date. Preserve scale; do not silently convert Karnofsky to ECOG or infer ECOG from narrative activity descriptions |
| CBC / basic chemistry | Observation and laboratory DiagnosticReport with local codes, numeric/text results, reference ranges and timestamps | Validate test identity and UCUM units, handle qualifiers/non-numeric results, select eligible observations by the criterion window, and mark missing/stale/incomparable explicitly |
| ANC / platelets / Hb / renal / hepatic checks | Generic laboratory evidence exists; individual requested analyte coverage remains to be checked locally | Distinguish absolute ANC from neutrophil percentage; do not assume eGFR method or units. Derived ANC/eGFR requires validated formulas and complete, approved inputs |
| QTc / LVEF / pregnancy test | Generic reports/labs are possible sources, not established coverage | Look for explicit method, units, date and current relevance. QTc correction method matters; pregnancy/WOCBP cannot be inferred from gender or age alone |
| Comorbidity / infection / cardiac flags | Condition and clinical-report evidence, potentially incomplete/generalized | Preserve active/history/suspected/absent/unknown and severity qualifiers. Exported active/confirmed status is a source assertion, not chart adjudication; no code does not mean no condition |
| Washouts / transfusion / G-CSF timing | Dated therapy/procedure/lab/report evidence candidates | Evaluate only with confirmed relevant event dates and a valid patient-local evaluation anchor. Shifted dates cannot establish real-world screening freshness |
| Treating center / geography | Export provenance and document/care-site hints; trial side has study locations | Do not label every patient Motol/Homolka based on the catalog or provenance alone. Add a reviewed local center mapping. Site distance/willingness require confirmation; home address is unnecessary |
| Consent / contraception compliance / biopsy willingness / investigator judgment | No reliable current fact can be assumed | Explicit unknown/manual-review fields, not fabricated consent or inferred willingness. Actual enrollment requires the applicable consent and protocol review |

### Limits that affect the entire packet

1. **Pseudonymization is not anonymization.** Patient facts and derived scores remain protected.
2. **Generalization is deliberate.** Do not reconstruct suppressed age/diagnosis precision from other fields or text.
3. **Dates are shifted per patient.** Relative within-patient intervals may remain useful; absolute “within 14 days of today” claims do not follow. Use an explicitly documented shifted patient-local demo anchor and label demo recency, not real screening eligibility.
4. **Units and terminology need validation.** Display units and local codes are not automatically standardized. Unsupported mappings yield missing/unsupported, not a guess.
5. **Clinical summaries are not supplied merely by event records.** Prescriptions/billing do not supply current regimens, adherence, therapy lines, response or contraindication absence.
6. **No DICOM-based adjudication.** Imaging metadata/availability hints and report narratives cannot substitute for image review or RECIST assessment.

## Matching policy corrections

The requested note is a useful extraction backlog, but its tiers should describe availability/work effort rather than determine protocol hardness.

### Do not automatically soften Tier D clinical requirements

Washout, measurable disease, tissue requirements and pregnancy restrictions may be **hard eligibility conditions**. If evidence is absent, they remain unresolved hard conditions, not ignored checks. Consent/biopsy willingness can be deferred at pre-screening, but their unresolved state must be visible and must never imply enrollment eligibility. Investigator judgment remains manual.

### Separate candidate discovery from eligibility

- Geographic fit is a preference/ranking signal unless a specific protocol/access constraint makes it a gate. Unknown willingness is not evidence of refusal.
- Diagnosis embedding similarity can retrieve candidates. It must not be the sole hard eligibility gate; use reviewed code/concept mapping and histology/context evidence. Patient embeddings stay hospital-side too.
- Recruiting status is a trial-side check: active-not-recruiting is not ordinarily available for new enrollment. Distinguish registry-wide status from availability of the actual site/cohort/arm, and preserve retrieval date.
- A CTIS/CT.gov crosswalk does not prove identical current arm-specific criteria. Preserve source/version/arm and conflicts; do not merge contradictory criteria or assume a blanket source preference resolves them.

### Use explicit polarity and unresolved states

Define each criterion atom as an unambiguous predicate and record `kind = inclusion | exclusion`. With the source note's literal-predicate convention:

```text
inclusion predicate true  → inclusion satisfied
inclusion predicate false → hard inclusion failure, if criterion is hard
exclusion predicate true  → hard exclusion triggered, if criterion is hard
unknown / conflict / stale / unsupported → unresolved, never automatically satisfied
```

Keep AND/OR/NOT, thresholds, exception clauses, timing and arm dependencies; splitting a paragraph into independent checks can change its meaning. Explain the polarity in the UI so an exclusion marked “met” is not mistaken for a positive match.

Prefer a local result with separate fields:
- `candidate_relevance`: diagnosis/site fit for shortlisting;
- `eligibility_state`: potential / needs_chart_review / ineligible / manual_review;
- `evidence_coverage`: evaluable vs unresolved applicable criteria;
- `blocking_criteria`: supported hard failures and unresolved hard requirements.

Rank relevance separately from eligibility and evidence completeness. More criteria bullets must not inflate the score; avoid a raw “number of met bullets” advantage for verbose trials. Do not call a shortlisted patient eligible or assign a confident pass when required biomarkers, ECOG, safety checks or other hard requirements are unresolved.

## Hospital-side patient fact contract

The non-patient-data model may implement this schema and synthetic tests. **Real instances of the schema must never be returned to that model or the cloud.**

```text
PatientFact (local only):
  fact_key                 # diagnosis, age, ecog, lab.anc, prior_therapy, ...
  value                    # typed scalar / interval / structured event, when known
  state                    # known | unknown | not_tested | indeterminate | conflict
  missing_reason           # absent | generalized | stale | unsupported_unit | ...
  code_system / code       # preserve original plus validated normalization
  unit / canonical_unit    # preserve original; conversion only when validated
  effective_time           # time/interval + precision, when stated
  recorded_time            # separate from effective clinical time
  time_basis               # shifted_patient_local | unshifted_verified | unknown
  source_kind              # code | lab | prescription | billing | narrative | review
  evidence_reference       # local resource/version/attachment pointer
  assertion                # positive | explicit_negative | suspected | historical
  extraction_method_version
  confidence               # extraction confidence, not probability of eligibility
  reviewed                 # clinician/operator review indicator
  generalization           # preserve intentional precision limits

TherapyEvent (local only):
  agents[] / agent_classes[]
  evidence_kind            # prescription | billing | administration | narrative
  line / intent / setting  # optional and evidence-backed; otherwise unknown
  start / end / progression_time / best_response  # only supported fields
  fact_metadata            # same provenance/time/uncertainty rules as PatientFact
```

`not_tested` requires explicit evidence that a test was not performed; missing biomarker records are `unknown`, not `not_tested` or negative. An exact age and an age interval must be different data types. Do not invent precise `as_of` dates for facts documented only approximately.

Avoid a plaintext evidence excerpt in shared application telemetry. Local evidence pointers are preferable; even identifiers/pointers must stay inside the boundary. Criterion-level explanations should be generated locally from evaluated rules and local evidence, not sent to a cloud LLM for wording.

## Delivery plan and acceptance checks

### What can be built without patient-data access

1. Versioned criteria atoms with explicit polarity, Boolean grouping, arm/source scope, units and timing semantics.
2. PatientFact/TherapyEvent schemas and synthetic fixtures for all known/unknown/generalized/conflicting states.
3. Deterministic matching logic, relevance/coverage separation and a hospital-deployed clinician UI.
4. Local extractor interfaces and vocabulary contracts, without obtaining real packets or charts.

### Work for the authorized hospital-side pipeline

1. Finish ingestion and reconcile internally; do not declare full ingestion based on a canary or partial checkpoint.
2. Normalize demographics/diagnosis/labs/treatment events while retaining precision and evidence limitations.
3. Validate local method/unit/agent-class mappings and time-anchor policy.
4. Implement and assess explicit narrative extraction for histology, stage, ECOG, biomarkers and therapy history. Measure field coverage and extraction error internally; this report does not claim that coverage is known.
5. Add clinician review for unresolved/conflicting high-impact facts and current safety/site/consent questions.
6. Store fact packets/results locally, with access controls and event-end retention/deletion.

### Revised minimum viable packet

Use the eight requested areas as **schema slots**, not mandatory populated facts:
age/administrative gender; primary disease/histology; stage/state; ECOG; therapy history; diagnosis-relevant biomarkers; eligible labs; reviewed treating-center information.

Every slot may be unknown. The demo should visibly show missing evidence and “needs chart review,” rather than filling gaps to make a complete-looking packet. A diagnosis-level shortlist is possible before full extraction, but it is not a demonstrated A+B+C eligibility assessment.

### Synthetic acceptance tests

- Age interval fully satisfies / fully fails / straddles a criterion boundary.
- Unknown administrative gender and protocol-specific reproductive criteria remain unresolved.
- Positive, explicit-negative, historical and conflicting disease evidence remain distinct.
- Lab threshold handles unit mismatch, inequalities, method ambiguity and stale/incomparable shifted dates.
- Prescription alone does not prove administered therapy; unknown therapy line stays unknown.
- Biomarker unknown vs explicit not-tested vs negative is distinguishable.
- Hard washout/RECIST/pregnancy requirement is not passed because it sits in Tier D.
- A confirmed hard exclusion overrides a high relevance score; unresolved hard requirements prevent an eligible label.
- Boolean groups and protocol exceptions preserve semantics.
- Cloud receives no patient queries, facts, embeddings, evidence, scores or explanations.

## Sources and limits

- `PATIENT_MATCHING_DATA_NEEDS.md`: requested trial-side needs; catalog prevalence and crosswalk assertions were not independently re-audited for this response.
- `reports/GENERAL_DATA_GUIDE.md`: privacy-safe data and architecture contract.
- Authorized prior source-schema inspection informed the capability/limitation summary. Restricted record-level information and exact inventory figures were deliberately omitted. No new clinical narrative audit or patient feature extraction was performed for this response.
- Infrastructure/ingestion status is an operational snapshot, not evidence of clinical completeness, correctness, GDPR certification, or durable storage. The authorized HTTPS destination remains publicly addressable and ephemeral; scoped runtime identities and restart reliability are separate outstanding tasks.

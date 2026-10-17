# Avicenna patient matching packet standard

## Status and scope

**Version:** `avicenna.patient-packet/1.1.0` · **Status:** proposed implementation contract · **Date:** 17 October 2026.

This standard defines the JSON packet supplied to the **hospital-side trial matcher**. It is an application-level projection of FHIR/evidence, not a replacement for FHIR, an HL7 implementation guide, or a clinical eligibility certification. It supports structured source fields, deterministic derivations, local-model extraction and clinician review without making missing data look complete.

The schema and wholly synthetic example are safe for models without patient-data access. Real packet instances are protected patient data and must not be shared with those models.

Normative terms: **MUST** is required, **SHOULD** is recommended with documented exceptions, **MAY** is optional. Unknown enum values MUST fail validation; new semantics require a schema version change. Consumers MUST support the declared version rather than silently interpreting an unfamiliar one. An executable JSON Schema is a future implementation deliverable; this document does not claim one is deployed.

## Privacy boundary

- Source records, decoded text, facts, embeddings, evidence pointers, packets and patient-linked results MUST remain inside the approved hospital/event boundary for a zero-egress matching design.
- Public trial criteria MAY be structured externally and pushed inward. Patient processing MUST NOT silently fall back to an external model.
- A local open-weight model is hospital-side only when its inference service and telemetry are actually inside that boundary. If patient text is sent to an approved EU processor, record that architecture accurately; do not claim zero patient-data egress for that extraction.
- Packets MUST NOT contain names, addresses, contact details, national identifiers, passwords or source narrative excerpts. A pseudonymous `patient_ref` and evidence references are still protected information.
- Actual packets MUST NOT appear in Git, shared model prompts, public logs, error traces or analytics. Access, retention/deletion and backups MUST follow the event/hospital policy.

## Packet envelope

Transport/storage format: UTF-8 JSON object. JSON numbers MUST be finite; dates MUST be strings, not locale-formatted numbers. Arrays MUST NOT be interpreted as ordered clinical priority unless explicitly specified.

| Field | Type | Requirement / meaning |
|---|---|---|
| `schema_version` | string | Required; exactly `avicenna.patient-packet/1.1.0` |
| `packet_id` | string | Required; opaque local identifier for this immutable packet revision |
| `patient_ref` | string | Required; opaque local pseudonymous reference, never a direct identifier |
| `generated_at` | RFC 3339 timestamp | Required; actual packet-generation time, not shifted clinical time |
| `environment` | enum | Required: `synthetic_demo`, `approved_event`, `hospital` |
| `source_snapshot` | object | Required; local `snapshot_id`, `ingestion_state`, `extractor_version`, `terminology_version` |
| `evaluation_context` | object | Required; temporal anchor and permitted evaluation mode, below |
| `facts` | array of Fact | Required; may contain only unknown facts; all IDs unique |
| `coverage` | object | Required; `assessed_fact_keys`, `unassessed_fact_keys` (string arrays), and `completeness` (array of scoped completeness assertions, below) |
| `warnings` | string array | Required; controlled codes, no patient narrative |

`source_snapshot.ingestion_state`: `complete`, `partial`, `unknown`. A partial snapshot MUST produce a visible warning and MUST NOT turn absent records into negative facts. Snapshot/extractor/terminology identifiers are versioned local provenance, not external download URLs.

`evaluation_context` fields:
- `mode`: `prescreen_real_time`, `shifted_demo`, `historical_review`;
- `anchor`: TimePoint, or `null` when no valid anchor exists;
- `absolute_screening_recency_allowed`: boolean;
- `policy_version`: versioned local evaluation policy.

An absent anchor MUST NOT default to `generated_at` or today's date. The actual export/generation time does not establish the patient's clinical evaluation time.

## Common fact format

Every clinical assertion is a **Fact**. Extractors MUST preserve separate observations/episodes instead of overwriting conflicting or historical evidence with a single “latest truth.” The matcher resolves evidence using a versioned policy.

| Field | Type | Requirement / meaning |
|---|---|---|
| `fact_id` | string | Required; unique within packet |
| `fact_key` | string | Required; vocabulary key below |
| `state` | enum | Required: `known`, `unknown`, `not_tested`, `indeterminate`, `conflict` |
| `value` | typed object or null | Required; supplied only for `known`; null for other states |
| `missing_reason` | enum or null | Required; see state rules below |
| `assertion` | enum or null | Required: `positive`, `explicit_negative`, `suspected`, `historical`, or null when there is no assertion to characterize |
| `subject_scope` | enum | Required: `patient`, `family`, `other`, `uncertain` |
| `effective_time` | TimePoint / TimeInterval / null | Required; when the clinical assertion applies |
| `recorded_time` | TimePoint / null | Required; when evidence was documented |
| `evidence` | array of Evidence | Required; empty only for `unknown` |
| `provenance` | object | Required; derivation/extraction method and version |
| `review_status` | enum | Required: `unreviewed`, `reviewed`, `rejected` |
| `generalization` | object | Required; `applied` boolean and `constraints` string array |
| `alternatives` | string array | Required; conflicting candidate fact IDs; otherwise empty |
| `scope` | Scope or null | Required for scoped negative/history assertions; otherwise null. Defined below |

### State rules

- `known`: a typed value and evidence MUST be present; `missing_reason = null`. “Known” means supported as an assertion, not clinically confirmed/current or automatically eligible.
- `unknown`: `value = null`; reason MUST be `not_documented`, `not_assessed`, `source_incomplete`, `generalized`, or `unavailable`.
- `not_tested`: `value = null`; reason `explicitly_not_tested`; evidence MUST explicitly support non-performance. No record is not evidence of not-tested.
- `indeterminate`: `value = null`; reason `ambiguous`, `unsupported_code`, `unsupported_unit`, `insufficient_precision`, or `insufficient_inputs`; evidence MUST be retained.
- `conflict`: `value = null`; reason `contradictory_evidence`; at least two alternative fact IDs and evidence MUST be supplied. Alternative facts MUST exist and MUST NOT themselves point back to create a conflict cycle. A `conflict` fact **supersedes its own alternative arms**: those alternatives MUST NOT independently establish a hard pass/fail until a documented review rule resolves them (matcher `MATCHER_DESIGN.md` §4.7).

### State × assertion consistency

`assertion` MUST be consistent with `state`; validators MUST enforce:

| `state` | permitted `assertion` |
|---|---|
| `known` | `positive`, `explicit_negative`, `suspected`, `historical` |
| `unknown` | null only |
| `not_tested` | null only; explicit non-performance is encoded by state, reason and evidence |
| `indeterminate` | null only |
| `conflict` | null only; assertions live on the alternative facts |

A `suspected` or `explicit_negative` assertion requires `state = known` with supporting evidence; it MUST NOT be attached to an absent value.

Null assertion never means criterion non-applicability. Only the matcher's explicit applicability logic may emit `evaluation_state = not_applicable`. `not_tested` does not mean a negative test result or absence of disease/exposure. For Boolean values, false MUST use `explicit_negative`; true MUST NOT use `explicit_negative`. A negative coded assay result remains a known measured result; its interpretation is not an inferred absent record.

The legacy `historical` assertion does not encode polarity: historical Boolean negatives MUST use `explicit_negative` plus effective time and scope. Until polarity/certainty/temporality have separate fields, combinations not representable unambiguously MUST remain indeterminate, not be guessed.

`assertion = historical` MUST NOT substitute for time: effective time/unknown time is still required. Facts about relatives MUST use `subject_scope = family` and MUST NOT satisfy a patient biomarker/disease predicate. Rejected, suspected and uncertain-subject evidence MUST NOT establish a definitive hard pass/failure without a documented review rule.

### Typed values

All value objects use a `kind` discriminator:

| `kind` | Fields |
|---|---|
| `boolean` | `value`: true/false; false requires explicit negative evidence, not absence |
| `integer` | `value`: integer; `unit` optional for dimensioned values |
| `interval` | `lower`, `upper`: numbers; `lower_inclusive`, `upper_inclusive`: booleans; `unit`: string |
| `coded` | `system`, `code`, `display`; optional `normalized` object with the same fields |
| `quantity` | `value`: number; `comparator`: `eq`, `lt`, `le`, `gt`, `ge`; `unit_original`: string; `ucum_code`: string or null; `normalization_status`: `validated`, `unmapped`, `unsupported` |
| `stage` | `system`, `edition`: string or null; `stage_group`, `t`, `n`, `m`: string or null; `disease_fact_ref`: fact ID |
| `biomarker` | `marker`: coded object; `result`: coded or quantity value; `assay`, `specimen_ref`: string or null; `disease_fact_ref`: fact ID or null |
| `therapy_event` | Fields defined below |
| `scoped_absence` | `absent`: true; represents explicit, evidence-backed absence of the exposure/condition defined by Fact.scope, not silence in an export |
| `scored_instrument` | Exact numeric/ordinal shape below; supersedes `performance_status`; see `TRIAL_DATA_STANDARD.md` §6.5.2 |

A coded `display` is a label, not an authoritative synonym mapping. `normalized` MUST be supplied only after validated mapping with mapping provenance. A quantity with `unmapped`/`unsupported` normalization remains usable as source evidence but MUST NOT satisfy a threshold requiring an unverified unit conversion.

### Scored instrument shape

Required fields: `kind = scored_instrument`, `instrument` (coded object), `registry_version` (string), `representation` (`numeric` or `ordinal`), and `no_interconversion = true`.

- Numeric representation requires finite numeric `value`, nullable numeric `value_high`, and numeric `scale_min`, `scale_max`, `step`. Ordinal fields MUST be absent. Null `value_high` means an exact score; otherwise `value <= value_high`. Both bounds MUST lie within the pinned instrument scale and on its defined step grid. Step and scale MUST match the registry, not be chosen by the extractor.
- Ordinal representation requires `ordinal_code` and nullable `ordinal_code_high`, with codes and ordering defined by the pinned instrument registry. Numeric fields MUST be absent. Null high means one category; otherwise registry ordering defines the inclusive category interval. Never compare category labels lexically or infer numeric conversion.
- Unknown/unregistered instrument semantics produce indeterminate/unsupported, not a user-defined scale. ECOG and Karnofsky retain their own registered bounds/steps and are never interconverted.

`therapy_event` fields:
- `agents`: array of `{system, code, display}`; MAY be empty if only a class is explicitly documented;
- `classes`: array of controlled codes: `chemotherapy`, `immunotherapy`, `endocrine`, `targeted`, `adc`, `parp_inhibitor`, `radiation`, `surgery`, `transplant`, `other`, `unknown`;
- `evidence_kind`: `prescription`, `billing`, `administration`, `narrative`, `review`;
- `line`: positive integer or null; `line_context`: string or null, required when line is populated;
- `intent`: `neoadjuvant`, `adjuvant`, `advanced`, `palliative`, `other`, `unknown`;
- `start`, `end`, `progression_time`: TimePoint or null;
- `best_response`: coded value or null;
- `disease_fact_ref`: fact ID or null.

Agents/class alone MUST NOT imply actual administration, completed regimen, therapy line, intent, progression or washout date. Unknown optional properties stay null/unknown; they MUST NOT be fabricated to fill the object.

### Evidence and provenance

Evidence requires `resource_type`, `resource_id`, `version_id` (string or null), `locator` (local element/attachment/span locator), `source_kind`, and `verification_status` (`source_assertion`, `extracted_candidate`, `reviewed`). Locator MUST resolve locally; it MUST NOT trigger remote fetching. If a span uses normalized text offsets, record normalization version and offset unit explicitly.

`source_kind`: `structured`, `lab`, `prescription`, `billing`, `administration`, `narrative`, `manual_review`.

Provenance requires `method` (`source_projection`, `deterministic_derivation`, `local_llm`, `approved_eu_processor`, `manual_review`), `method_version`, `model_id` (string or null), `confidence` (number 0–1 or null), and `input_fact_refs` (array). Derived facts MUST reference their input facts and a versioned formula/mapping through `method_version`. Extraction confidence is not the probability of a correct diagnosis or eligibility.

Use `approved_eu_processor` honestly when patient text was sent to an external approved endpoint. Such a packet is incompatible with a claim of zero patient-data egress during its extraction.

## Clinical fact vocabulary

Repeated keys are allowed for different observations, disease episodes or evidence sources. Required coverage slots MUST appear in `assessed_fact_keys` or `unassessed_fact_keys`; a key MUST NOT appear in both. At least one Fact MUST exist for each assessed key, including an explicit unknown if assessment found no evidence. For an unassessed key, no Fact is required. Omitting a Fact MUST NEVER mean negative.

**`assessed` means *looked at*, not *complete*; completeness is scoped, not a bare key.** `completeness` defaults to **empty**. Extraction can capture *supported exposures* but by itself does NOT certify comprehensive clinical history; **complete extraction and complete ingestion MUST NOT be equated with complete clinical history**, and the whole-snapshot `ingestion_state` MUST NOT be used as a completeness proxy. A bare "`therapy.event` is complete" is too broad and is not permitted: each completeness assertion MUST state its scope.

### Scope and completeness objects

**Scope** is shared by `coverage.completeness[]` and explicit negative Facts. Required fields:
- `concepts`: `{system, registry_version, classes, agents}`, with nonempty system/version strings and arrays of registered code strings. At least one array MUST be nonempty; unrestricted “any” is not allowed. Class→agent membership and class subsumption MUST be validated under that registry version. Unknown membership remains unresolved.
- `disease_setting`: `neoadjuvant`, `adjuvant`, `advanced`, `palliative`, `all_settings`, or `unknown`;
- `disease_fact_ref`: a local disease Fact ID or null;
- `disease_scope`: `referenced_disease` or `all_diseases`. Referenced scope requires a non-null resolvable disease reference; all-diseases scope requires explicit review support, not an omitted disease reference;
- `time`: `{extent: "bounded", interval: TimeInterval}` or `{extent: "lifetime", time_basis: TimePoint.time_basis, through: TimePoint}`. Bounded closure requires both interval bounds and compatible time basis. Lifetime means documented history through the supplied point; it does not assert future absence. A lifetime query must have a compatible cutoff no later than `through`. Null/incompatible cutoff yields unresolved.

Scope matching MUST consider concepts, disease, setting, time basis, extent and cutoff together. `unknown` setting cannot clear a setting-specific absence query. Bounded scope never clears lifetime history.

**Completeness assertion** requires `assertion_id` (unique local ID), `fact_key`, `scope`, `method = reviewed_reconciliation`, `authorization` (below), nonempty `evidence` (Evidence array), nonempty `reconciled_sources` (local source references), `source_snapshot_ref`, and `reconciliation_policy_version` (string). Snapshot reference MUST match the packet snapshot; mismatch is a validation error. A known qualifying or ambiguously scoped exposure prevents absence clearance even when completeness is asserted.

`authorization` is one of:
- `{kind: "human", reviewer_id, reviewed_at}`: authorized local reviewer identity and actual RFC 3339 review timestamp;
- `{kind: "approved_process", process_id, process_version, approval_ref, completed_at}`: approved validated process identity/version, local approval record and actual completion timestamp.

Authorization references MUST be checked against a pinned local authorization policy; a populated string alone proves nothing. The extractor cannot approve itself. Review/completion timestamps are operational metadata, not shifted clinical dates. The packet's terminology version must resolve all referenced concept-registry versions; matching never fetches them remotely.

```jsonc
// Synthetic shape example: coverage.completeness[]; not a real review assertion.
{
  "assertion_id": "synthetic-reconciliation-001",
  "fact_key": "therapy.event",
  "scope": {
    "concepts": { "system": "urn:synthetic:therapy", "registry_version": "1", "classes": ["parp_inhibitor"], "agents": [] },
    "disease_setting": "advanced",
    "disease_scope": "referenced_disease",
    "disease_fact_ref": "synthetic-disease-1",
    "time": {
      "extent": "bounded",
      "interval": {
        "kind": "interval",
        "start": { "kind": "point", "value": "2026-01-01", "precision": "day", "time_basis": "shifted_patient_local" },
        "end": { "kind": "point", "value": "2026-04-01", "precision": "day", "time_basis": "shifted_patient_local" }
      }
    }
  },
  "method": "reviewed_reconciliation",
  "authorization": { "kind": "human", "reviewer_id": "synthetic-reviewer", "reviewed_at": "2026-10-17T09:00:00Z" },
  "evidence": [{ "resource_type": "DocumentReference", "resource_id": "synthetic-review-note", "version_id": "1", "locator": "content[0]", "source_kind": "manual_review", "verification_status": "reviewed" }],
  "reconciled_sources": ["synthetic-local-treatment-record"],
  "source_snapshot_ref": "synthetic-fixtures-v1",
  "reconciliation_policy_version": "synthetic-reconciliation-policy-v1"
}
```

A completeness assertion MUST be grounded in reviewed reconciliation with the authorization and evidence above; its `fact_key` MUST be assessed. Explicit negative evidence is a separate Fact, not permission to label an entire domain complete.

**Explicit therapy absence:** use `fact_key = therapy.event`, `state = known`, `assertion = explicit_negative`, `value = {"kind": "scoped_absence", "absent": true}`, and a non-null Scope. Supporting evidence MUST explicitly deny the scoped exposure, rather than merely omit it. Preserve review/provenance and unresolved contradictory exposure evidence. The literal `absent: true` describes absence; it does not mean the corresponding exposure predicate is true. The matcher applies the queried predicate's polarity.

A `not_exists`/negative predicate resolves to a definite negative **only** when an assertion's scope **subsumes the criterion's scope** (concepts ⊇, setting compatible/covering, and time covering — a `bounded` window never satisfies a `lifetime` criterion), or when a criterion-scoped `explicit_negative` Fact exists; otherwise `unknown`. Concept subsumption MUST use **validated, versioned concept membership**; an unknown or unvalidated mapping leaves the predicate `unknown`, never assumed (non-)member (matcher `MATCHER_DESIGN.md` §5.4).

| Key / family | Value kind | Interpretation |
|---|---|---|
| `demographics.age` | integer or interval | Years as documented; preserve deliberately generalized interval |
| `demographics.administrative_gender` | coded | FHIR administrative gender; not reproductive status/sex-at-birth |
| `disease.primary` | coded | Explicitly supported primary disease, not simply first-listed diagnosis |
| `disease.condition` | coded | Other/unspecified disease assertion, including comorbidity |
| `disease.histology` | coded | Explicit morphology/histology, with local code allowed if no validated standard mapping |
| `disease.stage` | stage | Preserve stage system/edition and disease episode |
| `disease.metastatic`, `disease.recurrent`, `disease.refractory`, `disease.locally_advanced`, `disease.cns_metastases` | boolean | Explicit positive/negative assertion with temporal context |
| `disease.recist_measurable` | boolean | Requires explicit criteria-compatible evidence or review, not scan presence |
| `performance.status` | scored_instrument | ECOG 0–4 or Karnofsky 0–100 in increments of 10; preserve interval and instrument; no silent interconversion |
| `biomarker.result` | biomarker | Repeated per assay/specimen/marker; unknown marker results represented by an unknown Fact with local marker context in evidence |
| `therapy.event` | therapy_event or scoped_absence | Repeated; event evidence/context or an explicit scoped negative, never inferred silence |
| `lab.result` | quantity or coded | Analyte identity MUST be attached as `concept`, below |
| `cardiac.qtc` | quantity | Preserve correction method as `qualifiers.qtc_method` |
| `cardiac.lvef` | quantity | Percent and measurement method/context |
| `safety.condition` | coded | Explicit condition evidence; “no code” cannot establish absence |
| `safety.pregnancy_test` | quantity or coded | Requires pregnancy-test context; generic hCG need not be pregnancy screening |
| `safety.pregnant`, `safety.wocbp` | boolean | Explicit evidence/review; never infer from gender/age alone |
| `logistics.treating_center` | coded | Reviewed care-center mapping, not trial-catalog provenance |
| `logistics.travel_willingness`, `logistics.biopsy_willingness`, `logistics.tissue_available`, `logistics.consent_obtained` | boolean | Current explicit evidence or confirmation; null/unknown is not refusal |

Fact MAY additionally contain `concept` (coded object) for analytes or an unknown specific biomarker; `qualifiers` (object) for criterion-relevant context. Recognized qualifier fields: `disease_fact_ref`, `specimen_ref`, `assay`, `qtc_method`, `reference_low`, `reference_high`, `reference_ucum_code`, `interpretation`, `confirmation_method`. Unknown free-form qualifiers MUST NOT become executable matching semantics. Add new standardized qualifiers through a versioned contract update.

Minimum coverage slots: `demographics.age`, `demographics.administrative_gender`, `disease.primary`, `disease.histology`, `disease.stage`, `disease.metastatic`, `performance.status`, `therapy.event`, `biomarker.result`, `lab.result`, `logistics.treating_center`. The trial-specific input contract SHOULD name required analytes/markers; a generic unknown lab/biomarker slot does not prove all analytes/markers were individually assessed.

**Safety slots are trial-contract-driven, not baseline (decision).** `safety.pregnant`/`wocbp`/`pregnancy_test`, `disease.recist_measurable`, and `cardiac.*` are deliberately **not** in the minimum baseline: they are hard only when a specific trial states them, so the trial's criterion contract names them and they surface as unknown→unresolved when absent. This does **not** weaken them — an absent trial-named safety slot blocks `eligible_pending_review` exactly as any unresolved hard criterion does (§matching semantics); it is simply not demanded of every packet up front.

**Therapy absence is `unknown`, not negative.** A therapy class/agent not appearing among assessed `therapy.event` facts does NOT establish "no prior X." For an **exclusion** (or a "no prior X" inclusion) this is the dangerous false-pass direction: such a `not_exists` returns `unknown` unless a `coverage.completeness` assertion whose scope **subsumes the criterion's** (matching concepts/classes, disease+setting, and lifetime-vs-window) exists, **or** a criterion-scoped `explicit_negative` fact exists. Mere presence in `assessed_fact_keys` is not enough, and a complete *export window* MUST NOT clear a *lifetime* "no prior therapy" criterion (matcher `MATCHER_DESIGN.md` §5.4).

## Time and normalization rules

**TimePoint:** `{kind: "point", value: string, precision: "year" | "month" | "day" | "second", time_basis: "shifted_patient_local" | "unshifted_verified" | "unknown"}`. Value MUST match its precision: `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or RFC 3339 timestamp with offset. Clinical time MAY have reduced precision; unknown time is null, never an invented date.

**TimeInterval:** `{kind: "interval", start: TimePoint | null, end: TimePoint | null}`. At least one bound MUST be present; non-null bounds MUST use the same time basis. No artificial January 1 birth date, sample date or treatment end date may be created from partial data.

- `shifted_demo` MUST set `absolute_screening_recency_allowed = false`; shifted timestamps MUST NOT be compared with real today or real enrollment deadlines to claim screening validity.
- Relative intervals MAY be evaluated within the same patient's shifted time basis using an explicit compatible anchor and sufficient precision. They MUST be labeled demo/historical, not current enrollment clearance.
- Cross-patient shifted dates MUST NOT establish shared chronology.
- Age generalization MUST be retained; narrative MUST NOT recover suppressed precision.
- Lab thresholds require validated analyte/unit identity. Preserve inequalities, method and reference ranges; percentage is not absolute count. “Latest” MUST select within compatible time/context, not blindly choose the greatest timestamp.
- eGFR/ANC derivations require reviewed formulas and sufficient inputs; no guessed demographics or units. Karnofsky MUST NOT silently convert to ECOG. Biomarker scores/assays MUST NOT be treated as interchangeable.
- A fact may be recorded recently but describe historical disease. Recording time alone MUST NOT make the assertion current.

## Matching semantics

Packets contain patient facts, **not** trial-specific pass/fail labels. The hospital-side matcher applies a separate versioned criterion-atom contract with explicit inclusion/exclusion polarity, Boolean groups, thresholds, exceptions, timing and arm/cohort scope.

Matcher output per criterion (`predicate_state`, `evaluation_state`, `fact_refs`, `reason_codes`) and the roll-up states (`eligibility_state`, `evidence_coverage`) are defined **normatively in `MATCHER_DESIGN.md` §8.1** — the single source for the shared result vocabulary. This document does not restate those enums; consumers MUST use the §8.1 definitions.

`true` for an exclusion predicate means the exclusion is triggered, not a positive match. A hard inclusion `false` or hard exclusion `true` may establish `eligibility_state = ineligible` (§8.1). Unknown required evidence MUST NOT become pass or rejection solely because it is missing; it leads to unresolved screening/review.

Interval facts: wholly satisfying the predicate → true; wholly failing → false; crossing its boundary → unknown. Quantity comparators require the same set-based reasoning. Family-history, suspected, rejected or incompatible-time evidence cannot silently establish a definitive hard outcome.

Protocol hardness is independent of extraction difficulty: RECIST, washout, pregnancy and tissue requirements may be hard. Consent/willingness may be deferred for pre-screening but MUST remain unresolved before enrollment. Relevance, evidence coverage and eligibility state MUST be separate outputs; a high relevance score MUST NOT conceal missing safety checks.

For unknown administrative gender or differing protocol-specific sex semantics, mark the predicate unresolved unless explicit appropriate evidence is available. Diagnosis embeddings MAY retrieve candidates locally but MUST NOT be the sole definitive disease eligibility gate.

## Synthetic example

**Entirely fictional.** The example illustrates shape and uncertainty, not a complete patient packet, clinical reference case, or exported source record. The year/time anchor is arbitrary demo metadata. Source IDs and codes are invented local identifiers.

```json
{
  "schema_version": "avicenna.patient-packet/1.1.0",
  "packet_id": "synthetic-packet-001",
  "patient_ref": "synthetic-patient-001",
  "generated_at": "2026-10-17T09:00:00Z",
  "environment": "synthetic_demo",
  "source_snapshot": {
    "snapshot_id": "synthetic-fixtures-v1",
    "ingestion_state": "complete",
    "extractor_version": "synthetic-example-v1",
    "terminology_version": "synthetic-vocabulary-v1"
  },
  "evaluation_context": {
    "mode": "shifted_demo",
    "anchor": {
      "kind": "point",
      "value": "2026-04-01",
      "precision": "day",
      "time_basis": "shifted_patient_local"
    },
    "absolute_screening_recency_allowed": false,
    "policy_version": "demo-interval-policy-v1"
  },
  "facts": [
    {
      "fact_id": "age-1",
      "fact_key": "demographics.age",
      "state": "known",
      "value": {
        "kind": "interval",
        "lower": 60,
        "upper": 64,
        "lower_inclusive": true,
        "upper_inclusive": true,
        "unit": "years"
      },
      "missing_reason": null,
      "assertion": "positive",
      "subject_scope": "patient",
      "effective_time": null,
      "recorded_time": null,
      "evidence": [
        {
          "resource_type": "Patient",
          "resource_id": "synthetic-patient-001",
          "version_id": "1",
          "locator": "extension[synthetic-age-band]",
          "source_kind": "structured",
          "verification_status": "source_assertion"
        }
      ],
      "provenance": {
        "method": "source_projection",
        "method_version": "synthetic-example-v1",
        "model_id": null,
        "confidence": null,
        "input_fact_refs": []
      },
      "review_status": "unreviewed",
      "generalization": {
        "applied": true,
        "constraints": ["do_not_narrow_age_band"]
      },
      "alternatives": [],
      "scope": null
    },
    {
      "fact_id": "performance-unknown-1",
      "fact_key": "performance.status",
      "state": "unknown",
      "value": null,
      "missing_reason": "not_documented",
      "assertion": null,
      "subject_scope": "patient",
      "effective_time": null,
      "recorded_time": null,
      "evidence": [],
      "provenance": {
        "method": "source_projection",
        "method_version": "synthetic-example-v1",
        "model_id": null,
        "confidence": null,
        "input_fact_refs": []
      },
      "review_status": "unreviewed",
      "generalization": {"applied": false, "constraints": []},
      "alternatives": [],
      "scope": null
    }
  ],
  "coverage": {
    "assessed_fact_keys": ["demographics.age", "performance.status"],
    "unassessed_fact_keys": [
      "demographics.administrative_gender", "disease.primary", "disease.histology",
      "disease.stage", "disease.metastatic", "therapy.event", "biomarker.result",
      "lab.result", "logistics.treating_center"
    ],
    "completeness": []
  },
  "warnings": ["partial_fact_assessment", "shifted_dates_not_real_screening_time"]
}
```

For this synthetic age interval, an age-only predicate “at least 18” is true, “at most 62” is unknown, and “at most 50” is false, subject to the criterion's age-time semantics. Unknown performance status cannot establish an ECOG requirement. This example makes no trial eligibility claim.

## Validation and acceptance

Before a packet is accepted:
1. Validate version, required fields, strict enum/type rules and finite values; reject unexpected fields rather than assigning them semantics.
2. Validate state/value/missing-reason/assertion consistency, required evidence, unique IDs, local references and non-cyclic conflicts/derivations. Null assertion does not remove a criterion from applicability.
3. Validate interval bounds, stage/performance scale constraints, timestamp precision/time basis, and shifted-mode restrictions.
4. Validate concept/unit normalization status; ensure unvalidated mappings cannot satisfy normalized thresholds.
5. Ensure all minimum coverage slots are assessed or explicitly unassessed. Unassessed MUST NOT be interpreted as not-tested/negative.
6. Ensure patient attribution and review status constrain eligibility use; family-history or rejected evidence MUST NOT establish a patient fact.
7. Validate no direct identifiers/narrative excerpts/secrets and no external evidence-fetch locations. Schema validation alone is not a complete de-identification check.
8. Record immutable packet/source/extractor/rule versions so local decisions can be reproduced. Errors SHOULD emit controlled codes without packet contents.
9. Validate scored-instrument discriminated numeric/ordinal fields and pinned bounds/step/category ordering; unknown instruments cannot define their own semantics.
10. Validate scoped absence/completeness concepts, typed temporal bounds/cutoff, setting/disease coverage, registry versions, reconciled evidence and authorized human/process records. Contradictory exposures cannot be cleared by a completeness flag. No bare complete-fact-key list is accepted.

**Version migration:** 1.1.0 replaces filler `assertion = not_applicable` with null, defines Scope/scoped_absence and authorizes typed completeness assertions. These proposed-draft changes are not silently compatible with 1.0.0. Consumers MUST explicitly support 1.1.0; migration MUST NOT invent scope, registry versions or review authorization. Old incomplete assertions remain unresolved pending review.

Synthetic acceptance tests MUST cover generalized age boundaries; absent vs explicit negative vs not-tested; ambiguous biomarkers; copied historical evidence; conflict references; unsupported units; inequality-valued labs; shifted-date recency; incomplete ingestion; prescriptions vs administration; therapy-line uncertainty; Boolean exclusion polarity (a cleared hard exclusion — predicate `false` — MUST contribute to a positive, never require predicate `true`); a stale reviewed/structured fact that MUST NOT override a more recent lower-authority fact for a current-state predicate; an `assessed`-but-not-`complete` therapy domain where a `not_exists` exclusion MUST resolve `unknown`, not clear; a `bounded`-window completeness assertion that MUST NOT clear a `lifetime` "no prior therapy" criterion, and a concept/setting-scoped assertion that clears only the criteria it subsumes; an unknown/unvalidated concept-membership mapping that leaves a subsumption test `unknown` rather than assuming (non-)membership; a `completeness` entry whose `method` lacks authorized-reviewer/approved-process provenance being rejected; and no external fallback.

Clinical validation is separate: an authorized reviewer SHOULD assess both extracted candidates and apparent misses, adjudicate relevant evidence, and measure extraction errors per field before using outputs for consequential matching. An LLM confidence score or a successful JSON parse is insufficient.

Related design documents: `PATIENT_MATCHING_DATA_NEEDS.md`, `PATIENT_MATCHING_DATA_NEEDS_RESPONSE.md`, `MATCHER_DESIGN.md` (evaluation engine; §8.1 shared result vocabulary), and `reports/GENERAL_DATA_GUIDE.md`. These describe requirements and limitations; they do not establish patient-level completeness.

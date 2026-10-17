# Privacy-safe data and integration guide

## Audience and permitted use

This report and `PATIENT_MATCHING_DATA_NEEDS_RESPONSE.md` are intended for models without approved patient-data access. They describe interface/schema and engineering constraints without patient records, excerpts, identifiers, filenames carrying pseudonyms, exact cohort counts, disease frequencies, clinical distributions, or record-level examples. They are not a substitute for authorization to access the source data.

Do not open the restricted report, dataset, decoded attachments, patient-derived features, audit manifests, or logs. Implement against wholly synthetic fixtures, not transformed real examples. Do not request data samples from another model. Patient-linked scores/explanations are protected data too.

## Data structure overview

The integration supports FHIR R4 transaction Bundles, tabular exports, and readable clinical documents. FHIR is the preferred import format; tables support reconciliation rather than being separately imported as duplicate clinical facts. NDJSON represents one transaction Bundle per line, not an ordinary single FHIR transaction for the entire file. Diagnosis-split exports may overlap; choose one canonical import stream.

| Area | FHIR surface | Engineering constraints |
|---|---|---|
| Demographics | Patient + custom extensions | Exact age, age interval, or missing value; do not fabricate dates or recover suppressed values |
| Diagnoses | Condition | ICD-10 with possible deliberate generalization; missing does not mean disease absent |
| Clinical reports | DocumentReference | Base64 text/HTML attachments; decode locally and sanitize HTML |
| Imaging | ImagingStudy + DiagnosticReport | Metadata/findings only; indirect PACS availability is not access to images |
| Laboratories | Observation + DiagnosticReport | Local method codes, numeric/text/missing results, units and reference ranges; validated unit mappings required |
| Treatment | MedicationRequest, MedicationAdministration, Procedure | Prescriptions and billing evidence do not establish a curated active regimen |
| Scheduled exams | ServiceRequest when provided | Design for empty datasets; no fabricated planned events |

The data contract may pseudonymize identifiers, shift dates per patient, and generalize demographics/diagnoses. These reduce risk without making clinical data anonymous. Within-patient intervals may survive shifting; absolute comparisons with today may not. Custom terminology URIs are vocabulary identifiers, not endpoints to fetch.

## Hospital-side integration contract

```text
Avicenna cloud: public trial catalog → criteria structuring
                                    ↓ versioned criteria only
Hospital boundary: IRIS → local matcher → local clinician UI and alerts
```

No cloud FHIR search, chart access, feature fetching, or patient-linked result retrieval. Keep feature extraction, matching, scores, explanations, evidence, and alert delivery inside the approved hospital/event boundary. An external EU-hosted model is not automatically hospital-side or approved.

A criteria payload should contain trial ID/version, criterion IDs, inclusion/exclusion kind, vocabulary, operator, threshold/unit, time-window semantics, required evidence, and unsupported/needs-review flags. Public trial criteria can be structured by a cloud LLM, but generated rules require validation. Rule evaluation is deterministic/conservative inside the boundary. Do not expose a patient-data API to cloud to make rule authoring easier.

Clinician-facing local results should distinguish met / not met / data missing or indeterminate, and record local evidence/provenance. Final eligibility needs clinical review. Absence of a coded row is not proof of a negative exclusion criterion. This is a design contract; the matcher and UI are not implemented by the current infrastructure setup.

## Implementation guidance

1. Use entirely synthetic R4 fixtures to develop importer, criteria parser, matcher, and UI. Keep fixtures clearly labeled and unrelated to source patients.
2. PUT-based transaction entries should use deterministic IDs and valid local references. Stable live IDs do not prevent history/version growth on repeated uploads.
3. Validate JSON/FHIR shape, allowed types, reference integrity, code systems, numeric parsing, and units. Keep validation enabled; quarantine unsupported input rather than forcing it through.
4. Stream Bundles with bounded memory/concurrency and protected checkpoints. Inspect all transaction-response statuses. Timeouts can mean uncertain completion; use fixed-ID reconciliation and bounded retry.
5. Handle age bands using interval logic: wholly inside → met, wholly outside → not met, overlapping boundary → indeterminate. Unknown units or incomparable shifted dates → missing/unsupported.
6. Build local evidence extraction with negation, uncertainty, temporality, provenance, and manual-review paths. Narrative extraction must respect deliberate generalization and cannot silently override missing or suppressed values.
7. Test auth denial, failed transactions, duplicate IDs, missing references, unit mismatches, overlapping age bands, empty streams, pagination, retries, and exclusion criteria with unknown evidence.
8. Keep secrets, patient data, features, and logs outside Git/shared artifacts. Never render unsanitized report HTML or follow links embedded in source content.

The current IRIS mock has an enabled, authenticated FHIR R4 endpoint in namespace `AVICENNA`, with verified HTTPS and only port 443 published. The user approved the destination for event data and ingestion was started; completion must be checked separately by an authorized operator. It remains publicly addressable with ephemeral storage, not a private-subnet installation. Models without patient-data access must use synthetic fixtures only and must not query it. Scoped runtime identities, capacity tests, retention controls and restart reliability remain separate requirements; HTTPS/authentication do not establish GDPR compliance by themselves.

## Limitations

This guide intentionally omits dataset-specific inventory and clinical findings. It does not certify the dataset, GDPR compliance, production security, or clinical accuracy. Models using this guide should not attempt patient-level debugging: provide synthetic reproductions to an authorized operator, who can run the checks locally and return a sanitized engineering issue.

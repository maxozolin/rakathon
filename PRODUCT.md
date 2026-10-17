# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Static HTML/CSS (single self-contained file, no build step) for the UI mock. Confirmed by the user.

## Users

Primary: a treating oncologist checking trial options for one patient during a consult. They have minutes, the patient may be in the room, and they need to know which open trials are plausible, what blocks each one, and what to check next. They decide whether to refer the patient to a trial coordinator; they do not enrol from this screen.

## Product Purpose

Avicenna is a hospital-side clinical-trial matcher. It evaluates one patient's structured packet (`avicenna.patient-packet/1.1.0`) against atomized trial criteria packs (`avicenna.criteria-pack/0.1`, per `TRIAL_DATA_STANDARD.md` v1.3). It returns a per-trial, per-arm, per-criterion verdict with the reason and the evidence used. Success: the clinician trusts the shortlist because every verdict shows why, and nothing unknown is ever shown as passed or failed.

## Positioning

Deterministic, offline, fail-closed matching. UNKNOWN never collapses into pass or fail. Every criterion carries a reason code, the verbatim trial text and the fact references it rests on. The best possible state is "eligible pending review", never a bare "eligible". Patient data never leaves the hospital boundary.

## Operating Context

- Used inside the hospital network next to the EHR during a consult.
- Trial data comes from public registries (the local ClinicalTrials.gov snapshot) after atomization into criteria packs.
- Patient packets are built inside the hospital by the patient-pack builder.
- A trial coordinator does the follow-up chart review.

## Capabilities and Constraints

Eligibility states:

- `eligible_pending_review`
- `needs_chart_review`
- `manual_review`
- `ineligible`

Criterion outcomes:

- `satisfied`
- `clear`
- `resolved_disqualifier`
- `unresolved`
- `non_blocking`
- `not_applicable`

Each verdict also carries:

- reason codes in categories (evaluation_blocking, applicability, evidence_absent, evidence_ambiguous, evidence_conflict, evidence_stale, concept_unsupported, temporal, structural);
- evidence coverage;
- the anchor date and `policy_version`.

Procedural and consent criteria always need manual review. The UI must display the result vocabulary faithfully (`MATCHER_DESIGN.md` §8.1).

## Evidence on Hand

- Synthetic demo only: `matcher/tools/mock_patient_demo.py` provides 5 synthetic patients and 3 atomized ClinicalTrials.gov trials (NCT07062965, NCT06252649 CodeBreaK 301, NCT07218380 FORAGER-2).
- No real patient data may be used or shown in UI work.
- No clinical validation, accuracy figures or customer claims exist; do not fabricate them.

## Product Principles

- Unknown is a first-class answer; it is never hidden or rounded to pass or fail.
- Every verdict is explainable down to source text and evidence.
- Next action over score: show what to check, not a ranking number.
- The clinician decides; the tool pre-screens.

## Accessibility & Inclusion

Clinical-grade legibility is required. State is never shown by colour alone. The screen must be keyboard-operable and meet WCAG 2.2 AA contrast.

# Manual patient packet pilot — sanitized engineering findings

## Scope

An authorized local pilot manually transformed selected real source evidence into the canonical patient packet and evaluated it with the current matcher. This document contains engineering conclusions only: no patient identifiers, excerpts, clinical values or patient-linked outcomes. Models without patient-data access may read this file, not the restricted packets or report.

This was a small convenience sample chosen for explicit performance-status evidence, not a representative or disease-matched cohort. One real public registry trial was retained as a partial CriteriaPack, with unsupported/unstructured criteria kept opaque. Diagnostic sub-packs were used separately to isolate field behavior; they are not trial eligibility assessments. No external API calls or IRIS patient readback were performed. No engine code changed.

## Helpful

- Canonical packets now flow through the adapter and schema-validated pipeline.
- Explicit numeric ECOG can be represented with the pinned scored-instrument registry and evaluated. Removing that fact in an ablation changes the diagnostic predicate from evaluable to missing.
- Generalized ages remain intervals; suppressed age remains unknown instead of being recovered from narrative.
- Coded historical biomarker results can be evaluated with explicit marker and result systems when querying historical evidence. This does not imply assay-equivalent current trial eligibility.
- Unmapped laboratory units stay unsupported, rather than being silently treated as standardized measurements.
- Missing evaluation anchors leave screening-dependent predicates unresolved. Partial/opaque protocol coverage prevents a false all-clear.

## Not yet helpful / limitations

- Stage values still become indeterminate through the adapter. Keep the canonical stage evidence; do not invent a Boolean stage substitute just to get a match.
- A document-local performance score is not automatically screening-current. The local export uses shifted dates; present screening time was not reconstructed.
- Unmapped labs remain unusable for normalized thresholds until the analyte/unit pipeline is validated.
- Whole-trial outcomes in this pilot are dominated by deliberately opaque criteria and absent anchors. They do not measure matcher recall, precision, clinical suitability or candidate yield.
- Public trial text has temporal, specimen, therapy-context and exception requirements; a scalar demographic/biomarker match alone does not implement them.

## Edge cases identified

1. Coded diagnosis and report diagnosis can disagree. Preserve source-specific assertions and obtain adjudication; never silently choose one as the primary disease.
2. Document metadata time may differ from its internal encounter date. Keep recorded and effective time distinct with source locators and provisional date interpretation.
3. A recent report can repeat old stage/biomarker history. Currentness must follow effective evidence time, not the report timestamp.
4. Different specimens/assays can have different biomarker scores without a same-event contradiction. Do not merge them or arbitrarily choose one.
5. A nonspecific score abbreviation without marker/assay linkage must remain unassigned.
6. Metastasis in differential diagnosis is not confirmed metastatic disease; organ-negative wording is not an all-sites/lifetime negative.
7. Remission/local-recurrence-negative text does not certify lifetime absence of metastases.
8. Prescribed/planned/current therapy wording is not a reviewed complete exposure history or reliable line number.
9. Order requests for labs are not results. Generic “labs normal” statements cannot populate individual screening values.
10. Generalization is a privacy constraint: suppressed age/diagnosis precision must not be recovered from narrative.

## Next step

Expand to a diagnosis-targeted reviewed batch, faithfully structure selected relevant trial gates, normalize a small validated analyte/unit set, and test temporal/specimen/therapy-context rules. Separate full-trial triage from diagnostic atom probes. Add clinician-reviewed gold labels before estimating clinical accuracy. Reconciliation completeness remains empty unless separately authorized and supported.

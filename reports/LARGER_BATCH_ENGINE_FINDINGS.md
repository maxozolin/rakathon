# Larger local batch — sanitized engineering findings

The authorized batch evaluated 60 local patient packets against three real public trials (180 evaluations). Sampling covered three coded oncology groups and required documented local care evidence; it was a convenience sample, not primary-diagnosis adjudication or a representative cohort. Patient identifiers, clinical values, source excerpts and detailed per-group outcomes are omitted here. Restricted artifacts are in `.opencode-secrets/larger-patient-batch/`.

## Results and interpretation

- Initial evaluation rejected the saved demographic `any_history` relation. The registry age atom was updated to the supported `current` snapshot relation, and the same packets were rerun without changing patient facts, anchors or completeness. Both direct and complementary age encodings now agree across the batch; no top-level disagreements were observed.
- The corrected registry run produced both `eligible_pending_review` and `needs_chart_review`. Positive results are modeled registry pre-screen candidates only, with consent/site/enrollment review outstanding. Treatment-trial evaluations remained `manual_review`; no supported clinical disqualification was established by the unstructured treatment packs.
- The registry outputs still distinguish supported disease/location evidence from missing disease evidence, despite sharing the same top-level state. Eligibility state alone does not rank strong versus wrong-disease candidates.
- Treatment outputs were dominated by opaque criteria, missing clinical facts and absent screening anchors. The treatment packs were largely or entirely unstructured; these outcomes measure integration gaps, not the patients' clinical suitability.

## What this batch tested

Structured demographic and Condition projection, explicit documented Czech care evidence, canonical adaptation, validation, real-trial output generation, privacy-preserving missing values and equivalent age-encoding traces. It did NOT perform comprehensive narrative extraction, assay/unit normalization, clinical adjudication or complete therapy reconciliation. No real screening anchor or completeness assertion was invented. No external API calls or IRIS patient readback occurred.

## Next actions

1. The registry demographic atom has been updated and rerun; retain export-age effective-time caveats and add supported snapshot semantics to future curated packs.
2. Curate faithful treatment-trial gates and extract diagnosis-state/performance/biomarker evidence before judging match usefulness.
3. Report resolved criteria, missing inputs, unsupported semantics and protocol opacity separately; distinguish disease mismatch from absence of a disease code.
4. Review a targeted set of strong/close/negative candidates before estimating accuracy or scaling to the full population.

The test suite at run time reported 541 passed, 2 skipped and 4 expected failures. This is engineering evidence, not clinical validation. A more positive result count is not a success criterion unless its supporting facts, rule semantics and uncertainty handling are correct.

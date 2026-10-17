# Evidence-backed candidate search — sanitized engine findings

## Scope

Followed the patient/trial builder prompts in `prompts/`, preserving evidence and uncertainty. A local real-data search identified strong candidates for public recruiting registry `NCT03199066` (NiHiL), then tested close and wrong-disease controls. This is an observational lymphoma registry, **not a treatment trial or enrollment clearance**. No patient identifiers, clinical values, excerpts or exact patient counts are included here. Restricted traces remain outside Git.

The registry's visible criteria are short: lymphoma diagnosis, Czech treatment, consent and an under-adult-age exclusion. Consent remains procedural/outstanding. The full visible list was retained; source completeness describes that registry list, not independent certification that all site/protocol requirements are represented. A curated broad source-ICD-10 lymphoma binding was used on both sides; no suppressed diagnosis precision was recovered. The source age was used for pre-screening only, not reconstructed at actual enrollment time.

## Findings

- Strong evidence-backed candidates reached `eligible_pending_review` with supported lymphoma/care-location evidence and adult age under the complement encoding below. This is “modeled pre-screen gates cleared,” not definite clinical eligibility or participant consent.
- A close candidate with supported disease/location but deliberately suppressed age remained `needs_chart_review`. No narrative age reconstruction or fabricated anchor was used.
- A wrong-disease control also remained `needs_chart_review`: absence of a lymphoma code did not become proof of no lymphoma. This illustrates the need for separate relevance ranking and explicit disease evidence rather than expecting eligibility state alone to identify close candidates.

## Confirmed encoding-sensitivity edge case

For a documented adult age, two mathematically equivalent encodings of the exclusion “age <18” gave different results under `any_history`:

1. Direct `age <18`: unresolved / `absence_not_established`.
2. Criterion `not` over `age >=18`: exclusion clear.

Cause: the generic existential-history evaluator requires explicit negative assertions to return FALSE, even for a numeric comparison of a known demographic value. The positive complement can return TRUE and be negated. This is inappropriate encoding dependence for a same-assertion age check, although historical queries such as “was ever under 18” are different from age at enrollment.

Both traces are retained. Neither an existential export-age check nor its complement establishes age at an unknown enrollment/consent date. Production fix should explicitly distinguish a snapshot demographic predicate from lifetime event-existence queries, and require a valid enrollment anchor where the criterion requires one. Do not adopt complementary encoding merely to inflate positive yield.

## Limits and next steps

This search found a useful positive/close **registry** demonstration, not verified positive oncology treatment pairs. Treatment trials still need explicit disease-state, biomarker, therapy, screening safety and protocol evidence; missing criteria must not be omitted to manufacture matches. A separate diagnosis-targeted treatment batch is still needed.

Priorities: fix numeric-versus-history quantifier semantics; validate the source-to-trial concept mapping; preserve unknown age; separate registry participation from treatment actionability; include consent and site review; and expand reviewed real-trial coverage without fabricating absences/completeness or clinical timestamps.

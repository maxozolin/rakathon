# Targeted breast-treatment pilot — sanitized findings

## Scope

An authorized local pilot manually inspected breast-cancer report evidence and built canonical patient packets containing explicit ECOG, specimen/time-specific receptor candidates and therapy evidence. Actual packets/results remain restricted outside Git. No patient identifiers, excerpts, values or individual clinical findings are included here.

Real public treatment trials NCT06760637 and NCT07085767 were read from the local catalog. All visible bullets were retained; simple receptor and performance requirements were structured where sound, while unsupported disease/therapy/RECIST/safety requirements remained opaque. Both packs were marked partial. This is a small convenience sample, not a strong-match cohort or clinical validation.

## Outcome

The treatment evaluations all remained manual_review. The canonical adapter accepted the selected performance, receptor and therapy representations without reporting adaptation losses, but that does not establish that every semantic qualifier is evaluated by the matcher.

- Receptor screening predicates were unresolved with anchor_missing.
- Performance predicates, including a diagnostic current-state probe, were unresolved with recency_unbounded.
- Opaque protocol requirements continued to force review.

The current engine no longer treats document-local ECOG as automatically usable current screening evidence. That is safer, but it means richer extraction alone does not create evaluable screening gates without an explicit temporal policy/anchor. No anchor, arbitrary freshness window or completeness was fabricated to improve results.

## Helpful extraction versus missing capability

The manually built packet can preserve an explicit score range, historical receptor results, a pending/addendum assay sequence and prescription-versus-administration distinctions. Those facts improve the local review queue even when full eligibility stays unresolved.

Remaining work: explicit diagnosis/episode mapping, faithful histology/state predicates, specimen/assay-aware receptor evaluation, reviewed analyte/unit mapping, and therapy line/progression/timing logic. Stage, RECIST, complete prior therapy and current safety cannot be inferred from report summaries alone. Historical results should not be stamped with a recent report date.

## Edge cases

- A performance range straddling a threshold must remain indeterminate rather than choosing its lower value.
- Different biomarker specimens/assays/times are not one result and not automatically a conflict.
- Receptors from a concurrent second tumor must not feed breast eligibility predicates.
- Protein ER positivity/negativity is not ESR1 mutation status, despite a shared symbol binding.
- “Pending” plus an explicit addendum is different from a persistent missing assay; retain event provenance.
- Narrative therapy and prescriptions do not certify administered exposure, therapy lines or complete history.
- Clinical care consent wording is not study-specific informed consent.

## Next useful experiment

Agree an explicitly labeled shifted historical evaluation context for demonstration, supplied by the caller, rather than pretending to evaluate real screening today. Compare it with the null-anchor baseline. Then curate relevant disease/assay/therapy gates and review a small set of gold labels before reporting treatment match quality. Real enrollment still needs actual unshifted screening evidence and study-team review.

No external API/model calls, IRIS patient readback or matcher-code changes were made. Safe output here describes engineering behavior, not patient eligibility.

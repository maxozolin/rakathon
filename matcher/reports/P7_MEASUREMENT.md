# P7 — Matcher measurement report

Generated with `python matcher/tools/measure.py --ctis data/ctis/ctis.sqlite --ctgov data/ctgov/ctgov.sqlite --packs matcher/tools/sample_packs`. The script is deterministic and its tables are reproduced below. Inputs are public trial catalogs and synthetic packets only; the harness refuses any `rakathon-dataset` path.

## Findings

**§10.2 — do real criteria need the four §5 constructs? Yes. They are the common case, not edge cases.**
- 66% of all criteria, and 93% of exclusions, hit at least one construct. Absence (§5.4) dominates: 78% of exclusions are condition/state absences and 13% are therapy-scoped "no prior X".
- Relative-to-reference (1.9%), derived values (3.1%) and cross-criterion refs (0.3%) are rare but present. Guards and exceptions (13%) are common, and jurisdiction-specific guards are 2.3%.
- About 24% of criteria are likely `opaque_text` (compound or judgment). The atomizer must degrade these honestly rather than guess.

**§13.7 — launch impact on `eligible_pending_review`: absence evidence, not matching logic, is the bottleneck.**
- Best case means every measurable fact is present and favourable. Even then, with S0 (the launch default: no negatives, no completeness), only **0.5–1.1%** of trials can reach `eligible_pending_review`. Priority (Motol/Homolka) trials: 0.6–1.4%.
- Explicit negatives (S1) lift this to 8–37%. Reviewed-reconciliation completeness (S2) lifts it to 14–100%, depending on how much of the text the atomizer can handle.
- `manual_review` (57–76% under realistic atomizers) is driven almost entirely by **severity**, i.e. an un-evaluable judgment exclusion, not by the ⅓ ratio. Atomizer quality on "clinically significant X" exclusions is therefore the second lever.
- Conclusion: for the pilot, the auto-positive set is gated by reviewed scoped absence. It is not gated by engine capability. The fail-closed default is behaving as designed; yield is bought with review effort, not with relaxed rules.

**Exact pipeline check (Part B).** Four synthetic packs (onc not_exists, CZ guard, partial/opaque, basket arms) run through the real pipeline with constructed best-case witnesses. Each moves from S0 to S2 exactly as the census predicts. The partial pack stays `manual_review` even when forced complete.

**Design gaps surfaced**
1. Reviewed-reconciliation completeness is the critical input. The adapter accepts it only under a pinned local authorization policy, and no such data exists yet.
2. Judgment exclusions need either a reviewer-in-the-loop atom or an agreed reading; today they force `manual_review`.
3. Stage, biomarker and scored-instrument values are not yet interpreted from canonical packets (→ indeterminate). Their share of criteria should be measured once packs are atomized.
4. Part A is a lexical proxy. Exact rates need atomized packs for real trials.


## A. Corpus census — lexical PROXY (no atomizer yet)

2173 trials, 1993 with criteria text (483 Motol/Homolka); 36287 criteria (13746 inclusion / 22541 exclusion).

### §10.2 — how many real criteria need the four constructs

| signal | all | inclusion | exclusion |
|---|---|---|---|
| **any of the four §5 constructs** | 66.1% | 21.4% | 93.4% |
| §5.1 relative-to-reference (ULN/LLN) | 1.9% | 2.0% | 1.8% |
| §5.2 derived value (CrCl, eGFR, BMI, QTc…) | 3.1% | 3.7% | 2.8% |
| §5.3 guarded / exception (`in patients with`, `unless`, jurisdiction) | 13.3% | 16.8% | 11.2% |
| §7.3 jurisdiction-specific (`participants in France`, `local regulations`) | 2.3% | 4.3% | 1.0% |
| §5.4 absence — therapy-scoped (`no prior X`) | 8.5% | 1.3% | 13.0% |
| §5.4 absence — condition / state (any non-measurement exclusion) | 48.7% | 1.0% | 77.8% |
| §6.4.5 cross-criterion reference | 0.3% | 0.4% | 0.3% |
| plain measurement / threshold | 32.2% | 48.2% | 22.5% |
| procedural only (consent, willingness) | 5.4% | 11.8% | 1.6% |
| investigator judgment / clinical significance | 11.3% | 8.0% | 13.3% |
| compound (> 60 words, ≥ 3 clauses, `e.g.`/`as defined by`) | 18.0% | 20.9% | 16.2% |
| **likely `opaque_text`** (compound or judgment) | 24.3% | 23.5% | 24.8% |

### §13.7 — best-case `eligible_pending_review` ceiling by completeness scenario

Best-case patient: every measurable fact present and favourable. Atomizer levels: **conservative** — compound and judgment criteria become opaque_text; **optimistic** — compound criteria atomized faithfully; judgment criteria stay opaque_text; **judgment_atomized** — everything atomized; 'clinically significant X' read as presence of X.

| subset | atomizer | scenario | eligible_pending_review | needs_chart_review | manual_review (severity / ratio) |
|---|---|---|---|---|---|
| all (n=1993) | conservative | S0 | 0.5% | 23.8% | 75.7% (1492 / 17) |
| all (n=1993) | conservative | S1 | 7.9% | 16.4% | 75.7% (1492 / 17) |
| all (n=1993) | conservative | S2 | 14.1% | 10.1% | 75.7% (1492 / 17) |
| all (n=1993) | optimistic | S0 | 0.9% | 37.5% | 61.6% (1217 / 11) |
| all (n=1993) | optimistic | S1 | 15.4% | 23.0% | 61.6% (1217 / 11) |
| all (n=1993) | optimistic | S2 | 30.4% | 8.0% | 61.6% (1217 / 11) |
| all (n=1993) | judgment_atomized | S0 | 1.1% | 98.9% | 0.0% (0 / 0) |
| all (n=1993) | judgment_atomized | S1 | 36.6% | 63.4% | 0.0% (0 / 0) |
| all (n=1993) | judgment_atomized | S2 | 100.0% | 0.0% | 0.0% (0 / 0) |
| priority (n=483) | conservative | S0 | 0.6% | 26.3% | 73.1% (348 / 5) |
| priority (n=483) | conservative | S1 | 10.1% | 16.8% | 73.1% (348 / 5) |
| priority (n=483) | conservative | S2 | 15.1% | 11.8% | 73.1% (348 / 5) |
| priority (n=483) | optimistic | S0 | 1.0% | 42.0% | 56.9% (273 / 2) |
| priority (n=483) | optimistic | S1 | 16.6% | 26.5% | 56.9% (273 / 2) |
| priority (n=483) | optimistic | S2 | 31.9% | 11.2% | 56.9% (273 / 2) |
| priority (n=483) | judgment_atomized | S0 | 1.4% | 98.6% | 0.0% (0 / 0) |
| priority (n=483) | judgment_atomized | S1 | 34.4% | 65.6% | 0.0% (0 / 0) |
| priority (n=483) | judgment_atomized | S2 | 100.0% | 0.0% | 0.0% (0 / 0) |

Scenarios: **S0** no negatives / no completeness (launch default); **S1** documented explicit negatives, no reviewed completeness; **S2** reviewed-reconciliation completeness.

## B. CriteriaPacks — exact (real pipeline, synthetic witness packets)

4 packs, 15 criteria.

- completeness_note: complete 86.7%, opaque_text 6.7%, partial 6.7%
- logic: any 1, single 14
- atom predicate types: derived_value 1, guarded_case 1, not_exists 1, procedural 1, relative_to_reference 1, simple_comparison 10

| trial | completeness | no-witness hard criteria | S0 | S1 | S2 | forced complete (S2) |
|---|---|---|---|---|---|---|
| SYNTH-P7-BASKET | complete | 0 | eligible_pending_review | eligible_pending_review | eligible_pending_review | — |
| SYNTH-P7-CZ | complete | 0 | needs_chart_review | eligible_pending_review | eligible_pending_review | — |
| SYNTH-P7-ONC | complete | 0 | needs_chart_review | needs_chart_review | eligible_pending_review | — |
| SYNTH-P7-PARTIAL | partial | 1 | manual_review | manual_review | manual_review | manual_review |

| scenario | eligible_pending_review yield | opaque criteria | manual_review arms |
|---|---|---|---|
| S0 | 25.0% (1/4) | 6.7% | 20.0% |
| S1 | 50.0% (2/4) | 6.7% | 20.0% |
| S2 | 75.0% (3/4) | 6.7% | 20.0% |

## Caveats

- Part A is lexical: it estimates construct *demand* and a best-case *ceiling*; it is not matcher output. Real rates require atomized packs (Part B) once the atomizer exists.
- Best-case ceilings assume a perfectly documented chart; real yields are lower.
- CT.gov criteria are split on top-level bullets; nested sub-items are folded into their parent.

# Avicenna hospital-side matcher — design

**Version:** `avicenna.matcher/0.1` (draft design, not yet implemented)
**Date:** 2026-10-17
**Scope:** The deterministic, hospital-local component that evaluates a patient packet against a trial `CriteriaPack` and emits per-criterion results plus a trial-level triage.
**Related:** `TRIAL_DATA_STANDARD.md` (CriteriaPack / atoms), `PATIENT_MATCHING_FORMAT_STANDARD.md` (patient packet / Facts), `PROPOSAL_TRIAL_DATA_STANDARD.md` (hardness rationale).
**Grounding:** Design validated against real registry criteria, incl. CTIS `2022-500237-92-00` (DLBCL) and CT.gov `NCT06382948` (ER+/HER2− breast).

---

## 1. Core stance

The matcher is a **deterministic, three-valued, set-based evaluator** — not a scorer and not an LLM. All natural-language interpretation happened upstream during atomization; the matcher's entire value is that it is **reproducible and explainable**: identical inputs + `policy_version` ⇒ identical output, and every result traces to patient `fact_id`s and verbatim criterion `source_text`.

| The matcher IS | The matcher is NOT |
|---|---|
| A K3 (Kleene) logic engine over `{TRUE, FALSE, UNKNOWN}` | A weighted score of "bullets met" |
| A set/interval comparison engine | A scalar `==`/`<` comparison engine |
| A fail-closed decision maker (uncertainty → unresolved) | A gap-filler (uncertainty → guess) |
| Deterministic and side-effect-free | A caller of networks, clocks, or models at runtime |

### The one principle under everything

> **The matcher never promotes uncertainty into a decision.** Structural breakage → error (upstream bug). Missing / ambiguous / unsupported / out-of-scope evidence → `UNKNOWN` → unresolved. A hard pass or fail is produced **only** from explicit, in-scope, typed, context-complete evidence.

Every rule below is a special case of this principle.

---

## 2. Inputs and the input contract

The matcher is handed exactly three things:

1. **CriteriaPack `P`** — the complete evaluable gate for each arm it declares.
2. **Patient packet `Q`** — structurally valid per the packet schema.
3. **Evaluation context** — temporal anchor, mode, `policy_version`, and trial/site context (site country, `study_type`).

"Self-contained, non-null" is the precondition the matcher relies on, and two words must never be conflated:

- **Non-null** = object and required fields are *present and well-formed*. It does **not** mean "known": a field may hold `unknown`/`null` with a reason code — that is data, not a defect.
- **Self-contained** = every predicate is fully evaluable from `Q` + context, with **zero** external references. Anything needing outside text arrived upstream as an `opaque_text` atom.

Upstream owns two concerns the matcher therefore assumes away: **(A)** trials with no criteria never reach the matcher as a pack (they are catalog/relevance-only), and **(B)** packs built from partial public text carry `criteria_completeness`, which the matcher honors (§7) but does not re-derive.

### 2.1 Assumptions (preconditions) A1–A9

- **A1 — Pre-validated structure.** `P` and `Q` passed schema validation first. The matcher does not defensively re-parse; a structural violation is assert-and-abort, not an eligibility outcome.
- **A2 — Non-null ≠ known.** Missing *values* are `UNKNOWN`; only missing/malformed *structure* is an error.
- **A3 — No dangling references.** Every predicate resolves from packet + context alone. Deferred / tabular / unparseable / foreign-language prose was converted upstream to `opaque_text` → `manual_review`. The matcher never holds a reference it cannot follow.
- **A4 — Typed, registered concepts only.** Every atom carries a `type` and `system/code` from the vocabulary the matcher knows; out-of-registry concepts were flagged `unsupported` upstream. This is what makes the engine domain-neutral — a NIHSS, Wagner, or CHILD-Pugh threshold compares exactly like an ANC threshold.
- **A5 — Normalized, comparable values.** Quantities carry unit + `normalization_status`; the matcher compares validated-unit to validated-unit (or identical original unit) only. Unmapped/unsupported units → `UNKNOWN`, never coerced. Scales (ECOG/Karnofsky) are never interconverted. Ages are typed values; `age_group` bands are an **unordered set**.
- **A6 — Open-world by default.** Absence of a fact ⇒ `UNKNOWN`. A negative is established only by an `explicit_negative` fact or a coverage-backed `not_exists` (§5.4). An inclusion-only pack means "no exclusions *in scope*"; completeness is encoded upstream, not inferred here.
- **A7 — Arm scope is explicit.** Each criterion/atom declares `arm_scope` (null = whole trial). The matcher evaluates **per declared arm** and never mixes atoms across arms.
- **A8 — Context is supplied, never inferred.** Site country, `study_type`, and the anchor are inputs. Absent required context ⇒ dependent predicate `UNKNOWN`.
- **A9 — Deterministic, no side effects.** No network, no LLM, no clock beyond the provided anchor; identical inputs + `policy_version` ⇒ identical output.

---

## 3. Evaluation algebra

### 3.1 Three-valued logic (K3)

Atom and criterion results live in `{TRUE, FALSE, UNKNOWN}`. Error-like resolutions (`UNSUPPORTED`, `STALE`, `CONFLICT`) collapse to `UNKNOWN` carrying a reason code. Folding uses Kleene strong logic:

- `all` (AND): `FALSE` if any `FALSE`; else `UNKNOWN` if any `UNKNOWN`; else `TRUE`.
- `any` (OR): `TRUE` if any `TRUE`; else `UNKNOWN` if any `UNKNOWN`; else `FALSE`.
- `not`: swaps `TRUE`/`FALSE`; `UNKNOWN` is fixed.

**Consequence (the flood-relief rule falls out for free):** an `any` with one `TRUE` branch is `TRUE` regardless of unknown siblings, so unresolved alternatives are discharged automatically. We do not need a bespoke coverage rule — the matcher simply *is* K3.

### 3.2 Set-based comparison

Patient values are intervals, generalized bands, and inequalities, never clean scalars. Every comparison is between a patient **set** `S` and a predicate **region** `R`:

- `TRUE` iff `S ⊆ R` (wholly satisfies),
- `FALSE` iff `S ∩ R = ∅` (wholly fails),
- `UNKNOWN` iff `S` straddles the boundary of `R`.

Worked: an age band `[60,64]` against "≥ 18" → `TRUE`; against "≤ 62" → `UNKNOWN`; against "≤ 50" → `FALSE`. Quantity comparators (`lt/le/gt/ge`) and inequality-valued labs use the same rule.

---

## 4. Evidence resolution (before evaluation)

Packets carry repeated, dated, and conflicting Facts, so before any predicate runs the matcher must decide **which Facts feed it**. This is the `policy_version`-governed resolution policy. Its output per atom is a feeding Fact set + a resolution state (`resolved | missing | stale | conflict | unsupported`) that either feeds evaluation or short-circuits it to `UNKNOWN`. The steps run in order; the first that yields `not_applicable` or a short-circuit wins.

### 4.0 Order of operations

```text
applicability → subject/assertion filter → time compatibility → precision check
            → aggregation by time-relation → authority/recency selection → conflict
```

### 4.1 Applicability (can this criterion even apply?)

A criterion is **`not_applicable`** (removed from numerator *and* denominator, §8.3) when a structured gate makes it moot for this patient × arm — e.g. a WOCBP/pregnancy criterion for a patient whose `administrative_gender` is male *with appropriate evidence*, or an arm-specific atom for an arm not under evaluation. Applicability MUST rest on explicit evidence, never on inference from age/gender alone (A8); when the gating fact is itself `unknown`, the criterion is **applicable and `UNKNOWN`**, not `not_applicable`.

### 4.2 Subject and assertion filter

`subject_scope = patient` only — family/other never satisfy a patient predicate. `rejected` and `suspected` Facts, and `uncertain`-subject Facts, cannot establish a hard `TRUE`/`FALSE`; they are visible context only.

### 4.3 Time compatibility

A Fact's `effective_time` must be compatible with the anchor and the atom's `time_window.relation`. **Null anchor ⇒ anchor-relative predicates → `stale`→`UNKNOWN`, never satisfied.** `shifted_demo` time is evaluated only within the same patient's shifted basis and never compared to real deadlines; cross-basis comparison → `UNKNOWN`.

**Real-mode anchor (aligned with the patient packet):** the matcher never defaults a null anchor to today, `generated_at`, or an output timestamp. A caller MAY explicitly supply evaluation time as a labeled pre-screen approximation using compatible unshifted evidence; true screening-date anchoring remains a separate review step. No runtime clock is read by the evaluator. Packet and separately supplied context anchors/modes/policy versions MUST agree; disagreement is a structural validation error, not a silent override.

### 4.4 Precision check

If a Fact's time or value precision is coarser than the predicate needs (e.g. `precision: "year"` against a within-21-days window, or an age band against a single-year cutoff that falls inside the band), the atom is `unsupported`/`UNKNOWN` — the matcher never sharpens a value it was given coarse. (Set-based straddle, §3.2, already covers the value case; this is its time analogue.)

### 4.5 Aggregation by time-relation (which of several Facts?)

"Latest" is **not** a global rule — the aggregation mode is driven by the atom's `time_window.relation`:

| `relation` | Semantics | Fact set used |
|---|---|---|
| `any_history` / `ever` | existential ("has the patient ever…") | **all** compatible Facts; fold predicate with `any` (OR) |
| `current` / `at_screening` | point-in-time state | the **most-recent** compatible Fact; authority only tie-breaks among contemporaneous Facts (§4.6) |
| `within_days_before_anchor` | windowed | all Facts inside the window; relation-appropriate fold |

This is why a "history of grade ≥3 toxicity" exclusion folds existentially while an "ECOG at screening" inclusion takes the latest — applying "latest" to the former would silently drop a disqualifying earlier event.

**Existence/non-existence asymmetry.** Existence is provable from a single compatible Fact, but **non-existence is not provable from absence** under an incomplete history. A `not_exists`/negative predicate over `any_history` yields `TRUE` only with an explicit completeness or `explicit_negative` signal, else `UNKNOWN` (§5.4). [EU-agent feedback: treating assessed history as complete produces false "absent" results.]

### 4.6 Authority and recency selection

**Recency dominates for point-in-time state; authority only breaks ties.** For a `current`/`at_screening` predicate the matcher selects the **most-recent** compatible Fact. A more recent value that disagrees with an older one reflects **change over time**, not a conflict to overrule — a stale but "authoritative" (reviewed/structured) value MUST NOT override a fresher one (e.g. a reviewed ECOG 0 from six months ago never overrides a recent ECOG 3). Authority — `verification_status` (`reviewed` > `source_assertion` > `extracted_candidate`), then `source_kind` (structured/lab > administration/prescription > narrative) — breaks ties **only among contemporaneous Facts** (same effective time within precision). For existential (`any_history`/`ever`) relations recency is irrelevant; authority instead governs whether a single asserting Fact is trustworthy enough to establish existence.

[Corrected per EU-agent feedback: the prior "authority, then recency" ordering could select a stale authoritative value over current evidence for a point-in-time predicate.]

**Recency bound for screening state.** "Most recent" is not "current" when the most recent value is years old. For the screening-state keys (`performance.status`, `lab.result`, `cardiac.qtc`, `cardiac.lvef`, `safety.pregnant`, `safety.pregnancy_test`), a `current`/`at_screening` read must be bounded:
- by the atom's `window_days` (from the protocol text);
- else by the caller's site policy `screening_recency_days[fact_key]` (reported in result `notes`);
- else the predicate is `UNKNOWN` (`recency_unbounded`).

A bounded read needs an anchor. Existential relations are not bounded. Applicability gates and guards on these keys use the same bound.

**Snapshot keys.** `demographics.age` and `demographics.administrative_gender` are single-valued snapshots, so only point relations apply. Existential or windowed relations are `UNKNOWN` (`relation_unsupported_for_key`). Otherwise "age < 18" and ¬("age ≥ 18") would fold differently: ∃ age < 18 is not the negation of ∃ age ≥ 18.

Age is projected to the anchor. A completed-years band [lo, hi] stated at effective time E becomes [lo + ⌊Δmin⌋, hi + ⌈Δmax⌉] at anchor A, where Δ is the elapsed time in years between the extents of E and A.
- If E or A is unknown, only [lo, ∞) survives (age is non-decreasing and screening does not precede the record).
- In `historical_review` mode the anchor may precede the record, so the predicate is `UNKNOWN`.

[Added per the sanitized strong-candidate findings: an encoding-dependent age exclusion; a stale age passing an upper age limit.]

**Assay/specimen groups.** For `biomarker.result`, recency orders results only *within* one assay/specimen group (`qualifiers.assay`, `qualifiers.specimen_ref`). Results on different assays or specimens are different tests, not change over time.
- If the latest results of the groups agree, they answer.
- If they disagree, the predicate is `UNKNOWN` (`assay_discordant`).
- An atom's `assay` list restricts evidence to the named assays (exact match).

[Added per the sanitized manual-pilot findings: document-local scores are not screening-current; differing specimen/assay results are not interchangeable.]

### 4.7 Conflict (explicit and runtime)

- **Explicit:** a `conflict` Fact supersedes its own alternative arms; those arms MUST NOT independently establish a hard outcome until a documented review rule resolves them.
- **Runtime:** if two **contemporaneous** Facts (equal recency within precision) of **equal authority** disagree for a `current`-relation predicate, the matcher raises a conflict itself → `conflict`→`UNKNOWN`. Disagreement a clear recency difference resolves (newer = current state, §4.6) or authority breaks among contemporaneous Facts is *not* flagged.

### 4.8 Policy versioning

`policy_version` bumps whenever any of §4.1–4.7 or the §8 thresholds (`manual_review` ratio, coverage denominator rules) change. A result is reproducible only against its stated `policy_version`; two results with different policy versions are not comparable.

---

## 5. Predicate constructs the atoms must support

Real criteria require four constructs beyond a flat typed threshold. Where the current `CriteriaPack` grammar lacks them, these are **requirements fed back to the trial standard** (§10); without them the affected criteria must degrade upstream to `opaque_text`.

### 5.1 Relative-to-reference thresholds
`NCT06382948 #14`: *"total bilirubin < 1.5 × ULN."* The bound is relative to the **patient's own** reference. Rule: evaluable only if the reference (e.g. `qualifiers.reference_high`) rides on the Fact; absent it → `UNKNOWN`. The matcher MUST NOT assume a standard ULN.

### 5.2 Derived values
`NCT06382948 #14c`: *"estimated creatinine clearance ≥ 50 mL/min by Cockcroft-Gault."* A derivation is a separate derived Fact with its own provenance and inputs; the matcher MUST NOT compute it from guessed demographics at runtime. If an `any`-sibling (serum creatinine ≤ 1.5 × ULN) is `TRUE`, K3 discharges the missing CrCl.

### 5.3 Guarded / conditional predicates
`DLBCL #IPI`: *"IPI 3–5 (for > 60) **or** aaIPI 2–3 (for ≤ 60)"*; `NCT06382948 #14`: *"AST ≤ 1.5 × ULN (≤ 3 × ULN in patients with liver metastases)."* Needs `when <guard> then A else B`.

When the guard is known, take the selected branch. **When the guard is `UNKNOWN`, evaluate all reachable branches and apply supervaluation over the guard:** the result is `TRUE` iff *every* admissible guard resolution yields `TRUE`, `FALSE` iff every one yields `FALSE`, else `UNKNOWN` (equivalently: branches agree → that result; disagree or any branch `UNKNOWN` → `UNKNOWN`). Consequence: the guard fact is only required in the genuinely ambiguous band — when the strict branch passes or the loose branch fails, the criterion resolves cleanly without it (e.g. AST wholly ≤ 1.5 × ULN → `TRUE` regardless of liver-mets status; wholly > 3 × ULN → `FALSE` regardless; between → `UNKNOWN`, guard genuinely needed). This is the same "never promote uncertainty" principle applied to the guard.

### 5.4 Coverage-aware `not_exists`
`NCT06382948 #9`: *"No prior elacestrant or other SERDs for advanced disease"* — an inclusion whose predicate is `not_exists(SERD, setting=advanced)`. **The dangerous false-pass case.** `not_exists` returns `TRUE` only with a **positive, criterion-scoped signal of absence**:

1. a criterion-scoped `explicit_negative` Fact, or
2. a `coverage.completeness` assertion whose **scope subsumes the criterion's scope**:
   - **concepts**: asserted agents/classes ⊇ the criterion's queried agents/classes, tested via **validated, versioned concept membership** (e.g. `agent ∈ class` from a pinned ontology version). An **unknown or unvalidated mapping is `UNKNOWN`** — never assumed member or non-member.
   - **setting**: asserted disease + treatment setting is compatible with and covers the criterion's;
   - **time**: asserted window covers the criterion's — and a `bounded` export/review window **never** satisfies a `lifetime` criterion (a complete last-2-years list cannot clear "no prior therapy ever").

    The assertion's `method` MUST be **reviewed reconciliation backed by an authorized reviewer or an approved validated process with auditable provenance** — extraction and ingestion can never self-certify it, however "complete" they are.

    The typed Scope, registry versions, cutoff/time basis and authorization objects are defined in `PATIENT_MATCHING_FORMAT_STANDARD.md` v1.1.0. Completeness is not itself a negative fact: a confirmed qualifying exposure makes `not_exists` FALSE, and contradictory/ambiguously scoped exposure prevents TRUE. Use explicit `scoped_absence` Facts for documented therapy negatives. Missing scope/authorization cannot be fabricated during migration. Fact `assertion = null` means no assertion, never criterion non-applicability.

Mere presence in `assessed_fact_keys` is **not** a signal; "assessed" means *looked at*, not *complete history*. Absent a subsuming signal → `UNKNOWN`. "No matching fact" is never "absent." [EU-agent feedback.]

**The conservatism is bounded to absence/negation.** It does not make trials unevaluable: positive evidence, measured thresholds, and sufficient `any`-branches (§3.1) still resolve without exhaustive history — e.g. `NCT06382948 #14c` clears on the creatinine branch alone, and a *found* prior-therapy Fact satisfies a "must have received X" inclusion regardless of completeness. Only predicates that must prove *non-existence* require the scoped signal.

---

## 6. Per-criterion outcome (polarity + hardness)

Fold a criterion's atoms (K3 + §5 constructs) to `predicate_state ∈ {TRUE, FALSE, UNKNOWN}`, then apply polarity (by `kind`) and `hardness`:

`hardness ∈ {hard, procedural_pre_screen}` — **there is no `soft`.** A corpus scan of all 1,621 CTIS criteria found no genuine soft eligibility preference; "preferably / should / where possible" language (118 occurrences) always decorated a hard or procedural requirement. Softness is a *relevance*-axis concept (geo, condition proximity) on the TrialCard, never an eligibility atom. Removing the value also removes the temptation to demote an awkward hard criterion to stop it blocking.

| `kind` | `predicate_state` | Hardness | Outcome |
|---|---|---|---|
| inclusion | TRUE | any | satisfied |
| inclusion | FALSE | hard | **resolved disqualifier** |
| inclusion | UNKNOWN | any | unresolved |
| exclusion | TRUE | hard | **resolved disqualifier** (exclusion triggered) |
| exclusion | FALSE | any | clear |
| exclusion | UNKNOWN | any | unresolved |
| any | any | `procedural_pre_screen` | unresolved, **non-blocking** at pre-screen |

Polarity is implied by `kind` (no separate field). `procedural_pre_screen` (consent, willingness, investigator judgment) is never a disqualifier at pre-screen and is carried as visible-but-non-blocking.

---

## 7. The three matcher behaviors (C, E, F)

After the input contract discharges the other weird-trial classes, only three require genuine matcher behavior:

### 7.1 Per-arm evaluation (C)
The matcher evaluates each declared `arm_scope` independently and emits **per-arm verdicts**; it never folds atoms across arms. Trial-level relevance = "eligible for ≥ 1 arm." Whole-trial atoms (`arm_scope = null`) apply to every arm.

### 7.2 Study-type-aware candidacy (E)
The matcher reads `study_type` from context. Healthy-volunteer trials invert disease logic (inclusion = *absence* of significant disease). Observational / analytical studies are **not treatment candidacy** and MUST be labeled as such, not ranked beside interventional trials. Disease-relevance shortlisting MUST NOT be applied to healthy-volunteer trials as if disease presence were required.

### 7.3 Jurisdiction-keyed guards (F)
A guard (§5.3) may key on **site country**, not only a patient Fact — e.g. *"≥ 50 or ≥ 55 (for Czech Republic)"*, *"age limit may be higher if legally required."* For a Motol (CZ) patient the CZ-specific bound applies; absent site context, the dependent predicate → `UNKNOWN`.

### 7.4 Dual-source trials (CTIS + CT.gov)
A trial linked across registries may carry two packs (`TRIAL_DATA_STANDARD.md` §3 crosswalk + pack `linked_packs`). The matcher follows the pack's `criteria_policy`:
- `sole_source` → evaluate this pack only.
- `prefer_ctis_principal` / `prefer_ctgov` → evaluate the **preferred** pack for the verdict; the other is available for audit but not folded in.
- `keep_both_review` → evaluate **both** packs (via `linked_packs`) and surface a `source_conflict` flag with both results; the matcher MUST NOT merge or average them, and the arm's `eligibility_state` is the **more conservative** of the two (never silently pick the more favorable).

Determinism holds per `(pack_version, policy_version)` of each evaluated pack.

---

## 8. Trial-level outputs (three separate axes)

The matcher emits **three independent outputs**, never one score:

1. **`relevance`** — diagnosis/geo shortlist (`geo_rank`, condition match; embeddings allowed). **Never gates eligibility.** *Pilot scope (decision):* relevance = `geo_rank` + condition-code match only; embedding retrieval is deferred (its "never the sole gate" constraint keeps it off the critical path) and added only if catalog-only trials need better triage than geo+condition gives.
2. **`eligibility_state`:**
   - `ineligible` iff ≥ 1 **resolved** hard disqualifier (hard inclusion FALSE or hard exclusion TRUE) — resolved only, never from `UNKNOWN`;
   - else if every applicable hard criterion is **satisfied** (inclusion `TRUE` / exclusion `FALSE`, per the §6 outcome table — **not** predicate-`TRUE`, which for an exclusion means *triggered*), nothing hard is unresolved, **and** `criteria_completeness = complete` → `eligible_pending_review`;
     <br>[Corrected per EU-agent feedback: the prior "every hard criterion `TRUE`" wording wrongly required exclusions to be *triggered* to reach a positive.]
   - else `needs_chart_review` (a **data gap** — evaluation is sound, patient facts are missing; the chart likely resolves it);
   - `manual_review` (an **evaluation gap** — the criteria themselves are un-evaluable; a human must read the protocol text). The line is a `policy_version` knob, defaulting to **severity OR ratio**: severity = an un-evaluable **hard exclusion** (an `opaque_text`/`conflict` exclusion we cannot check is the dangerous false-pass direction — treat as forcing `manual_review`); ratio = (`opaque_text` + `conflict` + investigator-judgment) / applicable-hard-criteria > ⅓. An un-evaluable hard **inclusion** merely stays unresolved (→ `needs_chart_review`) and counts toward the ratio only. Individual un-evaluable criteria are **always** surfaced regardless of the arm-level label.
   - **Completeness cap:** `criteria_completeness = partial` caps the best achievable state at `needs_chart_review`, even if every visible atom passes.
3. **`evidence_coverage`** — resolved vs unresolved applicable criteria, **per arm**, computed **after** folding (so discharged unknowns don't count). Denominator = criteria applicable to this patient × arm after arm-scope and applicability filtering, **excluding** `procedural_pre_screen` and not-applicable criteria; the latter are tracked separately as "procedural outstanding." This is the ranking signal **among non-ineligible** trials.

Plus **`blocking_criteria[]`**: resolved hard disqualifiers + unresolved hard requirements, each with reason codes, `fact_refs`, and verbatim `source_text`.

Rank relevance separately from eligibility and coverage. A high relevance score MUST NOT conceal missing safety checks.

### 8.1 Shared result vocabulary (single normative source)

This subsection is the **one** definition of the matcher's I/O enums. `PATIENT_MATCHING_FORMAT_STANDARD.md` and `TRIAL_DATA_STANDARD.md` MUST reference it rather than restating it; the earlier divergences (`missing` vs `unknown`, `unsupported` vs `unsupported_unit`, "supported ineligibility" vs `ineligible`) are retired in favor of these.

- **`predicate_state`** (the folded truth value of a criterion): `true | false | unknown`.
- **`evaluation_state`** (why a criterion landed where it did): `evaluable` (resolved to true/false) · `missing` (required evidence absent) · `stale` (evidence time-incompatible with anchor/window) · `conflict` (contradictory evidence) · `unsupported` (unit/scale/concept not validated for comparison) · `not_applicable` (out of scope for this patient × arm) · `opaque` (arrived as `opaque_text`) · `manual_review` (needs human interpretation).
- **`eligibility_state`** (per arm and rolled up per trial): `ineligible | eligible_pending_review | needs_chart_review | manual_review`. **There is no bare `eligible`** — that is a post-human-review product state, never emitted by the matcher.
- **`reason_codes`**: a controlled, versioned registry. Unlike the enums above, unknown reason codes are **ignored, not fatal** (a new code must not break old consumers). Enums are closed and fatal; reason codes are an open controlled set.

### 8.2 Per-criterion result

```jsonc
{
  "criterion_id": "ctgov:NCT06382948:inclusion:14c",
  "arm_scope": null,
  "kind": "inclusion",                 // polarity
  "hardness": "hard",                  // hard | procedural_pre_screen
  "predicate_state": "unknown",        // true | false | unknown
  "evaluation_state": "missing",       // §8.1
  "outcome": "unresolved",             // satisfied | resolved_disqualifier | clear | unresolved | non_blocking | not_applicable
  "fact_refs": ["lab-creatinine-3"],   // patient fact_ids used
  "reason_codes": ["reference_range_absent"],
  "source_text": "Renal: Serum creatinine ≤ 1.5 × ULN or estimated creatinine clearance ≥ 50 mL/min…"
}
```

`source_text` is carried verbatim so the clinician sees *why*, not a score.

### 8.3 Per-arm and per-trial result

```jsonc
{
  "trial_uid": "ctgov:NCT06382948",
  "study_type": "interventional",
  "relevance": { "score": 0.0, "geo_rank": 1, "basis": ["condition", "geo"] },
  "best_eligibility_state": "needs_chart_review",   // rolled up across arms
  "pack_version": "20261017.1",
  "policy_version": "eval-policy-v1",
  "evaluated_at": "<local time; not sent to cloud>",
  "arms": [
    {
      "arm_scope": null,
      "eligibility_state": "needs_chart_review",
      "criteria_completeness": "complete",           // complete | partial (caps at needs_chart_review)
      "evidence_coverage": { "resolved": 17, "applicable": 19, "ratio": 0.89 },
      "blocking_criteria": ["ctgov:NCT06382948:inclusion:14c"],  // resolved hard disqualifiers + unresolved hard
      "procedural_outstanding": ["ctgov:NCT06382948:inclusion:1"] // consent/willingness, non-blocking
    }
  ]
}
```

`best_eligibility_state` rolls up across arms by precedence: any arm `eligible_pending_review` > `needs_chart_review` > `manual_review` > (all arms `ineligible`) `ineligible`. A trial is `ineligible` only when **every** arm is.

---

## 9. Pipeline

```text
1. Relevance shortlist (cheap: geo_rank + condition)            → candidate trials
2. Load active CriteriaPack per candidate (honor arm_scope, completeness)
3. Per atom: resolve applicable facts (§4) → set-based K3 eval (§3,§5) → atom_state
4. Fold atoms per criterion (K3 + guards + DAG refs)           → criterion predicate_state
5. Apply polarity + hardness (§6)                              → per-criterion outcome
6. Aggregate per arm (§7.1) → eligibility_state, coverage, blocking[]
7. Apply study-type semantics (§7.2); attach explanations (reason_codes, fact_refs, source_text)
```

Cross-criterion references (`TRIAL_DATA_STANDARD.md` §6.4.5; e.g. `NCT06382948 #14d` → exclusion 16) make the pack a **DAG**: evaluate in dependency order; the matcher MUST detect and refuse cycles.

---

## 10. Requirements fed back to the trial standard

The matcher can only be as good as the atoms it is handed. Status vs `TRIAL_DATA_STANDARD.md` **v1.3**:

| # | Requirement | Status |
|---|-------------|--------|
| 1 | Vocabulary beyond oncology; engine vs grammar (`scored_instrument`, …) | Adopted §6.5 |
| 2 | Four predicate constructs (§5) + cross-criterion DAG | Adopted §6.4 |
| 3 | `criteria_completeness` on every pack | Adopted (pack field) |
| 4 | Acyclic cross-criterion refs | Adopted §6.4.5 |
| 5 | Drop `soft` hardness | Adopted |
| 6 | `study_type` + per-criterion `arm_scope` | Adopted |
| 7 | `not_exists` absence_scope / subsumption (not `assessed_fact_keys`) | Adopted §6.4.4 (v1.3) |
| 8 | `criteria_policy` on pack for dual-source §7.4 | Adopted (pack field, v1.3) |

Criteria whose logic exceeds the available constructs MUST degrade to `opaque_text` + `needs_review` upstream, never to a wrong atom graph.

---

## 11. Worked trace — `NCT06382948 #14c` (renal)

> *"Renal: Serum creatinine ≤ 1.5 × ULN **or** estimated creatinine clearance ≥ 50 mL/min as calculated by Cockcroft-Gault equation."*

- Criterion: `kind = inclusion`, `hardness = hard`, `logic.op = any`.
- Atom α: `lab.result` creatinine, relative threshold `≤ 1.5 × ULN` (§5.1).
- Atom β: derived `organ_function` CrCl `≥ 50 mL/min`, Cockcroft-Gault (§5.2).

Evaluation of three illustrative (non-real) patient states:

| Patient state (illustrative) | α | β | criterion (`any`) | outcome |
|---|---|---|---|---|
| creatinine present **with** local ULN, wholly ≤ 1.5 × ULN | TRUE | — | TRUE | satisfied (β discharged) |
| creatinine present but **no** reference range; no CrCl Fact | UNKNOWN (§5.1) | UNKNOWN | UNKNOWN | unresolved → `needs_chart_review` |
| creatinine wholly > 1.5 × ULN; CrCl derived Fact = 60 | FALSE | TRUE | TRUE | satisfied |
| creatinine > 1.5 × ULN; no CrCl Fact | FALSE | UNKNOWN | UNKNOWN | unresolved (not ineligible — never from unknown) |

Note the last row: a failed sub-threshold with an unknown alternative is **unresolved, not a disqualifier** — the hard-inclusion-FALSE disqualifier fires only when the *folded criterion* is FALSE.

---

## 12. The matcher MUST NOT

- Compute a single eligibility score from "bullets met."
- Turn `UNKNOWN` into pass or fail.
- Coerce units or interconvert scales (Karnofsky ↔ ECOG).
- Use family-history, suspected, or rejected evidence for a hard outcome.
- Treat "no matching fact" as a negative (§5.4).
- Call an LLM, fetch anything remote, or read a clock other than the provided anchor.
- Compare shifted-demo dates to real screening deadlines.
- Report `eligible_pending_review` when `criteria_completeness = partial`.

---

## 13. Open questions

1. **Guard combination when the guard is `UNKNOWN`** — *resolved:* supervaluation over the guard (§5.3). The guard fact is required only in the ambiguous band.
2. **Soft outcomes** — *resolved:* `soft` dropped; `hardness ∈ {hard, procedural_pre_screen}` (§6). Corpus scan confirmed no genuine soft eligibility criterion. **Fed back:** `TRIAL_DATA_STANDARD.md` v1.2 removes `soft`, adds `criteria_completeness` / `study_type` / `arm_scope`, and §6.4 constructs required by §5 / §10.
3. **`manual_review` threshold** — *resolved:* severity-OR-ratio>⅓, `policy_version`-tunable (§8).
4. **Coverage denominator** — *resolved:* per-arm, post-filter, excluding `procedural_pre_screen` and n/a (§8).
5. **Trial-standard sync** — *resolved:* pack fields and atom grammar aligned in `TRIAL_DATA_STANDARD.md` v1.3 (incl. §5.4 `not_exists` / `criteria_policy`); this doc remains normative for result enums (§8.1) and absence evaluation (§5.4).
6. **Correctness fixes (EU-agent feedback, patient-data validated):** *resolved* — (a) `eligible_pending_review` requires each hard criterion *satisfied*, not predicate-`TRUE` (§8.2); (b) recency dominates authority for point-in-time state (§4.6); (c) absence resolves only from scoped `explicit_negative` or reviewed-reconciliation completeness that subsumes the criterion (§5.4), with validated versioned concept membership and reviewer/approved-process provenance; `completeness` defaults empty and extraction cannot self-certify.
7. **Launch impact on `eligible_pending_review`** — *unmeasured.* Empty-by-default completeness blocks absence-from-silence, so the auto-positive set depends on reviewed-reconciliation coverage for priority (Motol/Homolka) trials; size to be measured, not assumed.

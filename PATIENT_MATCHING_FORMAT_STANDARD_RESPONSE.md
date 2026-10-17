# Response: review of the patient matching packet standard

**Responds to:** `PATIENT_MATCHING_FORMAT_STANDARD.md` (`avicenna.patient-packet/1.0.0`, proposed)
**Status:** Reviewer response — opinions and recommended normative changes
**Date:** 2026-10-17
**Reviewer scope:** Read against the patient packet spec and its two sibling standards (`TRIAL_DATA_STANDARD.md` v1.1, `PROPOSAL_TRIAL_DATA_STANDARD.md`). No access to real patient data; review is of the contract, not of any instance.

---

## 1. Overall verdict

**Approve with changes.** The data model is sound and the safety posture is correct: *absence is never negative, unknown never auto-resolves.* This is the patient-side mirror of the trial standard's "unknown ≠ satisfied," and it is threaded consistently. The spec already encodes the one invariant that matters most — a hard inclusion false or hard exclusion true may establish ineligibility, but **unknown required evidence leads to unresolved review, never to pass or rejection** (§"Matching semantics"). That is the rule the trial-side proposal had to add explicitly; here it was right the first time.

The required work is **harmonization and a few correctness holes, not redesign.** None of the findings below change the architecture.

---

## 2. What should not change

These are load-bearing and correct; please preserve them through any revision:

1. **The five-state Fact model** (`known / unknown / not_tested / indeterminate / conflict`) with "no record is not evidence of not-tested." This is the distinction naive extractors collapse, and collapsing it is how patients get wrongly cleared or excluded.
2. **No "latest truth" overwrite** — separate observations retained, resolution deferred to a versioned matcher policy. Consistent with L0 immutability on the trial side.
3. **Time basis and `shifted_demo` rules** — shifted timestamps never compared to real deadlines; null anchor never defaults to today; cross-patient shifted dates share no chronology. This is the subtlest part of the spec and it is right.
4. **UCUM `normalization_status` with no silent conversion**, and no silent Karnofsky→ECOG. Same no-coercion discipline as the trial-side unit handling.
5. **Honest `approved_eu_processor` provenance** — a packet extracted via an external endpoint is explicitly incompatible with a zero-egress claim. Keep this candor; it is what makes the privacy section credible.

---

## 3. Priority findings and recommended changes

### P1 — Define the matcher output vocabulary once, shared with the trial standard (highest priority)

The matcher consumes **both** this packet and the trial `CriteriaPack`, but the two specs define the shared result vocabulary twice, slightly differently:

| Concept | This spec | Trial standard |
|---|---|---|
| per-criterion resolution | `evaluation_state ∈ {evaluable, missing, stale, conflict, unsupported, manual_review}` | atoms → `unknown \| conflict \| stale \| unsupported_unit → unresolved` |
| unmet-because-absent | `missing` | `unknown` |
| unit problem | `unsupported` | `unsupported_unit` |
| supported ineligibility | "supported ineligibility" (prose) | `eligibility_state = ineligible` |

These are near-synonyms that **will diverge** as each document evolves independently.

**Recommendation (MUST before Phase B schemas):** lift the matcher output contract — `predicate_state`, `evaluation_state`, `eligibility_state`, `reason_codes` — into a single normative definition (either a short shared doc or one spec that the other references). Neither standard should restate the enum.

### P2 — Constrain `state` × `assertion` (validator gap)

`assertion` is Required on every Fact, but the state rules never constrain it by state. The synthetic example sets an `unknown` performance-status fact to `assertion: not_applicable`, which reads as filler — an unknown fact has no assertion to characterize. Validation rule #2 checks state/value/missing_reason but **not** state/assertion.

**Recommendation:** add a normative `state × assertion` compatibility table, and extend acceptance rule #2 to enforce it. At minimum specify what `assertion` must be when `state ∈ {unknown, not_tested, indeterminate, conflict}`.

### P3 — Close the `conflict` / alternatives double-count (safety)

A `conflict` fact has `value = null` and points to ≥2 alternative facts. Those alternatives are themselves Facts, presumably `known` with real values. Nothing currently forbids the matcher from satisfying a predicate off **one arm of an acknowledged conflict**.

**Recommendation (MUST):** when a `conflict` fact exists for a key, its alternative facts MUST NOT independently establish a hard pass/fail. The conflict node supersedes its arms for hard-outcome purposes until a documented review rule resolves it.

### P4 — Add an explicit therapy-exclusion false-pass guard (safety)

§vocabulary already warns that a generic unknown lab/biomarker slot does not prove every analyte was assessed. The identical, higher-stakes trap on `therapy.event` is unstated: **absence of a `parp_inhibitor` (or any class) event among assessed therapy facts does NOT establish "no prior PARP inhibitor."** For an exclusion this is the false-*pass* direction — the most dangerous one in oncology matching.

**Recommendation:** add a sentence parallel to the lab caveat: a therapy class/agent not appearing among assessed `therapy.event` facts is `unknown` for an exclusion predicate, not `explicit_negative`, unless explicit negative evidence or review supports absence.

### P5 — Disambiguate the two meanings of "coverage"

Packet `coverage` means *did we assess this key* (assessed/unassessed). Trial-side `evidence_coverage` means *evaluable vs unresolved*. Same word, orthogonal axis: a key can be "assessed" here while every fact under it is `unknown/indeterminate/conflict`.

**Recommendation:** state explicitly that packet-`coverage` is "looked-at" (asserted by the extractor) and matcher-`evidence_coverage` is "evaluable" (computed downstream, post-logic-fold). Consider renaming one to remove the collision.

### P6 — Reconcile minimum coverage with the hard safety gates

Minimum coverage slots omit `safety.pregnant` / `wocbp` / `pregnancy_test`, `disease.recist_measurable`, and `cardiac.*` — yet the matching-semantics section insists RECIST / washout / pregnancy are legitimately **hard**. A packet can therefore be "complete per minimum coverage" while silent on exactly the criteria most likely to gate. They will correctly surface as unknown→unresolved (safe), but as a "did we look" checklist the baseline undercuts the hardness story — and it is inconsistent with the trial standard's instruction not to default pregnancy/RECIST to soft.

**Recommendation:** either add the safety slots to minimum coverage, or state explicitly that they are trial-contract-driven rather than baseline — and make that choice match the trial standard.

### P7 — Reconcile open-ended codes with the strict-enum stance

The spec is emphatic that unknown enum values MUST fail validation, but `warnings` and `reason_codes` are "controlled codes" with no closed list or registry pointer.

**Recommendation:** name where the code registry lives, and state the asymmetry explicitly — unknown *enum* values are fatal; unknown *warning/reason* codes MUST be ignored-not-fatal, so a new code does not break existing consumers.

### P8 — State the null-anchor timing consequence

§envelope forbids defaulting a null anchor to today (good) but does not say what happens to washout/recency predicates when `anchor = null`.

**Recommendation:** make it normative — a null anchor ⇒ anchor-relative timing predicates evaluate to `unknown`, never satisfied. This mirrors the trial-side `time_window` rule.

### P9 (minor) — Explain the two representations of generalization

Age generalization is modeled as `state = known` + interval + `generalization.applied = true`, yet `missing_reason = generalized` also exists under `state = unknown`. The distinction (value widened-but-preserved vs value suppressed) is defensible but unexplained.

**Recommendation:** one sentence stating when each form applies, so extractors do not choose arbitrarily.

---

## 4. Answers to the questions this spec implies

- **Is a local-model extraction + clinician-review packet an acceptable contract?** Yes, provided the privacy boundary holds as written and P3/P4 are closed — those are the two places where a plausible-looking packet could feed a false hard outcome.
- **Is the shifted-demo time model safe for a hackathon demo?** Yes. It is the strongest part of the spec. Keep `absolute_screening_recency_allowed = false` wired to `shifted_demo` as a MUST.
- **Is this ready to freeze at schema v1?** Not until P1 and P2 are resolved, because both are seams a JSON Schema and a validator must encode. P3–P8 can be normative prose in v1 with tests; P9 is editorial.

---

## 5. Bottom line

The model is right and the safety invariants are right — this spec is closer to correct than its trial-side sibling was at the same stage. The real risk is **vocabulary drift at the matcher seam** (P1, P5, and the `ineligible` wording), because the packet and the `CriteriaPack` define the matcher's shared language twice. Fix that seam first; then close the two concrete correctness holes (P3 conflict arms, P4 therapy exclusions) that neither a schema validator nor a reviewer can currently catch. Everything else is tightening.

---

## 6. Suggested next step

Draft a single normative **matcher I/O vocabulary** section (predicate/evaluation/eligibility states + reason-code registry policy) that both this spec and `TRIAL_DATA_STANDARD.md` reference instead of restating. That one change resolves P1, P5, and the terminology half of P6/P7 at once.

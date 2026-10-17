# Build plan — Avicenna hospital-side matcher

**Implements:** `MATCHER_DESIGN.md` (`avicenna.matcher/0.1`)
**Consumes:** `TRIAL_DATA_STANDARD.md` v1.3 (CriteriaPack/atoms), `PATIENT_MATCHING_FORMAT_STANDARD.md` v1.1 (patient packet)
**Date:** 2026-10-17
**Status:** plan — no matcher code yet.

---

## 0. Objective and non-goals

**Objective:** a deterministic, offline Python library + CLI that takes a validated `CriteriaPack` + patient packet + evaluation context and emits the §8 result objects, implementing the design exactly — including its MUST-NOTs.

**Non-goals (owned elsewhere, do not build here):** atomization/LLM structuring (upstream), patient extraction, relevance embeddings (deferred, §8), the clinical-reviewer loop, any UI. The matcher is the *evaluator* only.

**Hard constraints (from the design, enforced in code and CI):**
- **Deterministic + offline:** no network, no LLM, no `datetime.now()`/clock read in the evaluator. Anchor comes from input only (A9, §12).
- **Fail-closed:** `UNKNOWN` never becomes pass/fail (the §1 principle).
- **No patient data in the repo:** fixtures are synthetic only; real patient packets never committed, logged, or printed.

---

## 1. Stack and layout

Match the repo: **Python ≥ 3.12**, `uv run --script` style, stdlib-first (+ `jsonschema` for validation only), `pytest` for tests (`test_*.py`), SQLite for trial data.

```
matcher/
  avicenna_matcher/
    __init__.py
    types.py          # dataclasses + enums (TriState, EvaluationState, EligibilityState, Outcome)
    errors.py         # StructuralError (A1) vs evaluation UNKNOWN — never conflated
    tristate.py       # §3.1 K3 logic
    sets.py           # §3.2 interval/band/inequality set algebra + compare
    concepts.py       # §5.4 validated, versioned concept membership; unknown→UNKNOWN
    resolution.py     # §4 policy (applicability→…→conflict), policy_version-parameterised
    predicates.py     # §5 constructs: relative, derived-ref, guarded(supervaluation), not_exists(scoped)
    outcome.py        # §6 polarity + hardness → per-criterion outcome
    aggregate.py      # §8 eligibility_state, coverage, blocking[], manual_review rule, completeness cap, roll-up
    behaviors.py      # §7 per-arm, study_type, jurisdiction guard, dual-source
    explain.py        # reason_codes + fact_refs + verbatim source_text
    pipeline.py       # §9 orchestration
    cli.py            # evaluate(pack, packet, context) → result JSON (uv script entry)
  schemas/
    criteria_pack.schema.json
    patient_packet.schema.json
    criterion_result.schema.json
    trial_result.schema.json
    reason_codes.registry.json
  tests/
    fixtures/         # SYNTHETIC packs + packets only
    test_*.py
  tools/
    measure.py        # §7-plan corpus measurement harness (trial packs only)
  README.md
```

---

## 2. Build phases

Ordered by dependency; each phase has a **deliverable**, **design ref**, and **done = tests green**. Phases P0–P4 are the evaluable core; P5–P7 make it usable and measurable.

### P0 — Schemas + validator (the enforceable spec)
- **Deliverable:** JSON Schemas for pack, packet, and the two result objects; enums from §8.1 as closed/fatal; `reason_codes.registry.json` as an open set. A `validate(obj, kind)` that raises `StructuralError`.
- **Why first:** turns the design's "correct" claim into a machine check; `types.py` mirrors the schemas.
- **Done:** every §8.2/§8.3 example validates; the state×assertion table (`PATIENT_MATCHING_FORMAT_STANDARD.md`) and acyclic-ref constraint are schema- or load-checked; unknown enum → fail, unknown reason_code → pass.

### P1 — Evaluation algebra (pure, property-tested)
- **Deliverable:** `tristate.py` (K3 AND/OR/NOT) + `sets.py` (interval/band/inequality regions; `compare(S, R) → {TRUE,FALSE,UNKNOWN}` by ⊆ / ∩∅ / straddle).
- **Design ref:** §3.
- **Done:** property tests — K3 truth tables; `any` with one TRUE ⇒ TRUE regardless of UNKNOWN siblings (flood-relief, §3.1); the age-band worked example (§3.2); no scalar coercion path exists.

### P2 — Evidence resolution (`policy_version`-parameterised)
- **Deliverable:** `resolution.py` implementing §4.0 order: applicability → subject/assertion → time compat → precision → aggregation-by-relation → authority/recency → conflict. Returns `(feeding_facts, resolution_state)`.
- **Design ref:** §4. **Concepts registry** (`concepts.py`) stub with versioned membership + unknown→UNKNOWN.
- **Done (incl. the EU-feedback regressions):**
  - recency dominates authority for `current`/`at_screening`; stale reviewed value does **not** override fresh (§4.6);
  - `any_history`/`ever` folds existentially; `latest` not applied to history (§4.5);
  - null anchor ⇒ anchor-relative → UNKNOWN; shifted-demo never vs real deadlines (§4.3);
  - coarse precision ⇒ UNKNOWN (§4.4);
  - conflict node supersedes arms; runtime conflict only for contemporaneous equal-authority disagreement (§4.7).

### P3 — Predicate constructs
- **Deliverable:** `predicates.py` — relative-to-reference thresholds (§5.1), derived-value refs (evaluate derived Fact, never compute — §5.2), guarded `cases` with **supervaluation** over UNKNOWN guard (§5.3), coverage-aware `not_exists` with **scoped subsumption** (concepts⊇ via versioned membership, setting-covers, time-covers; bounded≠lifetime; reviewed-reconciliation provenance required) (§5.4).
- **Done:** guard resolves without the guard fact in the unambiguous band (AST example); `not_exists` TRUE only on scoped `explicit_negative` or subsuming reviewed completeness; unknown concept mapping ⇒ UNKNOWN; bounded window never clears lifetime criterion.

### P4 — Outcome + aggregation
- **Deliverable:** `outcome.py` (§6 polarity+hardness; no `soft`) + `aggregate.py` (§8 eligibility_state, per-arm `evidence_coverage`, `blocking_criteria[]`, `manual_review` severity-OR-ratio, completeness cap, roll-up precedence).
- **Done (incl. the polarity-bug regression):** `eligible_pending_review` requires each hard criterion **satisfied** (inclusion TRUE / exclusion FALSE), never predicate-TRUE (§8.2); ineligible only from a **resolved** disqualifier; partial completeness caps at `needs_chart_review`; coverage excludes procedural + n/a; trial `ineligible` only when every arm is.

### P5 — Matcher behaviors
- **Deliverable:** `behaviors.py` — per-arm evaluation (C), study-type candidacy incl. healthy-volunteer inversion (E), jurisdiction-keyed guards via site context (F), dual-source `criteria_policy` with conservative `keep_both_review` (§7.4).
- **Done:** per-arm verdicts don't mix atoms; observational/healthy-volunteer labeled not-candidacy; CZ bound selected for CZ site; `keep_both_review` yields the more conservative state + `source_conflict`.

### P6 — Pipeline + CLI + explanations
- **Deliverable:** `pipeline.py` (§9 steps), `explain.py` (reason_codes + fact_refs + verbatim source_text on every result), `cli.py` (`uv run` entry: pack + packet + context JSON → trial_result JSON, schema-validated in and out).
- **Done:** §9 end-to-end produces §8.3 objects; DAG cross-refs evaluated in dependency order, cycles refused; every criterion result carries its `source_text`.

### P7 — Corpus measurement harness (closes the design's unmeasured gaps)
- **Deliverable:** `tools/measure.py` over real **trial** packs (CTIS/CT.gov SQLite — never patient data): reports **construct coverage** (% criteria evaluable vs `opaque_text`), `opaque`/`manual_review` rates, and — against **synthetic** packets — the `eligible_pending_review` yield sensitivity to `completeness`.
- **Done:** a one-page report answering §13.7 (launch impact) and the §10.2 question "how many real criteria the four constructs actually cover."

---

## 3. Test strategy

- **Property tests** (P1): K3 and set algebra invariants; the master invariant *UNKNOWN never yields a hard outcome* asserted across random inputs.
- **Golden fixtures** (P2–P6): synthetic pack×packet → expected trial_result, incl. the §11 renal trace as a fixture.
- **Regression suite — the four patient-data-validated bugs** (each a named test):
  1. cleared hard exclusion (predicate FALSE) contributes to positive;
  2. stale reviewed fact does **not** override recent lower-authority fact;
  3. `assessed`-not-`complete` therapy ⇒ `not_exists` UNKNOWN; bounded window ≠ lifetime;
  4. unknown concept mapping ⇒ UNKNOWN.
- **Acceptance fixtures** from `PATIENT_MATCHING_FORMAT_STANDARD.md` §validation (age straddle, polarity, units, shifted-date, etc.).
- **Determinism + offline CI gate:** test asserting no socket and no `datetime.now` reachable from the evaluator; same inputs + `policy_version` → byte-identical output twice.

---

## 4. Dependencies and risks

- **Blocking input — atomizer:** P3 constructs need packs that actually carry §6.4 atoms. Until the atomizer emits them, test on hand-authored synthetic packs and measure `opaque_text` fallback rate in P7.
- **Concept registry (P2/P3):** `concepts.py` needs a validated, versioned membership source (ATC/avicenna). Ship a small pinned seed for pilot specialties (onc + cardio/resp/renal-metabolic, per the §6.5 decision); unknown mappings correctly degrade to UNKNOWN, so partial coverage is safe.
- **Completeness data:** `not_exists` clears need reviewed-reconciliation assertions that don't exist yet; default-empty means auto-positive yield is low until they do (§13.7) — P7 quantifies, does not assume.

---

## 5. Milestones

| M | Scope | Gate |
|---|-------|------|
| M1 | P0+P1 | schemas validate design examples; algebra property-tested |
| M2 | P2+P3 | resolution + constructs green, incl. all four regressions |
| M3 | P4+P5 | full per-arm verdicts + behaviors on synthetic trials |
| M4 | P6 | CLI end-to-end, explainable output, DAG+cycle handling |
| M5 | P7 | corpus construct-coverage + eligible-yield report |

M1–M4 make the matcher **work and be trustworthy**; M5 is what moves the design from "defensible" to "measured" — the point the design review flagged as the real remaining gap.

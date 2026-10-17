# Matcher implementation — fixes before M2

**Target:** `matcher/` (`avicenna.matcher/0.1`), currently at **M1** (P0 schemas + P1 algebra, 90 tests green).
**Against:** `MATCHER_DESIGN.md` (normative; §8.1 is the single result-vocabulary source), `TRIAL_DATA_STANDARD.md` v1.3, `PATIENT_MATCHING_FORMAT_STANDARD.md` v1.1.
**Date:** 2026-10-17

## Summary

The M1 code is clean and well-tested, but it was generated against an **earlier draft of the design** — before the §8.1 vocabulary unification, the `soft` drop, the `polarity` drop, and the EU-feedback fixes. The result: schemas + `types.py` enforce the *wrong* vocabulary, which defeats the point of the P0 "schemas = enforceable spec." Plus one real evaluation bug in `sets.py`. All are cheap to fix at M1 and expensive after M2 builds resolution/predicates/aggregation on top.

**Fix order:** F1 and F2 are blocking for M2. F3–F6 are same-sitting cleanups.

---

## F1 — Result-vocabulary drift from §8.1 (HIGH, blocking)

Schemas and `types.py` predate the unified §8.1 vocabulary and the `soft`/`polarity` drops. Correct every occurrence below, then add the pin-test in F1a so it cannot recur.

| Field | Where | Current (wrong) | Required (§ref) |
|---|---|---|---|
| `eligibility_state` | `trial_result.schema.json`, `types.py:EligibilityState` | `eligible`, `eligible_pending_review`, `ineligible`, `needs_chart_review`, `undetermined` | `ineligible`, `eligible_pending_review`, `needs_chart_review`, `manual_review` — **no bare `eligible`** (post-review product state, never emitted); no `undetermined` (§8.1) |
| `evaluation_state` | `criterion_result.schema.json`, `trial_result.schema.json`, `types.py:EvaluationState` | `resolved`, `missing`, `stale`, `conflict`, `unsupported`, `not_applicable` | `evaluable`, `missing`, `stale`, `conflict`, `unsupported`, `not_applicable`, **`opaque`**, **`manual_review`** (`resolved`→`evaluable`) (§8.1) |
| `outcome` | `criterion_result.schema.json`, `trial_result.schema.json`, `types.py:Outcome` | `pass`, `fail`, `unknown` | `satisfied`, `resolved_disqualifier`, `clear`, `unresolved`, `non_blocking`, `not_applicable` (§8.2) |
| `hardness` | `criteria_pack.schema.json`, `criterion_result`, `trial_result`, `types.py:Hardness` | `hard`, `soft` | `hard`, `procedural_pre_screen` — **`soft` dropped** (§6) |
| `assertion` | `patient_packet.schema.json`, `types.py:FactAssertion` | `positive`, `explicit_negative`, `suspected`, `historical` | add **`not_applicable`**; enforce the state×assertion table (`PATIENT_MATCHING_FORMAT_STANDARD.md`) |
| `normalization_status` | `patient_packet.schema.json` (quantity), `types.py:Quantity` | `normalized`, `original`, `unknown` | `validated`, `unmapped`, `unsupported` (packet typed-values; A5/§5.1 depend on these names) |

Also reconcile the completeness object: schema `assertion_type: {explicit_negative, reviewed_comprehensive}` should match the design's `method: reviewed_reconciliation` + scoped-subsumption fields (concepts/setting/time, reviewer, provenance). Full alignment can wait for P3, but **rename now** so the two don't diverge further.

### F1a — Pin the §8.1 vocabulary with one test (prevents recurrence)

Add `tests/test_vocab_contract.py` that asserts the enum sets in the schemas **and** `types.py` equal the §8.1/§8.2/§6 sets exactly (literal expected lists in the test). This is the guard P0 was supposed to be; without it, drift silently returns.

---

## F2 — Strict vs non-strict inequality bug in `sets.py` (HIGH, blocking)

`Interval` has no open/closed flag, so `lt`≡`le` and `gt`≡`ge`. A value exactly at a strict threshold is wrong:

```
x < 1.5, x = 1.5  -> TRUE   (must be FALSE)
x > 1.5, x = 1.5  -> TRUE   (must be FALSE)
```

Lab gates ("bilirubin < 1.5×ULN", "ANC ≥ 1.5") put real patients exactly on the boundary, and the packet already carries `lower_inclusive`/`upper_inclusive` (and `BandValue` mirrors them) — the model drops them.

**Fix:** give `Interval` `start_inclusive`/`end_inclusive` bounds. Map `lt`/`gt` → open bound, `le`/`ge` → closed; honor the packet's inclusivity flags for patient bands. Update `contains`/`subset_of`/`intersects` to respect open/closed at the boundary.

**Tests:** the four boundary cases above, plus an open-band vs closed-threshold straddle (patient `(1.5, 2.0]` vs `≤ 1.5` → FALSE; vs `< 1.6` → UNKNOWN).

---

## F3 — Stale `polarity` field in the pack schema (MED)

`criteria_pack.schema.json` has `polarity: {positive, negative}` on the atom. `TRIAL_DATA_STANDARD.md` **dropped atom `polarity`** (v1.1) — polarity is implied by `criterion.kind`. Remove the field (or, if kept transitionally, mark it ignored and never read it in evaluation).

---

## F4 — `tristate` docstring claims unimplemented behavior (LOW)

`k3_and`/`k3_or` docstrings say they "also accept a single sequence argument" — they do not; `k3_and([TRUE, FALSE])` would compare a list to an enum and wrongly return `TRUE`. Either implement the sequence overload or delete the claim and route sequence callers through `k3_all`/`k3_any` (which already exist).

---

## F5 — Packaging blocks the `uv` workflow (LOW)

`uv run pytest` fails to build the package (setuptools flat-layout discovery error) and silently falls back to bare `pytest`. Fix `pyproject.toml` — set `[tool.setuptools] packages = ["avicenna_matcher"]` or adopt `src/` layout — so the repo's `uv run --script` convention works and CI is reproducible.

---

## F6 — Verify `schema_version` consts (LOW)

Confirm the `const` strings match the standards' current versions: `patient_packet` declares `avicenna.patient-packet/1.1.0`; the format standard header should agree. Fix whichever is stale; don't leave two numbers.

---

## Acceptance for "ready for M2"

- [ ] F1 vocab corrected in all 5 schemas + `types.py`; F1a pin-test green.
- [ ] F2 interval inclusivity implemented; boundary tests green.
- [ ] F3 `polarity` removed/neutralized.
- [ ] F4 docstring/overload reconciled.
- [ ] F5 `uv run pytest` builds and passes.
- [ ] Existing 90 tests still green; no new network/clock calls (determinism gate from the build plan).

## Root cause note

The drift is a *snapshot* problem: code was written once against a moving design and not re-synced after the §8.1/`soft`/`polarity`/EU-feedback rounds. F1a (the vocabulary pin-test) is the durable fix — it makes the schemas fail loudly the next time the design and code disagree, which is exactly the enforcement P0 promised.

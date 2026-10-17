# Avicenna Hospital-Side Matcher

**Version:** `avicenna.matcher/0.1`  
**Status:** P0–P6 complete, plus review-2 fixes (436 tests passing, 4 xfailed). P7 harness and report done.

A deterministic, offline Python library that evaluates patient packets against trial `CriteriaPack` objects and emits per-criterion and trial-level eligibility results. Built on K3 (Kleene three-valued) logic, set-based comparisons, and fail-closed principles.

## Core Principles

1. **Deterministic + offline:** No network, no LLM, no `datetime.now()` in evaluation. Same inputs + `policy_version` → byte-identical output.
2. **Fail-closed:** `UNKNOWN` never becomes pass/fail. Structural errors → abort. Missing/ambiguous evidence → `UNKNOWN` → unresolved.
3. **No patient data in repo:** All fixtures are synthetic. Real patient packets never committed, logged, or printed.

## Build Phases

| Phase | Deliverable | Tests | Status |
|-------|---|---|---|
| **P0** | JSON schemas + validator | 30 | ✅ Done |
| **P1** | K3 algebra + set comparison | 60 | ✅ Done |
| **P2** | Evidence resolution (§4) | 23 | ✅ Done |
| **P3** | Predicate constructs (§5) | 19 | ✅ Done |
| **P4** | Outcome + aggregation (§6, §8) | 43 | ✅ Done |
| **P5** | Matcher behaviors (§7) | 24 | ✅ Done (healthy-volunteer inversion: documented gap) |
| **P6** | Pipeline + CLI + explanations | 87 | ✅ Done (see known gaps) |
| **R2** | Review-2 fixes: canonical adapter, time basis/precision, linkage, quantifier, completeness | 56 | ✅ Done (25/25 targeted mutants killed) |
| **P7** | Corpus measurement harness + report (`reports/P7_MEASUREMENT.md`) | 38 | ✅ Done |

### Running the matcher

```bash
python -m avicenna_matcher PACK.json PACKET.json [--context CTX.json] --generated-at 2026-03-01T12:00:00Z
```

`--generated-at` is required (the matcher never reads a clock). `--result-id` defaults to a
sha256 of the canonical inputs, so identical inputs give byte-identical output. Inputs and the
output are schema-validated; structural errors exit 2 with a JSON error on stderr.
Context may carry `site_context` (e.g. `{"country": "CZ"}`) and `authorization_policy`. It may also carry `anchor`/`mode`/`policy_version`; if present, these must agree with the packet's `evaluation_context`.

### Packets: canonical vs internal
- **Canonical** `avicenna.patient-packet/1.1.0` (PATIENT_MATCHING_FORMAT_STANDARD.md) is accepted directly. `adapter.py` translates it, loss-aware, into the internal `avicenna.matcher-packet/1.0.0`. Each loss is listed in the result `notes`.
- The adapter never invents precision, absence, completeness or authorization:
  - reduced-precision times keep `precision` and `time_basis`;
  - intervals and inequalities become *superset* integer bands;
  - `stage` becomes `indeterminate`. A numeric `scored_instrument` maps to a band in its own unit (`{ECOG}`, `{Karnofsky}`) only under the pinned `avicenna-instruments/1.0.0` registry; scale, step and grid are checked; ordinal or unregistered instruments become `indeterminate`. A `biomarker` maps its `marker` to `Fact.concept` and its `result` to the value;
  - unexpected fields are rejected.
- `coverage.completeness` is used only if its `authorization` matches the `authorization_policy` (`policy_version`, `human_reviewers`, `approved_processes`) that the caller supplies in context. A coverage that is otherwise valid is still discarded if:
  - its chronology is incompatible;
  - its lifetime cutoff does not reach the anchor;
  - its disease scope is a referenced disease;
  - it covers a single setting and the query is setting-agnostic.

### Time semantics
- A reduced-precision time denotes its whole unit.
- Different or `unknown` time bases are never compared (`time_basis_incompatible`).
- A fact that may or may not fall inside the anchor or window is UNKNOWN (`time_precision_insufficient`).
- "Latest": recency wins at the facts' real precision. Authority decides only between facts that are genuinely contemporaneous.
- Screening-state keys need a recency bound for point reads (`current`/`at_screening`). The keys are
  `performance.status`, `lab.result`, `cardiac.qtc`, `cardiac.lvef`, `safety.pregnant` and `safety.pregnancy_test`.
  - The bound is the atom's `window_days`, else the caller's site policy (context key
    `screening_recency_days: {fact_key: days}`, reported in `notes`).
  - With neither, the result is `recency_unbounded`. A years-old ECOG never stands for "now".
  - Existential relations (`ever`) are unaffected.
- `demographics.age` and `demographics.administrative_gender` are snapshots. Existential or windowed relations on
  them → `relation_unsupported_for_key`, so "age <18" and not("age ≥18") give the same answer.
  - Age is projected to the anchor. Completed age at the anchor is [lo + ⌊Δmin⌋, hi + ⌈Δmax⌉] for the elapsed
    time Δ, so a stale "74" cannot pass "≤ 75".
  - With an untimed age or no anchor, only the lower bound survives (age never decreases). In `historical_review`,
    nothing survives.
- Biomarker point reads select the latest result **per assay/specimen group** (`qualifiers.assay`, `specimen_ref`).
  - A newer result on a different assay or specimen does not supersede an older one; groups that disagree →
    `assay_discordant`.
  - An atom may restrict the acceptable assays with `assay: [...]` (exact match; a fact with an unstated assay is not
    evidence).
- `within_days_before_anchor` requires `quantifier` ∈ {`exists`, `latest`}; without it the result is `window_quantifier_unspecified`.
- `shifted_demo` cannot allow absolute recency. Non-real-time modes are labelled in `notes`.

### Demo
`python matcher/tools/mock_patient_demo.py` runs fictional patients against 3 public CT.gov trials that a developer hand-atomized (not an atomizer output).

### Builder prompts
These prompts are for the people and models that produce the matcher's inputs. Both share one terminology binding: codes are matched exactly, so a mismatch leaves a criterion unresolved.
- `prompts/TRIAL_PACK_BUILDER_PROMPT.md`: turns public eligibility text into `avicenna.criteria-pack/0.1`.
- `prompts/PATIENT_PACKET_BUILDER_PROMPT.md`: turns source records into canonical 1.1.0. Use it only inside the authorized boundary.

### MCP server (`avicenna_mcp`)
The matcher is packaged as an MCP server (stdio) together with three skills.

```bash
cd matcher && uv sync --extra mcp
uv run avicenna-mcp                     # serve over stdio (registered in ../opencode.json as `avicenna-trials`)
uv run avicenna-mcp build-catalog       # (re)index data/ctgov + data/ctis → data/catalog/trial_catalog.sqlite
uv run avicenna-mcp search "colorectal KRAS"
uv run avicenna-mcp screen skills/patient-data-format/example_packet.json
```

| Tool | Purpose |
|---|---|
| `search_trials` | FTS search over currently available CT.gov + CTIS trials with Czech sites (Motol/Prague first; filters: recruiting, registry, phase, geo, age, sex) |
| `screen_patient` | reuses the search (default query = the packet's ICD-10 diagnosis), evaluates each hit, returns `excluded` (hard criterion resolved against the patient, with the verbatim reason) and `can_apply` (sorted by probability) |
| `match_trial` | one patient × one trial: state, criteria met / disqualifying / to check, probability factors, optional full TrialResult |
| `get_trial`, `catalog_info` | public trial record with verbatim criteria; catalog metadata/rebuild |
| `validate_patient_packet`, `validate_criteria_pack` | structural checks exactly as the matcher applies them |
| `get_criteria_pack`, `save_criteria_pack`, `list_curated_packs` | curated packs in `matcher/packs/<trial_id>.json` override the automatic registry pack |
| `list_skills`, `get_skill` | skill text for clients without native skill support |

Skills (`matcher/skills/`, symlinked into `.agents/skills/`, also MCP prompts and `avicenna://skills/<name>` resources):
`patient-data-format`, `trial-data-format`, `explain-trial-to-patient`. Schemas and builder prompts are served as
`avicenna://schemas/{name}` and `avicenna://docs/{trial-pack-builder|patient-packet-builder}`.

Trials without a curated pack get a **registry pack**. It has structured CT.gov age (complete), CTIS age groups and sex
(`partial`, which can never exclude), and every bullet kept verbatim as an opaque criterion. As a result, registry trials
are ruled out only by age and otherwise land in `manual_review`.

**Probability** (`avicenna-prob-heuristic/0.1`, `avicenna_mcp/probability.py`) is a separate, *uncalibrated* ranking
heuristic. It is not part of the matcher verdict, and `eligibility_state` remains authoritative. The heuristic blends
per-criterion priors for unresolved criteria with a base rate, weighting by how many hard criteria were resolved. It then
applies penalties for a sex or age-group mismatch, a diagnosis not named by the trial, and CTIS principal-only or
unpublished criteria. Confidence is `low` for registry packs.

Paths can be overridden with `AVICENNA_CTGOV_DB`, `AVICENNA_CTIS_DB`, `AVICENNA_CATALOG_DB`, `AVICENNA_PACKS_DIR` and
`AVICENNA_SKILLS_DIR`.

### Known gaps (all fail-closed)
- Healthy-volunteer inversion (§7.2) is not implemented; it is waiting on a schema flag. Non-interventional arms are noted in the result.
- The adapter does not interpret `stage` values (→ indeterminate), ordinal instruments, or therapy line, timing or response.
- Atoms on the generic keys `biomarker.result` and `lab.result` must carry `concept`; without it they are unresolved (`concept_unspecified`).
- On `disease.condition` and `safety.condition`, the coded value is the condition's identity. Only facts about the queried code(s) are evidence, and `ne` is refused (absence of a code is never a negative). An explicit negative clears only an `eq` query on the identical code. There is no code hierarchy, so sets must be listed exactly.
- Agent→class membership exists only for the small seed registry. Any positive therapy whose agents or classes are not registered against the queried concepts leaves a `not_exists` unresolved (`exposure_membership_unknown`), e.g. palbociclib vs "no prior chemotherapy".
- Only `administration`/`review` therapy evidence counts as an exposure; a prescription alone → unresolved.
- An explicit negative at time *t* does not prove absence across a whole window. Windowed `exists` therefore clears only through all-explicit-negative evidence.
- There is no specimen-*type* constraint on atoms: the canonical packet has `specimen_ref` (an id) but no specimen
  type, so "tissue-based test" stays opaque. Assay strings are matched verbatim and need a shared assay vocabulary.
- An organ-specific negative cannot be scoped on `disease.metastatic` (it is a bare Boolean). The packet builder must
  not emit `false` from organ-specific text. Engine-side scoping needs a standard change.
- Reference ranges need explicit linkage: either `reference_qualifier` on the same fact, or a paired `reference_key` fact sharing `qualifiers.specimen_ref` with no assay or concept disagreement.

### P0 — Schemas + Validator (Complete)
- ✅ JSON schemas for patient packet, criteria pack, criterion result, trial result
- ✅ State × assertion consistency table enforcement
- ✅ Duplicate fact_id detection, acyclic alternative fact references
- ✅ 30 tests: packet/pack/result schema validation, fact state rules

### P1 — Evaluation Algebra (Complete)
- ✅ `tristate.py`: K3 AND/OR/NOT logic (Kleene strong semantics)
- ✅ `sets.py`: Interval/band/inequality comparison (subset ⊆, disjoint, straddle)
- ✅ Flood-relief rule: `any()` with one TRUE → TRUE regardless of UNKNOWN siblings
- ✅ Worked example: age band [60,64] against various threshold predicates
- ✅ 60 tests: K3 truth tables, interval operations, master invariant (UNKNOWN never yields hard outcome)

## Architecture

```
matcher/
  avicenna_matcher/
    __init__.py              # Public API
    types.py                 # Enums: TriState, EvaluationState, EligibilityState, Outcome, etc.
    errors.py                # StructuralError vs evaluation UNKNOWN
    validator.py             # Schema validation + state×assertion checks
    tristate.py              # K3 logic (P1) ✅
    sets.py                  # Set-based comparison (P1) ✅
    concepts.py              # Versioned concept membership (P2)
    resolution.py            # §4 evidence resolution policy (P2)
    predicates.py            # §5 constructs (P3)
    outcome.py               # §6 polarity + hardness (P4)
    aggregate.py             # §8 eligibility_state roll-up (P4)
    behaviors.py             # §7 per-arm, study-type (P5)
    explain.py               # Reason codes + fact refs (P6)
    pipeline.py              # §9 DAG orchestration (P6)
    adapter.py               # canonical 1.1.0 packet → internal, loss-aware (R2)
    timing.py                # precision/time-basis spans (R2)
    cli.py                   # uv script entry (P6)
  schemas/
    patient_packet.schema.json       # internal avicenna.matcher-packet/1.0.0 (canonical enters via adapter)
    criteria_pack.schema.json        # §TRIAL_DATA_STANDARD
    criterion_result.schema.json     # §8.2 per-criterion result
    trial_result.schema.json         # §8.3 trial-level result
    reason_codes.registry.json       # Open set of reason codes
  tests/
    test_p0_schemas.py       # 30 tests ✅
    test_p1_algebra.py       # 60 tests ✅
    test_p2_resolution.py    # (coming)
    test_p3_predicates.py    # (coming)
    test_p4_outcome.py       # (coming)
    test_p5_behaviors.py     # (coming)
    test_p6_pipeline.py      # (coming)
    test_p7_measure.py       # 38 tests ✅
    test_review2_regressions.py  # 56 tests ✅ (design-oracle, mutation-checked)
    fixtures/
      synthetic_packs/       # Hand-authored test criteria packs
      synthetic_packets/     # Synthetic patient packets (never real data)
  tools/
    measure.py               # §7 corpus measurement (P7)
  pyproject.toml             # Python package config
  README.md                  # This file
```

## Running Tests

```bash
cd matcher

# Install dependencies
python -m pip install -e ".[dev]"

# Run all tests
python -m pytest tests/ -v

# Run specific phase
python -m pytest tests/test_p0_schemas.py -v
python -m pytest tests/test_p1_algebra.py -v

# Coverage
python -m pytest tests/ --cov=avicenna_matcher
```

## Design References

- **MATCHER_DESIGN.md:** Full design document (avicenna.matcher/0.1)
- **TRIAL_DATA_STANDARD.md:** CriteriaPack / atoms specification
- **PATIENT_MATCHING_FORMAT_STANDARD.md:** Patient packet schema
- **PROPOSAL_TRIAL_DATA_STANDARD.md:** Hardness rationale

## Key Concepts

### K3 Logic (§3.1)
Values live in `{TRUE, FALSE, UNKNOWN}` with Kleene strong semantics:
- `AND`: FALSE if any FALSE; else UNKNOWN if any UNKNOWN; else TRUE
- `OR`: TRUE if any TRUE; else UNKNOWN if any UNKNOWN; else FALSE (flood-relief)
- `NOT`: swaps TRUE/FALSE; UNKNOWN is fixed

### Set-Based Comparison (§3.2)
Patient values are intervals, bands, inequalities—never clean scalars. Comparison:
- **TRUE** iff patient set ⊆ predicate region (wholly satisfies)
- **FALSE** iff sets are disjoint (wholly fails)
- **UNKNOWN** iff sets straddle (ambiguous)

Example: age band [60,64] vs "≤ 62" → UNKNOWN (boundary crossing)

### Evidence Resolution (§4)
Before evaluation, resolve which facts feed predicates using a `policy_version`-governed order:
```
applicability → subject/assertion → time compat → precision
  → aggregation → authority/recency → conflict
```

### Predicates (§5)
- **Simple comparison:** fact vs threshold
- **Relative-to-reference:** fact vs another fact (±offset)
- **Derived value:** evaluate an expression, then compare
- **Guarded case:** supervaluation over UNKNOWN guard
- **not_exists:** scoped negative with reviewed-completeness subsumption

### Outcome & Aggregation (§6, §8)
- Polarity (inclusion/exclusion) + hardness (hard/soft) → outcome per criterion
- Roll-up: hard criteria must all satisfy for `eligible_pending_review`
- `manual_review` flagged by severity or incompleteness ratio
- `blocking_criteria[]` identify disqualifiers

## Test Strategy

- **Property tests (P1):** K3 truth tables, interval operations, master invariant
- **Golden fixtures (P2–P6):** Synthetic pack × packet → expected trial_result
- **Regression suite:** Four known bugs (cleared hard exclusion, stale reviewed fact, assessed-not-complete, unknown concept)
- **Acceptance fixtures:** Age straddle, polarity, units, shifted dates (from standard)
- **Determinism + offline CI gate:** Test asserting no socket/clock; byte-identical output on same inputs

## Hard Constraints (Enforced)

- ✅ **No patient data in repo:** Fixtures synthetic only
- ✅ **Deterministic + offline:** No network, no `datetime.now()` in evaluator
- ✅ **Structural vs evaluation errors:** Never conflated (assert-and-abort vs UNKNOWN)
- ✅ **Fail-closed:** Master invariant tested—UNKNOWN never yields hard outcome

## Development Notes

- **Blocking:** P3 constructs need atomizer-generated packs; test on hand-authored synthetic packs
- **Concept registry:** Ship pinned seed for pilot specialties; unknown mappings → UNKNOWN
- **Completeness data:** `not_exists` clears only via reviewed scoped absence or authorized reconciliation (none exist in real data yet); P7 quantifies the impact

## Future Milestones

- **M1** (P0+P1): Schemas validate; algebra property-tested ✅
- **M2** (P2+P3): Resolution + constructs green; all four regressions pass
- **M3** (P4+P5): Full per-arm verdicts + behaviors on synthetic trials
- **M4** (P6): CLI end-to-end, explainable output, DAG+cycle handling
- **M5** (P7): Corpus construct-coverage + eligible-yield report

---

**Design validated against:** CTIS `2022-500237-92-00` (DLBCL), CT.gov `NCT06382948` (ER+/HER2− breast)

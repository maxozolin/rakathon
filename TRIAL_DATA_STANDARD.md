# Trial data standard (Avicenna)

Version: **1.3** (proposed — not yet implemented in code)  
Scope: public registry / HTML / coordinator-derived **trial** content only.  
Out of scope: patient facts, scores, explanations (`PATIENT_MATCHING_DATA_NEEDS_RESPONSE.md`, `reports/GENERAL_DATA_GUIDE.md`).  
**Matcher contract:** evaluation semantics and result enums are normative in `MATCHER_DESIGN.md` (esp. §5.4, §6–§8); this document defines the CriteriaPack atoms the matcher consumes.

---

## 0. Do existing public formats fit?

| Format | Role for us | Enough for matching? |
|--------|-------------|----------------------|
| **CTIS public JSON** | **L0** EU source of truth | No — principal I/E are free-text paragraphs |
| **ClinicalTrials.gov API v2 / PRS** | **L0** global / Motol seed | No — `eligibilityCriteria` is one Markdown/text blob; only sex/age structured |
| **FHIR R4 ResearchStudy / EvidenceVariable** | Optional **future hospital export** of L1/L2 | Not published by CTIS/CT.gov; would be our mapping, not an ingest format |
| **CDISC / CTR XML / WHO ICTRP** | Not on our ingest path | No for hackathon matching |

**Decision:** Adopt **CTIS + CT.gov native payloads as L0**. Define Avicenna **L1 TrialCard** + **L2 CriteriaPack** as the working standard for catalog + matcher. Do not pretend registry JSON is eligibility-structured.

Current `data/ctis/ctis.sqlite` / `data/ctgov/ctgov.sqlite` are **transitional L0 projections**, not L1/L2.

---

## 1. Design goals

1. **Immutable source, mutable structure** — never overwrite registry text; LLM output is a derived layer with provenance.
2. **Push criteria into the hospital** — cloud may structure public I/E; hospital runs deterministic evaluation against local `PatientFact`s. No patient data in cloud structuring.
3. **Explicit polarity & unresolved** — inclusions/exclusions are predicates; unknown ≠ satisfied.
4. **Multi-source without silent merge** — CTIS, CT.gov, HTML, coordinator packs can link; conflicting criteria stay visible.
5. **LLM where prose is dense; code where fields are already structured.**
6. **Separate candidate relevance from eligibility** — geo/diagnosis shortlist ≠ “eligible.”

---

## 2. Architecture layers

```text
L0 RAW          CTIS / CT.gov / HTML / attachment bytes (append-only; native schemas)
L1 CATALOG      TrialCard — identity, status, conditions, sites, geo, demographics gates
L2 CRITERIA     CriteriaPack — versioned atoms for the hospital matcher
L3 INDEX        optional trial-only embeddings / search docs
```

| Layer | Built where | LLM? | Consumed by |
|-------|-------------|------|-------------|
| L0 | Cloud ingest | No | Audit, re-parse, L1 projectors |
| L1 | Cloud (deterministic from L0; LLM only for HTML/manual stubs) | Rare | UI catalog, geo rank, shortlist |
| L2 | Cloud (LLM + validators) → **exported pack** | Yes, public text only | Hospital matcher |
| L3 | Cloud OK for trial-only search; never patient-linked in cloud | Optional | Retrieval |

**Hospital import:** active `CriteriaPack` + slim `TrialCard` header (not full L0 dumps unless offline audit needs them).

```text
Avicenna cloud:  L0 → L1 → L2 (public criteria only)
                        ↓ versioned packs
Hospital:        local PatientFact/TherapyEvent → deterministic eval → UI
```

---

## 3. Identifiers

```text
trial_uid     = "{registry}:{native_id}"
              # ctis:2025-524202-15-00
              # ctgov:NCT06382948
              # html:linkos_koc:{stable_hash}
              # manual:{uuid}

criterion_id  = "{trial_uid}:{kind}:{seq}"
atom_id       = "{criterion_id}:{atom_seq}"   # atom_seq = a,b,c… or 1,2,3

pack_version  = "YYYYMMDD.N"                 # bump on atoms, prompt, or validator change
source_etag   = sha256(canonical eligibility source bytes + retrieved_at)
```

**Crosswalk** (separate object; never collapse two criteria sets into one without policy):

```jsonc
{
  "schema": "avicenna.trial_crosswalk.v1",
  "trial_uid": "ctis:2025-524202-15-00",
  "same_as": ["ctgov:NCT0…"],
  "eu_ct_id": "2025-524202-15-00",
  "nct_id": "NCT0…",
  "eudract_id": null,
  "confidence": "registry_secondary_id",  // registry_secondary_id | fuzzy_title | coordinator
  "criteria_policy": "prefer_ctis_principal"
  // prefer_ctis_principal | prefer_ctgov | keep_both_review | sole_source
}
```

**Default policy:** if EU CT id links CTIS↔CT.gov → `prefer_ctis_principal` for L2, keep CT.gov pack available under `same_as` for diff/review. If texts conflict → upgrade to `keep_both_review` (two packs, UI shows conflict). Never average atoms. Single-registry packs use `sole_source`.

Mirror the active policy onto each exported **CriteriaPack** as `criteria_policy` (§6) so the hospital matcher can apply `MATCHER_DESIGN.md` §7.4 without a separate crosswalk lookup.

---

## 4. L0 — Raw store (native formats)

```text
data/
  ctis/raw/{ct_number}/{retrieved_at}.json      # CTIS retrieve body as returned
  ctgov/raw/{nct_id}/{retrieved_at}.json        # CT.gov study JSON as returned
  trials_unstructured/raw/{source}/{date}/…
  trials_manual/raw/{date}_{org}/…
```

SQLite may mirror projections + full JSON; treat DB as cache. Durability = L0 files when practical.

**Rules:** append-only; `retrieved_at`, content hash; **no patient data**.

**Eligibility source pointers inside L0 (do not “fix” here):**

| Registry | Path to I/E text |
|----------|------------------|
| CTIS | `authorizedApplication.authorizedPartI.trialDetails.trialInformation.eligibilityCriteria.principalInclusionCriteria[]` / `principalExclusionCriteria[]` |
| CT.gov | `protocolSection.eligibilityModule.eligibilityCriteria` (split Inclusion/Exclusion headers deterministically) |

---

## 5. L1 — TrialCard (catalog)

Deterministic projection from L0 for CTIS/CT.gov. HTML/manual may use LLM → **TrialStub** then promote to TrialCard (`TRIALS_CATALOG_SOURCES.md`). No eligibility **atoms** on the card.

```jsonc
{
  "schema": "avicenna.trial_card.v1",
  "trial_uid": "ctis:2025-524202-15-00",
  "registry": "ctis",                 // ctis | ctgov | html | manual
  "native_id": "2025-524202-15-00",
  "ids": {
    "eu_ct_id": "2025-524202-15-00",
    "nct_id": null,
    "eudract_id": null,
    "acronym": "GCT1184-07"
  },
  "titles": {
    "short": "…",
    "public": "…",
    "official": null
  },
  "status": {
    "registry_status": "Authorised",  // native string/code preserved
    "normalized": "authorised",
    // normalised enum: authorised | recruiting | active_not_recruiting |
    //   completed | withdrawn | unknown
    "recruiting_for_new": null,       // true|false|unknown — registry-wide guess only
    "site_recruiting": null,          // unknown until site/arm confirmed
    "as_of": "2026-10-16T12:00:00Z"
  },
  "phase": {
    "raw": "Therapeutic exploratory (Phase II)",
    "normalized": ["II"]
  },
  "conditions": [
    {
      "text": "Recurrent platinum-sensitive ovarian cancer",
      "meddra": [{"pt": "…", "code": "…"}],
      "codes": []
    }
  ],
  "interventions": [{"name": "…", "role": "experimental"}],
  "demographics_gate": {
    // ONLY fields present as structured registry fields — not inferred from I/E prose
    "sex": "female",                  // female | male | all | unknown
    "age_min_years": null,            // often null on CTIS (only coarse age_group)
    "age_max_years": null,
    "age_raw": "18-64 years, 65+ years",
    "age_precision": "band"           // exact | band | unknown
  },
  "eligibility_preview": {
    // optional: verbatim lists for UI before L2 exists; not for scoring
    "inclusions": ["…"],
    "exclusions": ["…"]
  },
  "sites": [
    {
      "country": "CZ",
      "city": "Prague",
      "org": "…Motol…",
      "org_norm": "fn_motol",
      "geo_rank": 1,
      "site_status": null
    }
  ],
  "geo_rank_best": 1,
  "sponsors": [{"name": "…", "type": "…"}],
  "active_pack": {
    "pack_version": "20261017.1",     // null if L2 not built yet
    "criteria_origin": "ctis_principal"
  },
  "source": {
    "retrieved_at": "…",
    "raw_ref": "ctis/raw/…",
    "api": "ctis-retrieve"
  },
  "public_registry": true
}
```

### Geo rank (relevance preference — not automatic ineligibility)

| Rank | Meaning |
|------|---------|
| 1 | FN Motol / Homolka (Prague) |
| 2 | Other Prague |
| 3 | Brno / Ostrava |
| 4 | Rest of Czechia |
| 5 | Other EU |
| 6 | Non-EU / unknown |

Unknown site willingness ≠ refusal. `active_not_recruiting` ⇒ treat `recruiting_for_new` as false unless site-level evidence says otherwise.

### TrialStub → TrialCard

HTML/coordinator LLM output (`TrialStub` in `TRIALS_CATALOG_SOURCES.md`) is an **ingest DTO**. Map into TrialCard + raw `eligibility_preview` / criterion `source_text` lines; then run the same L2 atomizer. Do not keep a third long-lived schema.

---

## 6. L2 — CriteriaPack (matcher contract)

**Canonical hospital import** for eligibility evaluation. Version independently of TrialCard.

```jsonc
{
  "schema": "avicenna.criteria_pack.v1",
  "trial_uid": "ctis:2025-524202-15-00",
  "pack_version": "20261017.1",
  "criteria_completeness": "complete",
  // complete | partial — set by retrieval/filler; partial caps matcher at needs_chart_review
  // (MATCHER_DESIGN.md §8). Partial = public principal text only / truncated source / known gaps.
  "study_type": "interventional",
  // interventional | observational | expanded_access | healthy_volunteer | unknown
  // Copied into evaluation context (MATCHER_DESIGN.md §7.2); do not rank observational as treatment.
  "criteria_policy": "prefer_ctis_principal",
  // prefer_ctis_principal | prefer_ctgov | keep_both_review | sole_source
  // Dual-registry: same values as crosswalk (§3). Matcher §7.4 reads this from the pack
  // (or the active pack's crosswalk row). sole_source = no linked alternate pack.
  "linked_packs": [],
  // optional: [{ "trial_uid": "ctgov:NCT…", "pack_version": "…", "role": "alternate" }]
  // when criteria_policy = keep_both_review, matcher evaluates both and takes conservative state.
  "source": {
    "registry": "ctis",
    "native_id": "2025-524202-15-00",
    "criteria_origin": "ctis_principal",
    // ctis_principal | ctgov_eligibility | html_llm | coordinator | protocol_pdf
    "retrieved_at": "…",
    "source_etag": "sha256:…",
    "language": "en"
  },
  "arm_scope": null,
  // Pack-level default; null = whole trial. Per-criterion/atom may override.
  // Else { "arm_id": "…", "label": "…" }
  "structuring": {
    "method": "llm+validate",
    // deterministic | llm+validate | human
    "model": "gpt-6-1-sol-dz-eu",
    "prompt_version": "criteria_atoms.v3",
    "structured_at": "…",
    "validator_version": "rules.v2",
    "review_status": "auto_passed"
    // auto_passed | needs_human_review | human_approved
  },
  "criteria": [ /* Criterion */ ]
}
```

Pack payload fields required by `reports/GENERAL_DATA_GUIDE.md`: trial id/version, criterion ids, inclusion/exclusion kind, vocabulary, operator, threshold/unit, time-window semantics, required evidence, unsupported/needs-review flags — covered by Criterion/Atom below plus `criteria_completeness`, `study_type`, and `criteria_policy`.

### 6.1 Criterion

One registry bullet / paragraph (or coordinator row). `source_text` is **verbatim** and authoritative.

```jsonc
{
  "criterion_id": "ctis:2025-524202-15-00:inclusion:2",
  "kind": "inclusion",                 // inclusion | exclusion
  "seq": 2,
  "arm_scope": null,                   // null = pack default / whole trial; else arm id
  "source_text": "Participant must have documented recurrence…",
  "logic": {
    "op": "all",                       // all | any | not | custom
    "notes": null                      // custom ⇒ human_approved required
  },
  "atoms": [ /* Atom */ ],
  "split_confidence": 0.0,
  "needs_review": false,
  "review_flags": []
  // boolean_ambiguous | exception_clause | arm_unclear | threshold_ungrounded | …
}
```

**Boolean safety:** “except if…”, unsafe “and/or”, or nested conditions the atomizer cannot encode with §6.4 constructs → `needs_review: true` and prefer a single `opaque_text` atom over a wrong split. Prefer `guarded` / `any`+siblings over opaque when the split is faithful.

### 6.2 Atom

Predicate evaluated hospital-side against `PatientFact` / `TherapyEvent`.

```jsonc
{
  "atom_id": "ctis:2025-524202-15-00:inclusion:2:a",
  "type": "prior_therapy",
  "predicate": {
    "op": "gte",
    // eq|neq|in|not_in|gte|lte|between|exists|not_exists|matches|opaque
    "concept": {
      "system": "avicenna",
      // avicenna | meddra | snomed | atc | loinc | local
      "code": "prior_platinum_lines",
      "display": "Prior platinum-containing regimens (count)"
    },
    "value": 1,
    "value_high": null,
    "unit": null,
    "unit_system": null,               // e.g. UCUM when known
    "qualifiers": {
      "disease_setting": "advanced",
      "agent_classes": ["platinum"],
      "exceptions": []
    },
    "time_window": {
      "relation": "any_history",
      // any_history | within_days_before_anchor | after_event | unknown
      "days": null,
      "anchor": "evaluation_time"
      // hospital chooses shifted_patient_local vs real screening anchor
    }
  },
  "arm_scope": null,
  "hardness": "hard",
  // hard | procedural_pre_screen  — soft is NOT permitted (v1.2)
  "required_patient_facts": ["prior_therapy"],
  "evaluation_notes": "Count distinct platinum-containing advanced-disease regimens.",
  "unsupported": false,
  "llm_confidence": 0.0
}
```

Polarity is **implied by `criterion.kind`** (no separate `polarity` field).

#### Hardness

`hardness ∈ {hard, procedural_pre_screen}` only. **`soft` is removed** (corpus scan + `MATCHER_DESIGN.md` §6 / §13.2). Softness belongs on TrialCard **relevance** (geo, condition proximity), never on an eligibility atom — it must not become a place to hide washout/RECIST/pregnancy.

| `hardness` | Meaning | Missing patient evidence |
|------------|---------|--------------------------|
| `hard` | Protocol gate (incl. washout, RECIST/measurable disease, pregnancy **when stated as eligibility**) | Criterion outcome `unresolved` → contributes to `needs_chart_review`; **never** auto-pass and **never** alone yields `ineligible` |
| `procedural_pre_screen` | ICF, pure willingness, investigator judgment | Visible, **non-blocking** at pre-screen; excluded from coverage denominator; must not depress rank (`MATCHER_DESIGN.md` §6, §8) |

Do **not** demote hard criteria because patient extracts are sparse — triage by **evidence coverage after K3 fold**, not by weakening gates (`PROPOSAL_TRIAL_DATA_STANDARD.md` §4.7).

#### Evaluation (hospital; normative in matcher)

**Do not restate result enums here.** Normative I/O vocabulary is `MATCHER_DESIGN.md` §8.1:

```text
eligibility_state ∈ { ineligible | eligible_pending_review | needs_chart_review | manual_review }
# no bare "eligible" from the matcher
# ineligible ⇔ ≥1 resolved hard disqualifier only (never from UNKNOWN)
```

Summary aligned with the matcher:

```text
K3 fold (all/any/not) over atoms → predicate_state ∈ {TRUE, FALSE, UNKNOWN}
inclusion FALSE (hard) or exclusion TRUE (hard) → resolved disqualifier → ineligible
UNKNOWN on hard → unresolved → needs_chart_review (or manual_review per policy)
procedural_pre_screen → non-blocking
any-branch TRUE discharges UNKNOWN siblings (coverage after fold)
```

Rank **relevance** separately from eligibility and coverage. Never inflate by raw “bullets met.”

### 6.3 Atom `type` enum

Normative closed set is §6.5.1. Illustrative mapping (domain detail lives in `concept`, not new types):

| type | Typical registry language | Patient facts |
|------|---------------------------|---------------|
| `demographics_age` | ≥18 years | age / birth precision |
| `demographics_sex` | female only | administrative gender (caveats) |
| `demographics_reproductive` | WOCBP, contraception, pregnancy | confirmation-heavy |
| `diagnosis` | disease X confirmed | Condition + narrative |
| `histology` | HG serous, adenocarcinoma | extraction / review |
| `stage` | AJCC / limited-stage | stage facts |
| `disease_state` | recurrent, platinum-sensitive, **RECIST measurable** | state + therapy / imaging facts |
| `biomarker` | BRCA mut, HER2−, PD-L1 | Observation / report |
| `scored_instrument` | ECOG, NYHA, NIHSS, Child-Pugh, … | named ordinal scale (§6.5.2) |
| `functional_status` | ambulatory, wheelchair-bound | non-scored function |
| `lab` | ANC ≥ …, bilirubin &lt; … | labs + UCUM validation |
| `organ_function` | QTc, LVEF, eGFR | labs / reports |
| `prior_therapy` | prior PARPi, ≤2 lines ET | TherapyEvent |
| `washout` | within 21 days of … | dated events + anchor |
| `comorbidity` | ILD, other malignancy | Condition |
| `specimen` | archival tissue available | confirmation |
| `procedural` | ICF, compliance | usually `procedural_pre_screen` |
| `investigator_judgment` | “in opinion of investigator” | always manual |
| `opaque_text` | unsafe to structure | unresolved / review |

`measurable_disease` as a separate `type` is **retired** (v1.2): encode RECIST/measurable requirements as `disease_state` (or `opaque_text` if unsafe) with an explicit concept code. `performance_status` → `scored_instrument` (§6.5.3).

---

## 6.4 Conditional & derived atom constructs (v1.1)

Flat `predicate` + `qualifiers.exceptions` cannot represent the criteria that dominate real registries (see `MATCHER_DESIGN.md` §5). Four additive constructs are required. An atomizer that cannot safely produce one MUST fall back to `opaque_text` + `needs_review` — never a wrong flat atom.

### 6.4.1 Relative-to-reference thresholds

Real: *“total bilirubin < 1.5 × ULN”*, *“creatinine ≤ 1.5 × ULN”*. The bound is relative to the **patient’s own** reference, not an absolute number.

```jsonc
"predicate": {
  "op": "lte",
  "value": 1.5,                     // factor, not an absolute quantity
  "reference": {
    "basis": "patient_reference_high",  // absolute | patient_reference_high | patient_reference_low | patient_baseline
    "of_concept": "same_analyte"        // whose reference range: the evaluated fact's own bound
  }
}
```

Effective threshold = `value × (reference drawn from the patient Fact)`. If the reference is absent on the patient Fact → `UNKNOWN` (matcher MUST NOT assume a standard ULN). `basis: "absolute"` is the ordinary case and needs no reference.

### 6.4.2 Derived-value atoms

Real: *“estimated creatinine clearance ≥ 50 mL/min by Cockcroft-Gault”*. The value is a derivation the **hospital** owns; the pack only states the concept and which derivations are acceptable.

```jsonc
"concept": { "system": "avicenna", "code": "creatinine_clearance" },
"derivation": {
  "acceptable_methods": ["cockcroft_gault"],   // empty = any reviewed method
  "forbid_runtime_derivation": true            // matcher evaluates a derived PatientFact; never computes it itself
}
```

The matcher evaluates against a derived `PatientFact` with its own provenance; it MUST NOT compute from guessed demographics (A9). An `any`-sibling (e.g. absolute creatinine) can discharge a missing derivation.

### 6.4.3 Guarded predicates (`cases`)

Real: *“AST ≤ 1.5 × ULN (≤ 3 × ULN in patients with liver metastases)”*; *“age ≥ 50, or ≥ 55 for Czech Republic”*. A branch is selected by a guard that keys on a **patient fact** or on **site context**.

```jsonc
"guarded": {
  "cases": [
    { "when": { "scope": "patient_fact", "concept": {"code":"liver_metastases"}, "op": "exists" },
      "then": { "op": "lte", "value": 3.0, "reference": {"basis":"patient_reference_high","of_concept":"same_analyte"} } }
  ],
  "else":   { "op": "lte", "value": 1.5, "reference": {"basis":"patient_reference_high","of_concept":"same_analyte"} }
}
```

`when.scope ∈ {patient_fact, site_context}` (the latter for jurisdiction guards, e.g. `country = CZ`). Matcher semantics are supervaluation over an `UNKNOWN` guard (`MATCHER_DESIGN.md` §5.3): the guard fact is required only in the ambiguous band.

### 6.4.4 Coverage-aware `not_exists`

Real: *“No prior elacestrant or other SERDs for advanced disease”* — an inclusion whose predicate is a negation. **Normative evaluation is `MATCHER_DESIGN.md` §5.4** (this section is the atom wire shape + what the atomizer must encode).

A missing matching Fact is **never** proof of absence. `not_exists` → `TRUE` only with a **positive, criterion-scoped signal of absence**:

1. a criterion-scoped `explicit_negative` / `scoped_absence` Fact on the patient packet, or  
2. a `coverage.completeness` assertion whose **scope subsumes** this atom’s query scope (concepts ⊇, compatible setting, time window covering the criterion — a `bounded` window **never** clears a `lifetime` criterion).

Mere presence in `assessed_fact_keys` is **not** sufficient (“assessed” ≠ complete history). Completeness `method` must be reviewed reconciliation / approved validated process — extraction cannot self-certify. Unknown/unvalidated concept membership → `UNKNOWN`.

```jsonc
"predicate": {
  "op": "not_exists",
  "concept": { "system": "atc", "code": "…SERD…" },   // or agent_classes[]
  "qualifiers": {
    "disease_setting": "advanced",
    "agent_classes": ["serd"]           // optional; membership tested with pinned ontology version
  },
  "absence_scope": {
    "time_extent": "lifetime",          // lifetime | bounded
    "bounded_days": null,               // required when time_extent=bounded
    "setting": "advanced",              // must be covered by packet completeness setting
    "concepts": ["serd"],               // queried set; completeness must subsume (⊇)
    "ontology_version_pin": null        // e.g. "atc@2026-01"; null → membership checks UNKNOWN
  },
  "on_uncovered": "unknown"             // always unknown in v1 — never coerce to TRUE
}
```

**Atomizer rules:** emit `absence_scope` from the source text (lifetime vs washout window, setting, agents/classes). Do **not** invent ontology pins. If the paragraph only says “no prior X” without a clear time bound, default `time_extent: "lifetime"`. If structuring the scope is unsafe → `opaque_text` + `needs_review`.

**Conservatism is bounded to absence/negation:** positive exposures, measured thresholds, and sufficient `any`-siblings still resolve without exhaustive history (`MATCHER_DESIGN.md` §5.4 last paragraph).

### 6.4.5 Cross-criterion references (DAG)

Real: *“INR ≤ 1.5 × ULN, unless the patient meets exclusion criterion 16.”* Criteria reference each other, making a pack a DAG.

```jsonc
"ref": { "criterion_id": "ctgov:NCT06382948:exclusion:16", "as": "triggered" }  // as ∈ {satisfied, triggered, predicate_true}
```

References MUST be acyclic; the matcher evaluates in dependency order and refuses cycles.

### 6.4.6 `time_window.relation` additions

To support aggregation-by-relation (`MATCHER_DESIGN.md` §4.5), extend the enum with `current` and `at_screening` (point-in-time; take the authoritative latest) alongside `any_history`/`ever` (existential over all compatible Facts) and `within_days_before_anchor`.

---

## 6.5 Engine vs grammar — keeping the standard multi-specialty

Only ~32% of the corpus is oncology; NYHA (cardiology), FEV1/GOLD (respiratory), eGFR, and HbA1c criteria are each as common as RECIST. An oncology-only mental model of types (histology, stage, RECIST-as-special-case, ECOG-only performance) mis-types or opaques the majority of trials.

**Principle — separate the engine from the grammar:**

- The **matcher engine** (K3 + set-based comparison) is **domain-neutral**: a NIHSS ≤ 7 compares exactly like an ANC ≥ 1.5.
- The **grammar** (the `type` set + value kinds + concept registry) is where domain lives, and it MUST stay thin in `type` and rich in **concepts**.

A disease area is added by extending the **concept registry** (and, rarely, an instrument definition) — **never** by adding a `type` like `nyha_class` or a bespoke evaluation path. Pushing domain knowledge into the `type` enum or the matcher is the coupling this split exists to prevent.

### 6.5.1 Domain-neutral `type` set

`type ∈ { demographics_age, demographics_sex, demographics_reproductive, diagnosis, histology, stage, disease_state, biomarker, scored_instrument, functional_status, lab, organ_function, prior_therapy, washout, comorbidity, specimen, procedural, investigator_judgment, opaque_text }`. The disease-specific detail (which disease, which marker, which instrument) rides in `concept`, not in `type`.

### 6.5.2 `scored_instrument` value kind (generalizes `performance_status`)

ECOG is one instance of a universal pattern — a **named ordinal scale with a fixed range and a no-silent-interconversion rule**. NYHA (I–IV), NIHSS (0–42), EDSS (0–10 by 0.5), Child-Pugh (A/B/C or 5–15), DAS28, Mayo, GOLD, MMSE (0–30) are the same shape.

```jsonc
{
  "kind": "scored_instrument",
  "instrument": { "system": "avicenna", "code": "nyha" },   // ecog | karnofsky | nyha | nihss | edss | child_pugh | das28 | mayo | gold | mmse | …
  "value": 2, "value_high": 3,          // numeric or ordinal; interval preserved
  "ordinal_code": null,                  // for A/B/C-style scales, in place of value
  "scale_min": 1, "scale_max": 4,
  "step": 1,                             // e.g. 0.5 for EDSS, 10 for Karnofsky
  "no_interconversion": true             // the ECOG↔Karnofsky rule, now universal
}
```

The matcher evaluates it set-based like any ordered value; `no_interconversion` forbids mapping between instruments (a Karnofsky fact never satisfies an ECOG predicate without a reviewed derived fact, §6.4.2).

### 6.5.3 Migration

`performance_status` (the §6.3 `type` here, and the `performance_status` value kind in `PATIENT_MATCHING_FORMAT_STANDARD.md`) is **deprecated** in favor of `scored_instrument` with `instrument ∈ {ecog, karnofsky}`; existing ECOG/Karnofsky atoms read as that instance. `functional_status` remains for non-scored functional assertions (e.g. “ambulatory”, “wheelchair-bound”) that are not an instrument score.

---

## 7. Where to use LLMs

### 7.1 Allowed (public trial text only)

| Job | Input | Output | Model |
|-----|--------|--------|-------|
| Atomize criteria | One I/E paragraph (+ condition context) | Criterion + atoms | EU Data Zone Sol |
| HTML → TrialStub | Cleaned page chunk | TrialCard seed + source_text | EU DZ Sol |
| Coordinator PDF/CSV | Non-PHI text | TrialCard + source_text | EU DZ Sol |
| Concept normalize assist | Atom displays | Suggested codes | EU DZ Sol → vocab review |
| Conflict summarize | Two `source_text`s | Review notes | EU DZ Sol |

### 7.2 Forbidden

- Patient-linked decisions, scores, or explanations in cloud  
- Inventing IDs / labs / thresholds not in `source_text`  
- Silent merge of contradictory packs  
- Softening `hardness` because patient data is often missing  

### 7.3 Atomization pipeline (guards)

```text
1. Split → paragraphs (deterministic; CTIS arrays already split)
2. Per paragraph:
   a. LLM → Criterion JSON (strict schema)
   b. JSON Schema validate
   c. Grounding checks: thresholds/concepts must appear in source_text;
      exception/and-or → needs_review or opaque_text
   d. On failure → one opaque_text atom, needs_review=true
3. Emit pack_version + source_etag; export CURRENT
4. Spot-check Motol/Homolka (geo_rank 1) before trusting auto_passed
```

### 7.4 Prompt contract (sketch)

```text
Structure ONE eligibility paragraph into JSON atoms (schema avicenna.criterion.v1).
Extract only what the paragraph states.
Preserve AND/OR/exceptions; if unsafe, one opaque_text + needs_review.
kind is given; do not flip inclusion/exclusion.
Default hardness=hard; use procedural_pre_screen only for investigator judgment, consent, or pure willingness. Never emit soft.
```

Re-run with new `prompt_version` ⇒ new `pack_version`.

---

## 8. Deterministic extractors (prefer over LLM)

| Field | Source | Method |
|-------|--------|--------|
| trial_uid, titles, status, phase | CTIS/CT.gov | JSON paths |
| sex, min/max age | CT.gov `eligibilityModule`; CTIS population / age_group | JSON paths (CTIS often band-only) |
| conditions + MedDRA | CTIS retrieve / CT.gov conditions | JSON paths |
| sites + geo_rank | CTIS Part II / CT.gov locations | JSON + `org_norm.yml` |
| EUCT ↔ NCT | CT.gov secondary ids / CTIS identifiers | type=CTIS + regex |
| CT.gov → paragraphs | `eligibilityCriteria` | Inclusion/Exclusion header split |
| `eligibility_preview` | same paths | copy verbatim into L1 |

LLM only for **typed predicates inside prose**.

---

## 9. Optional FHIR mapping (non-normative)

If the hospital prefers FHIR types later:

| Avicenna | FHIR (illustrative) |
|----------|---------------------|
| TrialCard | `ResearchStudy` |
| Criterion / Atom | `EvidenceVariable` characteristic / FHIR R5 `Eligibility` ideas — **not required for v1** |

v1 wire format remains JSON CriteriaPack. FHIR is an adapter, not a replacement for L0 registry JSON.

---

## 10. File / table layout

```text
data/trials/
  cards/{trial_uid}.json
  packs/{trial_uid}/{pack_version}.json
  packs/{trial_uid}/CURRENT
  crosswalk.jsonl
  org_norm.yml
  schemas/
    trial_card.v1.json
    criteria_pack.v1.json
    criterion.v1.json
```

Or SQLite tables `trial_cards`, `criteria_packs` (+ optional `pack_atoms` index).

Hospital import: CURRENT packs + cards for the active slice (e.g. `geo_rank_best ≤ 4` and normalised status in authorised/recruiting).

---

## 11. Relation to patient matching

| Trial standard | Hospital (`MATCHER_DESIGN.md` / patient packet) |
|----------------|--------------------------------------------------|
| `required_patient_facts` | Fact `fact_key` slots (may be unknown) |
| atom predicate + §6.4 constructs | K3 + set-based eval; relative ULN, guards, `not_exists` coverage |
| `hardness=hard` + UNKNOWN | `needs_chart_review`; listed in `blocking_criteria` |
| resolved hard disqualifier | `ineligible` |
| `procedural_pre_screen` | `procedural_outstanding` (non-blocking) |
| `geo_rank` / conditions | `relevance` axis only |
| `opaque_text` / high opaque ratio | `manual_review` (severity-OR-ratio policy) |
| `criteria_completeness=partial` | caps best state at `needs_chart_review` |

MVP demo: packets may have unknown facts; UI must show gaps — do not fabricate facts to look complete.

---

## 12. Acceptance checks (trial side)

- [ ] L0 retained; L1 rebuildable without LLM for CTIS/CT.gov  
- [ ] Every Criterion has verbatim `source_text`  
- [ ] No atom threshold absent from `source_text`  
- [ ] Ambiguous Boolean → `needs_review`, §6.4 constructs, or `opaque_text`  
- [ ] No `hardness: soft` in any pack  
- [ ] Every pack has `criteria_completeness`, `study_type`, and `criteria_policy`  
- [ ] Relative-ULN / guarded / `not_exists` (with `absence_scope`) / cross-refs represented or degraded to opaque  
- [ ] `not_exists` never treats `assessed_fact_keys` alone as sufficiency (matcher §5.4)  
- [ ] Linked CTIS/CT.gov conflict → `keep_both_review` or explicit prefer policy — no silent merge  
- [ ] `pack_version` changes with prompt/validator/source etag  
- [ ] Export has no patient data  
- [ ] Synthetic fixtures align with `MATCHER_DESIGN.md` §11–§12 (incl. `any` discharging UNKNOWN sibling)  

---

## 13. Implementation order

1. JSON Schemas under `data/trials/schemas/` + validator CLI  
2. TrialCard projector from existing SQLite (no LLM)  
3. LLM atomizer for Motol/Homolka CTIS principals (`geo_rank` 1)  
4. CT.gov paragraphs when no CTIS pack (or under `keep_both_review`)  
5. HTML/coordinator → TrialStub → TrialCard → same atomizer  
6. Hospital import + synthetic evaluation tests  

---

## 14. Changelog

| Ver | Notes |
|-----|--------|
| 1.0 | Initial layers, TrialCard, CriteriaPack, LLM guards |
| 1.1 | Explicit “registries unfit for matching”; L0=native; TrialStub mapping; drop atom `polarity`; hospital result fields; status/site recruiting split; FHIR non-normative; mark proposed |
| 1.1a | Add §6.4 conditional/derived atom constructs; drop `soft` hardness; result vocabulary deferred to matcher |
| 1.1b | Add §6.5 engine-vs-grammar; `scored_instrument`; multi-specialty without new `type`s |
| 1.2 | Align with matcher: `criteria_completeness` + `study_type`; `arm_scope`; retire `measurable_disease`; result enums → matcher §8.1 |
| 1.3 | Sync matcher §5.4: `absence_scope` on `not_exists` (subsumption, not `assessed_fact_keys`); `criteria_policy` + `linked_packs` on pack; clean §6.5 intro |

---

## 15. References

- `MATCHER_DESIGN.md` — hospital evaluator (normative result enums, K3, evidence policy)  
- `PATIENT_MATCHING_FORMAT_STANDARD.md` — patient packet / Facts  
- `PROPOSAL_TRIAL_DATA_STANDARD.md` — consultant-facing rationale  
- `CTIS_TRIALS_STRUCTURE.md` — CTIS field map  
- `TRIALS_CATALOG_SOURCES.md` — sources + TrialStub  
- `PATIENT_MATCHING_DATA_NEEDS.md` / `_RESPONSE.md` — needs + hospital capability  
- `reports/GENERAL_DATA_GUIDE.md` — cloud vs hospital  
- CT.gov API v2 / PRS Data Element Definitions; CTIS public retrieve JSON  

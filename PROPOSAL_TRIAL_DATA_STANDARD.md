# Proposal: Trial eligibility data standard for Avicenna

**Status:** Draft for consultant review  
**Date:** 2026-10-17  
**Authors:** Rakathon team (Avicenna / Motol–Homolka trial matching)  
**Related technical draft:** `TRIAL_DATA_STANDARD.md` (v1.3) · **Matcher design:** `MATCHER_DESIGN.md`  
 
**Privacy:** This proposal covers **public trial registry and derived criteria structures only**. It does not describe patient records, cohorts, or hospital extracts.

---

## 1. Purpose of this review

We ask the consultant to review and challenge:

1. Whether a **derived, versioned criteria pack** is the right matching contract (vs adopting an existing public or FHIR-native format as primary).
2. Whether our **cloud vs hospital** split for structuring vs evaluation is sound under typical clinical-research and data-protection practice.
3. Whether **LLM-assisted structuring of public eligibility text** (with deterministic validation and human review gates) is an acceptable approach for a decision-support (not enrollment) tool.
4. Gaps, risks, or simpler alternatives we should prefer for a hackathon-to-pilot path.

Detailed field definitions live in `TRIAL_DATA_STANDARD.md`. This document states the **recommended approach and rationale**.

---

## 2. Problem statement

Avicenna must:

- Ingest trials relevant to Motol/Homolka and a Prague → CZ → EU geo ladder.
- Turn inclusion/exclusion text into something a system can compare to local patient facts.
- Produce transparent outcomes: criterion met / not met / data missing (or equivalent unresolved states), with explanations for clinicians.
- Keep **patient** processing inside an approved hospital boundary; public trial metadata may be prepared outside that boundary.

**Constraint we confirmed empirically:** major public sources (**CTIS**, **ClinicalTrials.gov**) expose rich study metadata but **do not** publish eligibility as machine-evaluable predicates. I/E arrive as free-text paragraphs or a single eligibility blob; only coarse fields (e.g. sex, age bands) are structured.

Local hospital lists (e.g. professional society pages, coordinator spreadsheets) are even less standardized.

Therefore “just use the registry format” cannot satisfy the matching requirement without a derived layer.

---

## 3. Recommended approach (summary)

Adopt a **three-layer trial data model**:

| Layer | Name | What it is | How it is produced |
|-------|------|------------|--------------------|
| **L0** | Raw source | Unmodified CTIS / CT.gov / HTML / coordinator files | Deterministic ingest; append-only |
| **L1** | TrialCard | Catalog record: IDs, titles, status, conditions, sites, geo rank, coarse demographics | Deterministic projection from L0 (LLM only for messy HTML/manual stubs) |
| **L2** | CriteriaPack | Versioned, typed eligibility atoms (polarity implied by inclusion/exclusion kind) with hardness | LLM structuring of **public** I/E text + automated validation + review flags |

**Hospital import artifact:** current CriteriaPack (+ TrialCard header).  
**Patient facts and match results:** hospital-local only; never sent to cloud to “improve” rules.

```text
Public web / APIs  →  L0 raw  →  L1 TrialCard  →  L2 CriteriaPack
                                                      ↓
                              Hospital: PatientFact ↔ evaluate ↔ clinician UI
```

This is intentional: **registries remain system-of-record for wording**; Avicenna owns **interpretation for matching**, with full provenance back to verbatim source text.

---

## 4. Why this is our best approach

### 4.1 Fit to the product

The product promise is criterion-level compare-and-explain, not merely “similar trials.” That requires predicates (age ≥ 18, ECOG 0–1, no prior ADC, …), not embeddings alone. Embeddings may help **shortlist**; they must not be the sole eligibility gate.

### 4.2 Honest use of upstream standards

| Upstream | We use it for | We do not claim |
|----------|---------------|-----------------|
| CTIS public API | Best EU L0 + principal I/E lists + sites | Structured match rules |
| CT.gov API v2 / PRS | L0, Motol/Homolka recall, NCT↔EU CT crosswalk | Structured match rules |
| FHIR R4 (hospital) | Patient store | That ResearchStudy/EvidenceVariable is already populated by registries |
| CDISC / WHO ICTRP | — | Useful primary path for this project |

Reusing CTIS/CT.gov **as L0** maximizes auditability and refresh. Inventing a parallel “better registry” would duplicate work and drift from sponsor-facing text.

### 4.3 Separation of structuring and evaluation

- **Structuring** public text can happen in cloud (including EU-hosted LLM) because inputs are public.
- **Evaluation** must be deterministic and local, against uncertain/generalized/shifted patient facts, with explicit `unresolved` — not LLM judgment on the chart in the cloud.

This matches the architecture already assumed in our privacy-safe integration guide.

### 4.4 LLM where it earns its keep

Eligibility prose packs histology, biomarkers, prior therapy, labs, and exceptions into single paragraphs. Hand-coding rules for thousands of trials is not viable in hackathon time; pure regex underfits.

**Controls we propose as non-negotiable:**

- Verbatim `source_text` retained on every criterion.
- No numeric threshold unless present in source text (grounding checks).
- Unsafe Boolean/exception splits → `opaque_text` + human review, not a wrong atom graph.
- Versioned packs (`pack_version`, prompt/validator versions) so interpretations are reproducible.
- Default **hardness = hard** when the protocol states a requirement; missing patient data ⇒ `unresolved`, never pass. The semantics that keep a hard default *usable* and not just safe — i.e. that avoid flagging nearly every trial as blocked — are set out in §4.7.

### 4.5 Multi-source without silent merge

Motol-relevant trials often appear in both CTIS and CT.gov. Texts and arms can differ. We recommend:

- Crosswalk by EU CT / NCT when registry-backed.
- Default preference for **CTIS principal criteria** when linked.
- On conflict: **keep both packs** and flag review — never average or silently overwrite.

### 4.6 Pragmatism for Motol / Homolka

Geo rank on TrialCard supports the client’s Prague-first ladder as **relevance**, not fake ineligibility. Site willingness and true local recruiting status remain confirmation/review items when registries are ambiguous.

### 4.7 Hardness and `unresolved`: the semantics that keep matching safe *and* usable

`hardness` was not designed up front; it emerged because every criterion that refused to fit “blocks / doesn’t block” forced a new case. On review it is best understood as a **projection of two independent axes** onto one field:

- **Consequence when a predicate resolves to a disqualifying answer** (we hold the fact and it fails): disqualify / deprioritize / note.
- **Meaning of an *unknown*** (no patient fact): a chart gap a human must close before enrolling / nice-to-have / not a chart gap at all, because it is resolved at the screening visit.

`hard` asserts *both* “disqualifying when false” **and** “must-resolve when unknown.” For most protocol criteria these co-move, so one scalar is adequate. The enum’s other values are exactly the divergence cases:

- `procedural_pre_screen` — disqualifying in principle (you cannot enrol without consent) but where **unknown is normal**, because it is resolved at the screening encounter, not from the chart. Such atoms must never depress a trial’s rank for “missing data” (ICF, willingness, investigator judgment).
- ~~`soft`~~ — **dropped.** A CTIS corpus scan (all 1,621 retrieved CZ dossiers) found no genuine soft eligibility preference; “preferably / should / where possible” always decorated a hard or procedural requirement (`MATCHER_DESIGN.md` §6). Softness stays on the TrialCard **relevance** axis only.

Two invariants make a hard default safe **and** prevent a false-negative flood:

1. **`ineligible` is reserved for a *resolved* disqualifier** — a hard exclusion known true, or a hard inclusion known false. An **unknown never yields `ineligible`; it yields `needs_chart_review`.** Under sparse oncology extracts almost every trial will carry unresolved hard inclusions; that is expected and harmless, because automatic “eligible” was never the target — “which few trials deserve a clinician’s time” is.
2. **Coverage is folded, then ranked.** Unresolved atoms under a *satisfied* `any` criterion are discharged, not counted as gaps; evidence coverage is accounted at the criterion level **after** logic folding and surfaced as a primary triage signal alongside relevance. A trial with nine of ten hard inclusions satisfied and one unknown must rank far above one where only two are evaluable.

The wrong response to the flood is to demote hard criteria to `soft`: that hides real gates (washout, measurable disease, pregnancy). The right response is ranking by coverage, never demotion. Normative evaluation rules live in `MATCHER_DESIGN.md`; the CriteriaPack wire format lives in `TRIAL_DATA_STANDARD.md` v1.2.

---

## 5. Alternatives considered

| Alternative | Verdict | Reason |
|-------------|---------|--------|
| **Match on registry JSON as-is** | Reject as primary | Cannot score most oncology I/E |
| **Only CT.gov or only CTIS** | Reject | Misses EU-local sites vs global/device/registry coverage; Motol needs both |
| **FHIR EvidenceVariable as primary wire format** | Defer | Conceptually close, but unused by public APIs; adds implementer cost; better as optional hospital adapter later |
| **Fully manual criteria coding** | Reject for scale | Acceptable for a tiny Motol pilot list; not for catalog breadth |
| **LLM end-to-end match (patient + trial in one prompt)** | Reject for cloud path | Patient boundary, non-determinism, weak audit; structuring trials ≠ judging patients |
| **Embeddings-only ranking** | Reject as sole method | Fails explainability and hard exclusions |

**Hybrid we endorse:** deterministic L1 + LLM L2 structuring + deterministic hospital evaluation + clinician review for unresolved hard criteria.

---

## 6. Scope of the proposed standard (for review)

### In scope

- Trial identity and crosswalk.
- Catalog fields needed for search and geo ranking.
- CriteriaPack: criterion kind (inclusion/exclusion), atoms, operators, units/time windows, hardness, review flags.
- Provenance: source registry, retrieval time, content hash, structuring method/model/prompt versions.
- Rules for LLM use and validation on **public** text.
- Export expectations toward a hospital matcher.

### Out of scope (explicit)

- PatientFact / TherapyEvent schemas (hospital-owned; sketched elsewhere for interface only).
- Claiming clinical eligibility or enrollment authorization.
- Replacing sponsor/CTIS submissions or regulatory archives.
- Guaranteeing that unstructured HTML/coordinator sources are complete.

---

## 7. Governance and quality bar (proposed)

1. **Source supremacy:** If structured atoms disagree with `source_text`, the text wins; atoms are marked wrong/unsupported until fixed.
2. **Review tiers:** `auto_passed` only after schema + grounding validators; Motol/Homolka (geo rank 1) packs should be spot-checked before trusting automation.
3. **Decision-support labeling:** UI must distinguish shortlist relevance from eligibility state and must surface unresolved hard criteria.
4. **No patient in the loop for rule authoring:** Cloud must not fetch patient fields to refine packs.
5. **Retention:** Raw L0 retained for audit; pack versions immutable; “CURRENT” pointer is the only mutable alias.

---

## 8. Delivery phasing (so the standard stays usable)

| Phase | Deliverable | Standard depth |
|-------|-------------|----------------|
| A | L0 ingest + L1 TrialCard from CTIS/CT.gov SQLite | Implementable without LLM |
| B | JSON Schemas + validator for CriteriaPack | Normative wire format |
| C | LLM atomizer for Motol/Homolka CTIS principals | First trusted L2 cohort |
| D | CT.gov-only and HTML/coordinator packs | Same L2 schema |
| E | Optional FHIR adapter | Non-normative mapping |

We recommend **freezing v1 schemas at Phase B** even if atom coverage is incomplete: unknown/opaque atoms are valid.

---

## 9. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| LLM invents thresholds or flips inclusion/exclusion | Grounding validators; opaque fallback; polarity fixed by `kind` |
| Over-splitting Boolean text changes meaning | Prefer opaque + review over clever graphs |
| CTIS vs CT.gov divergence | Dual packs + conflict policy |
| Treating unresolved as pass | Hardness rules; hospital acceptance tests |
| Scope creep into full protocol PDF coding | Start from principal/public eligibility; escalate PDFs only for priority sites |
| Consultant/regulatory expectation of CDISC/FHIR-first | Position Avicenna pack as matching interpretation layer; map later if required |

---

## 10. Questions for the consultant

We would value explicit advice on:

1. **Primary contract:** Is CriteriaPack-as-JSON acceptable for pilot decision-support, or should we mandate FHIR EvidenceVariable (or another standard) from day one?
2. **LLM structuring of public I/E:** Acceptable with the controls in §4.4, or should Motol-priority trials be human-structured only?
3. **Hardness / unresolved (see §4.7):** Is “protocol-hard stays hard; missing evidence ⇒ `needs_chart_review`, never pass and never automatic `ineligible`; triage by coverage after fold” aligned with how trial offices expect a pre-screening tool to behave? *(Internal: `soft` already dropped pending any counter-example you supply.)*
4. **Source preference:** Is defaulting to CTIS principal criteria (when NCT↔EU CT linked) reasonable for an EU site, with CT.gov as fallback/conflict surface?
5. **Geo rank:** Any objection to using site proximity as relevance ranking rather than a hard filter?
6. **Minimum review:** What review burden is proportionate for hackathon vs a hospital pilot (e.g. % of packs human-approved before production alerts)?
7. **Naming / IP:** Any conflict with calling this an internal “Avicenna criteria pack” vs aligning names to an existing open specification?

---

## 11. Ask

Please review this proposal and the technical draft `TRIAL_DATA_STANDARD.md` v1.1, and return:

- **Approve / approve with changes / reject** on the three-layer approach.
- Marked-up answers to §10 where possible.
- Any must-fix normative requirements (fields, coding systems, audit trails) before we implement Phase B schemas.

---

## 12. Annex — one-page mental model

```text
CTIS / CT.gov / HTML / coordinator
        │  (keep bytes, hash, time)
        ▼
   TrialCard (who/what/where/status)
        │
        ▼
   CriteriaPack (what “eligible” means, versioned)
        │  public criteria only
        ▼
   Hospital evaluator + PatientFacts → explainable pre-screen
```

**Bottom line:** The best approach is not to wait for registries to ship structured eligibility, nor to judge patients in the cloud, but to **standardize a provenance-preserving interpretation layer** (CriteriaPack) built from public text under controlled LLM+validation, and evaluate it deterministically next to the patient.

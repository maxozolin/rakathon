# Patient data needed to match against our trial catalog

> Derived only from **trial** sources (`data/ctis/`, `data/ctgov/`). No patient records inspected.  
> Corpus snapshot: CTIS search **12 636**, CTIS retrieve **~1 530+**, CT.gov Prague/Motol/Homolka **552** (Motol **173**, Homolka **39**).

The registries do **not** ship structured eligibility. Matching is almost always “patient facts ↔ free-text I/E criteria.” This note lists the **patient-side facts** those criteria keep asking for, so the EU-zone model / IRIS extract can target the right FHIR shapes.

---

## 1. Verdict

To match a patient to trials in our catalog you need, in practice:

| Tier | Patient facts | Why |
|------|----------------|-----|
| **A — hard gate** | Age, sex, primary diagnosis (+ histology), site/geography willingness | Almost every trial; partly structured on CT.gov / CTIS overview |
| **B — oncology core** | Stage / extent, line of therapy & prior drug classes, key biomarkers, ECOG | Dominates Motol oncology I/E text |
| **C — safety labs & organs** | Recent CBC/chem, hepatic/renal, selected cardiac/infection flags | Very common in exclusions |
| **D — soft / often missing** | Washouts, measurable disease (RECIST), tissue availability, pregnancy/contraception, ICF | Present in text but rarely auto-decidable from a thin EHR dump |

Without **A+B**, ranking is mostly keyword/disease noise. Without **C**, you will over-propose trials that fail screening labs. **D** should score as `data_missing` / informational, not hard fail.

---

## 2. What the trial side actually provides

### Already structured (cheap filters)

| Field | CTIS | CT.gov (our DB) |
|-------|------|------------------|
| Status / recruiting | `ct_status` | `overall_status` (263 recruiting / 289 active-not-recruiting in seed) |
| Sex | `gender` (Female / Male / both) | `sex` ALL/FEMALE/MALE |
| Age band | coarse `age_group` (0–17 / 18–64 / 65+) | `min_age` / `max_age` (min present on ~95%) |
| Condition labels | `medical_conditions`, MedDRA in retrieve | `conditions_json` |
| Sites | retrieve `sites_json` (city + org; Motol/Homolka → mostly Prague) | `locations_json` + Motol/Homolka flags |
| Phase / sponsor | yes | phase in JSON |

### Free text (where matching lives)

- **CTIS:** `principalInclusionCriteria[]` / `principalExclusionCriteria[]` — numbered paragraphs (median inclusion bullet ~140 chars; tails >500). Sampled retrieves: ~**7** inclusion / ~**13** exclusion bullets per trial.
- **CT.gov:** single `eligibility_text` blob (p50 ~2k chars, p90 ~6k). Present on **100%** of our 552 rows.

Theme prevalence (keyword scan; not mutually exclusive):

| Theme | CTIS inclusions (n≈80) | CTIS exclusions | CT.gov elig (n=200) |
|-------|------------------------|-----------------|---------------------|
| Prior therapy / line | 68% | 74% | 78% |
| Age | 64% | 5% | 52% |
| Sex / pregnancy / contraception | 59% | 40% | 52% |
| Organ / infection / cardiac | 20% | **69%** | 58% |
| Labs | 18% | 50% | 40% |
| Biomarker | 22% | 29% | 38% |
| Stage / metastatic / RECIST | 20% | 21% | 44% |
| ECOG / PS | 22% | rare | 37% |
| Consent / compliance | 62% | 11% | 52% |

**Implication:** inclusions lean demographics + disease + consent; exclusions lean **organs, washouts, labs, comorbidities**. Patient extract must cover both.

---

## 3. Patient fact model (what the EU model should produce)

Map each fact to something matchable against criterion atoms (see `CTIS_TRIALS_STRUCTURE.md` §4). Prefer coded values + `as_of` date + `confidence`.

### 3.1 Demographics (Tier A)

| Fact | Needed for | Notes |
|------|------------|--------|
| `birthDate` or age (years) | Almost all trials | CT.gov often “≥18 Years”; CTIS age_group is too coarse alone |
| `sex` / administrative gender | Sex-restricted arms (~10% CT.gov FEMALE/MALE-only) | |
| Geography / treating site | Geo ranking | Motol vs Homolka vs other Prague vs CZ — from care site, not “home address” alone |

### 3.2 Disease identity (Tier A/B)

| Fact | Needed for |
|------|------------|
| Primary diagnosis (text + code if any: ICD-10 / SNOMED / MedDRA-ish) | Condition gate vs trial `medical_conditions` |
| Histology / morphology (e.g. HG serous, adenocarcinoma, SCLC) | Common Motol oncology inclusions |
| Confirmation method (histo/cyto) if known | “Histologically confirmed …” |
| Diagnosis / recurrence dates | Line-of-therapy & platinum-free interval logic |

### 3.3 Stage & disease state (Tier B)

| Fact | Needed for |
|------|------------|
| Stage / TNM / limited vs extensive | Stage-gated trials (~20–44% of texts) |
| Metastatic / locally advanced / recurrent / refractory | Disease-state atoms |
| Measurable disease / last imaging summary | RECIST clauses — often **missing**; mark `unknown` |
| CNS / brain mets status | Frequent hard exclusion |

### 3.4 Biomarkers & molecular (Tier B)

| Fact | Examples seen in catalog |
|------|--------------------------|
| Receptor / IHC | ER/PR, HER2 (0/1+/2+/ISH) |
| Mutations / fusions | BRCA, EGFR, ALK, BRAF, KRAS, … |
| Immuno markers | PD-L1 %, MSI/MMR, TMB |
| Specimen meta | Archival FFPE available? date of tissue |

On Motol oncology CT.gov lines, biomarker-tagged clauses are common (~112 hits in sample). Null biomarker ≠ fail if trial doesn’t require it; required biomarker with `data_missing` → do not auto-include.

### 3.5 Treatment history (Tier B — highest volume)

Prior therapy is the **#1** theme across CTIS and CT.gov.

Extract as a structured list, not a paragraph:

```text
TherapyEvent:
  class          # chemo | immuno | endocrine | targeted | ADC | PARP | radiation | surgery | transplant | other
  agents[]       # generic names / ATC if known
  line           # 1L / 2L / … if inferable
  intent         # neoadjuvant | adjuvant | advanced
  start/end
  best_response / progression_date  # if present
  setting        # for ABC, NSCLC, etc.
```

Needed to evaluate: “≥1 prior platinum”, “no prior topo-1 ADC”, “progressed on CDK4/6i”, washout windows.

### 3.6 Performance status (Tier B)

| Fact | Needed for |
|------|------------|
| ECOG (0–4) or Karnofsky | ~22–37% of oncology-ish criteria; usually inclusion ECOG 0–1 |

If absent → `data_missing` (soft down-rank for ECOG-gated trials, not global discard).

### 3.7 Labs (Tier C)

| Panel | Typical thresholds in text |
|-------|----------------------------|
| Hematology | ANC, platelets, hemoglobin (± transfusion/G-CSF washout) |
| Chemistry | Cr / eGFR, bilirubin, ALT/AST, albumin |
| Other | QTc, LVEF, pregnancy test |

Need **value + unit + date** (screening windows are often “within 7–14 days” — for catalog matching, “recent enough” + flag stale).

### 3.8 Comorbidities & safety (Tier C)

Active/significant: other malignancy, autoimmune disease, ILD, uncontrolled infection, HIV/HBV/HCV, transplant, serious cardiac disease, symptomatic CNS disease.

Represent as Condition list with `clinicalStatus` + onset if possible.

### 3.9 Procedural / soft (Tier D — do not hard-fail)

| Fact | Handling |
|------|----------|
| Informed consent | Assume unknown at pre-screen; never fail match |
| Contraception / WOCBP rules | Demographics + pregnancy if known; else missing |
| Willingness for biopsy / contraception compliance | Informational |
| “Investigator judgment” | Always soft |

---

## 4. Matching policy (patient side)

```text
1. Geo filter     → Motol/Homolka / Prague / CZ / EU using trial sites
2. Hard demo      → age, sex vs structured trial fields
3. Condition gate → diagnosis ↔ trial conditions (embed + codes)
4. Atom score     → each I/E bullet → atoms → met | not_met | data_missing
5. Aggregate      → any hard inclusion not_met or hard exclusion met → reject
                    many data_missing on Tier B → “needs chart review”
                    Tier D missing → ignore for rank
6. Rank           → geo_rank + #hard mets − #hard misses − missing penalty
```

Prefer **CTIS retrieve** criteria when EU CT id crosswalks to CT.gov (246 linked in our seed); else CT.gov `eligibility_text`.

---

## 5. Minimum viable patient packet (hackathon)

Enough to demo Motol oncology matching without full EHR:

1. Age, sex  
2. Primary oncology diagnosis + histology  
3. Stage / metastatic flag  
4. ECOG if available  
5. Prior systemic therapy list (drug class + approximate line)  
6. 3–5 key biomarkers relevant to diagnosis (or explicit “not tested”)  
7. Latest CBC + basic chem (or “labs unknown”)  
8. Treating center = Motol or Homolka  

Everything else improves precision but is optional for a first ranked shortlist.

---

## 6. Out of scope for this note

- How the EU model reads **patient** charts / FHIR (separate pipeline).  
- Inventing structured criteria the registries didn’t publish.  
- Committing protocol PDFs from coordinators.

---

## 7. Sources

- `data/ctis/ctis.sqlite`, `data/ctgov/ctgov.sqlite`  
- `CTIS_TRIALS_STRUCTURE.md`, `TRIALS_CATALOG_SOURCES.md`

# EU Clinical Trials (CTIS) — how to structure for Avicenna

> Source: [euclinicaltrials.eu](https://euclinicaltrials.eu/) / CTIS public portal & API.  
> No patient data in this note — trial catalog only.

---

## 1. What the portal is

- Public face of the **Clinical Trials Information System (CTIS)** (EMA), live since 31 Jan 2022 under CTR (EU) 536/2014.
- UI: [Search](https://euclinicaltrials.eu/ctis-public/search) (basic + advanced; CSV export of result lists).
- Machine access (undocumented-but-used public JSON API):
  - `POST https://euclinicaltrials.eu/ctis-public-api/search`
  - `GET https://euclinicaltrials.eu/ctis-public-api/retrieve/{ctNumber}`
- Also: older [EU Clinical Trials Register](https://www.clinicaltrialsregister.eu/) (EudraCT) still linked from the homepage for legacy trials.

For Avicenna’s Prague → CZ → Europe ladder, **CTIS is the right EU spine**; ClinicalTrials.gov remains useful as a world/supplement feed.

---

## 2. API shape (practical)

### Search (overview cards)

```http
POST /ctis-public-api/search
Content-Type: application/json
```

Useful `searchCriteria` knobs we verified:

| Field | Example | Notes |
|--------|---------|--------|
| `medicalCondition` | `"breast cancer"`, `"cancer"` | Free text; good recall, noisy |
| `containAll` | `"Czechia"`, `"Praha"` | Full-text; **Praha → 3 hits** (site-level), Czechia+cancer → hundreds |
| `sponsor` | `"Motol"` | Exact-ish; Motol alone returned 0 in a quick probe |
| `number` | `"2025-524202-15-00"` | Exact CT number |
| `status` | int array | Public status codes (see community mappings) |

`trialCountries` in results look like `"Czechia:2"` (country + MSC public status code).

**Location tip:** there is no clean “city=Prague” filter. Pipeline: search broad (condition + Czechia) → `retrieve` → filter `authorizedPartsII[].trialSites` by city / org name (Prague / Brno / Ostrava / Motol).

### Retrieve (full dossier)

```http
GET /ctis-public-api/retrieve/{ctNumber}
```

Payload is large (~100–250+ KB). Matching-relevant path:

```text
authorizedApplication
  authorizedPartI
    trialDetails
      clinicalTrialIdentifiers   → titles, shortTitle
      trialInformation
        medicalCondition         → free text + MedDRA terms
        eligibilityCriteria
          principalInclusionCriteria[]  → free-text bullets
          principalExclusionCriteria[]  → free-text bullets
        populationOfTrialSubjects → sex flags, age category codes
        trialObjective / endPoint
    products / productRoleGroupInfos
    sponsors
  authorizedPartsII[]            → per-country sites, local status
ctNumber, ctStatus, decisionDate, documents[]
```

**Important:** criteria arrive as **numbered free-text paragraphs**, not structured FHIR. One list item can pack labs, prior therapy, biomarkers, and ECOG into a single string.

---

## 3. Two worked examples (oncology + Czechia)

Pulled live from CTIS (Authorised). Summaries only.

### A. `2025-524202-15-00` — GCT1184-07 (ovarian)

| Field | Value |
|--------|--------|
| Condition | Recurrent platinum-sensitive ovarian cancer |
| MedDRA PT | Ovarian cancer recurrent |
| Sex | Female only |
| Sites (CZ sample) | Motol & Homolka, VFN, Bulovka, Královské Vinohrady (Prague), AGEL Nový Jičín |
| Products | e.g. Carboplatin (+ study drug Rina-S / bevacizumab context in title) |

**Inclusion themes (6 bullets):** histology (HG serous/endometrioid EOC ± peritoneal/FT); recurrence after 1L platinum; PARPi rules if BRCA-mut; measurable disease RECIST 1.1; tumor specimen; ECOG 0–1.

**Exclusion themes (4 bullets):** clear cell/mucinous/sarcomatous/low-grade; prior non-bev anti-angiogenics; prior topo-1 ADC; prior FRα ADC.

→ Dense **oncology structured fields**: histology, line of therapy, platinum sensitivity, biomarkers (BRCA), prior drug classes, ECOG, measurable disease.

### B. `2025-525026-35-00` — Trilaciclib-LSSCLC01 (lung)

| Field | Value |
|--------|--------|
| Condition | Limited-stage SCLC (LS-SCLC) |
| MedDRA PT | Small cell lung cancer limited stage |
| Sex | Female + male |
| Sites (CZ sample) | FN Ostrava, AGEL Ostrava-Vítkovice |
| Age text | ≥18 (in inclusion #1; age codes also on population object) |

**Inclusion themes (9 bullets):** age ≥18; LS-SCLC staging (VALSG / AJCC I–III, no distant mets); ECOG 0–1; eligible for concurrent CRT; RECIST disease; **lab panel** (Hb, ANC, platelets, …); recovery from surgery; contraception; ICF.

**Exclusion themes (13 bullets):** ES-SCLC; prior platinum/etoposide/trilaciclib for SCLC; recent other anti-cancer Rx; ILD; other malignancies; CV / QTc; infections (HIV/HBV/…); hypersensitivity; pregnancy; live vaccines; transplant; “investigator judgment” catch-alls.

→ Mix of **hard filters** (stage, ECOG, labs) and **soft / missing-prone** criteria (ICF, contraception, investigator opinion).

---

## 4. Proposed Avicenna trial schema

Normalize CTIS (and later CT.gov) into something the matching engine can score against IRIS/FHIR facts.

### 4.1 Trial header (catalog / geo ranking)

```jsonc
{
  "trial_id": "2025-524202-15-00",          // CTIS ctNumber (primary for EU)
  "registry": "ctis",
  "short_title": "GCT1184-07",
  "public_title": "...",
  "status": "Authorised",                   // ctStatus
  "phase": null,                            // map trialPhase code → I/II/III
  "conditions": [
    {
      "text": "Recurrent Platinum-Sensitive Ovarian Cancer",
      "meddra": [{ "pt": "Ovarian cancer recurrent", "code": "10066697" }]
    }
  ],
  "therapeutic_areas": ["..."],
  "products": ["Carboplatin", "..."],
  "sex": "female",                          // from isFemale/isMale
  "age": { "min_years": 18, "max_years": null, "raw_codes": ["3","4"] },
  "sites": [
    {
      "country": "CZ",
      "city": "Prague",
      "org": "Fakultni Nemocnice Motol A Homolka",
      "priority": 1                          // 1 Prague Motol/Homolka, 2 Prague other, 3 Brno/Ostrava, 4 CZ, 5 EU
    }
  ],
  "geo_rank": 1,
  "source": {
    "retrieve_url": "https://euclinicaltrials.eu/ctis-public-api/retrieve/2025-524202-15-00",
    "fetched_at": "ISO-8601"
  }
}
```

**Geo ranking (matches mission):** Motol/Homolka Praha → other Praha → Brno/Ostrava → rest of CZ → other EU → non-EU (if CT.gov merge).

### 4.2 Eligibility criteria (matching atomic units)

Each CTIS bullet → **one or more** structured criteria (LLM-assisted split allowed; keep `source_text` immutable).

```jsonc
{
  "criterion_id": "2025-524202-15-00:incl:2",
  "trial_id": "2025-524202-15-00",
  "kind": "inclusion",                      // inclusion | exclusion
  "seq": 2,
  "source_text": "Participant must have documented recurrence...",
  "logic": "all",                           // all | any (if split into subclauses)
  "atoms": [
    {
      "atom_id": "incl:2:a",
      "type": "disease_state",              // see typology below
      "operator": "eq",
      "concept": {
        "system": "avicenna",               // + SNOMED/MedDRA/ATC/LOINC later
        "code": "platinum_sensitive_recurrence",
        "display": "Platinum-sensitive recurrent disease after 1L platinum"
      },
      "params": {
        "min_prior_platinum_cycles": 4,
        "line": 2
      },
      "fhir_hints": ["Condition", "MedicationStatement", "Procedure"],
      "required_data": ["diagnosis", "prior_systemic_therapy"],
      "match_hardness": "hard"              // hard | soft | procedural
    }
  ]
}
```

### 4.3 Criterion typology (for Motol-style oncology matching)

| `type` | Examples from CTIS text | Typical evidence |
|--------|-------------------------|------------------|
| `demographics` | age ≥18, sex | FHIR Patient |
| `diagnosis` | SCLC, EOC histology | Condition + morphology |
| `stage` | LS vs ES, AJCC I–III | Condition stage / Observation |
| `disease_state` | platinum-sensitive recurrence | Condition + therapy timeline |
| `biomarker` | BRCA1/2 mut | Observation / DiagnosticReport |
| `performance_status` | ECOG 0–1 | Observation |
| `labs` | Hb, ANC, platelets, QTc | Observation (LOINC) |
| `prior_therapy` | prior PARPi / ADC / platinum | Medication* / Procedure |
| `washout` | vaccine &lt;30d, recent chemo | dates on above |
| `measurable_disease` | RECIST | often **missing** in EHR extract |
| `procedural` | ICF signed, contraception | usually **N/A / missing** for auto-match |
| `comorbidity` | ILD, active infection, other ca | Condition |
| `investigator_judgment` | “in opinion of investigator” | always soft / skip auto-fail |

**Scoring rule (aligns with mission):** per atom → `met` | `not_met` | `data_missing` (+ exclusion invert). Aggregate: hard fails dominate; procedural/soft → missing or informational, don’t tank the score alone.

---

## 5. Ingest pipeline (recommended)

```text
1. Search CTIS
   - seed queries: oncology conditions + containAll Czechia / Praha / Brno / Ostrava
   - optional: Motol/Homolka org names after retrieve
2. Retrieve each ctNumber (cache JSON; respect size)
3. Project header + sites → geo_rank
4. Extract principalInclusion/Exclusion arrays (English preferred)
5. LLM (EU Data Zone Sol): split bullets → atoms + typology + FHIR hints
   - never send patient data in this step
6. Store structured trial pack (JSON/Parquet) for matcher
7. Refresh: re-search Authorised / Recruiting statuses on a schedule
```

**LLM job prompt sketch:** “Given one inclusion/exclusion paragraph, emit JSON atoms with type, operator, concept, params, match_hardness; do not invent labs not stated; mark ambiguous clauses soft.”

---

## 6. Design implications for Avicenna

1. **CTIS “principal” criteria are already a summary** — full protocol PDFs live under `documents[]`. For MVP use principal lists; escalate to PDF only for Motol-priority trials.
2. **MedDRA on conditions** is gold for indexing; histology/biomarkers usually **only in free text**.
3. **Sites are Part II** — required for “recruiting at Motol / Prague” story; search alone is not enough.
4. **Many criteria will be `data_missing`** on hospital extracts (RECIST, ICF, contraception, investigator opinion) — UI must show that honestly (mission already asks for missing).
5. **Exclusions are as important as inclusions** — model them symmetrically with inverted logic.
6. **Geo ladder** is a sort key on an otherwise global/EU catalog, not a hard filter (unless product asks).

---

## 7. References

| Resource | URL |
|----------|-----|
| CTIS public home | https://euclinicaltrials.eu/ |
| Public search UI | https://euclinicaltrials.eu/ctis-public/search |
| Search API | `POST https://euclinicaltrials.eu/ctis-public-api/search` |
| Retrieve API | `GET https://euclinicaltrials.eu/ctis-public-api/retrieve/{ctNumber}` |
| EMA: full trial information field guide (PDF) | https://www.ema.europa.eu/en/documents/other/clinical-trial-information-system-ctis-public-portal-full-trial-information_en.pdf |
| Public-user FAQ / search tips (PDF) | https://www.ema.europa.eu/system/files/documents/other/cttm22_faqs_en.pdf |
| Community write-up of search/retrieve | https://www.hendrik.codes/post/scraping-the-clinical-trials-information-system |
| Example schema notes | https://github.com/brunoamaral/gregory-ai/blob/main/docs/ctis-public-api-schema.md |
| Example trials used here | `2025-524202-15-00`, `2025-525026-35-00` |

---

## 8. Bottom line

Treat CTIS as: **search → retrieve → geo-filter sites → freeze source criteria text → LLM-atomize into typed hard/soft rules → score met / not_met / missing against IRIS-held facts.**  
The two examples show the pattern: short “principal” lists that still hide labs, biomarkers, and prior-therapy logic inside prose — structuring those atoms is where Sol earns its keep, without touching patient charts in the catalog pipeline.

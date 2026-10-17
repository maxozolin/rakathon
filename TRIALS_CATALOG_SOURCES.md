# Trial catalog sources — CTIS, ClinicalTrials.gov, unstructured

How Avicenna should build the **trial side** of matching (no patient data).

---

## 1. Source stack (priority)

| Priority | Source | Role | Store |
|----------|--------|------|--------|
| 1 | **CTIS** (`euclinicaltrials.eu`) | EU CTR drug trials; best EU site + principal I/E text | `data/ctis/ctis.sqlite` |
| 2 | **ClinicalTrials.gov** | Broader (devices, registries, US-led, academic); NCT + eligibility block; Motol/Homolka/Prague | `data/ctgov/ctgov.sqlite` |
| 3 | **Unstructured HTML** (Linkos KOC, hospital pages, klinicketesty, …) | Fill gaps / local lists | `data/trials_unstructured/` + parsed JSON tables |
| 4 | **Coordinator channel** | Trials not in any public registry | CRM / `data/trials_manual/` |

Crosswalk key: **EU CT number** (`2024-######-##-00`) links CT.gov ↔ CTIS. Legacy **EudraCT** (`2019-######-##`) may exist only on CT.gov / old EU CTR.

---

## 2. What we already automate

### CTIS
```bash
uv run scripts/ctis_to_sqlite.py search-all          # overviews (~12.6k)
uv run scripts/ctis_to_sqlite.py retrieve --czechia  # full I/E + sites
uv run scripts/ctis_to_sqlite.py stats
```

### ClinicalTrials.gov
```bash
uv run scripts/ctgov_to_sqlite.py ingest   # Motol / Homolka / Prague seeds
uv run scripts/ctgov_to_sqlite.py stats    # includes CTIS crosswalk counts
```

Default CT.gov queries (see script): Motol+Prague, Homolka+Prague, Motol any, Prague+oncology keywords. Statuses: `RECRUITING`, `ACTIVE_NOT_RECRUITING`.

Each row keeps full `study_json`, location flags (`prague_related`, `motol_related`, `homolka_related`), `eligibility_text`, and parsed `eu_ct_ids_json` / `eudract_ids_json`.

---

## 3. Unstructured HTML → LLM parse

Use when the only public hint is a **webpage list** (e.g. [Linkos active KOC studies](https://www.linkos.cz/lekar-a-multidisciplinarni-tym/personalizovana-onkologie/klinicke-hodnoceni-a-klinicky-vyzkum/aktivni-klinicke-studie/), paediatric Motol/Brno lists, aggregator cards).

### Pipeline

```text
1. Fetch HTML (httpx/playwright) → save raw under
   data/trials_unstructured/raw/{source}/{date}/page.html
2. Strip to main content (readability / trafilatura / css selector per source)
3. Chunk by trial card / diagnosis section (keep source URL + heading)
4. LLM (EU Data Zone Sol) → structured TrialStub JSON (schema below)
5. Upsert into SQLite table trials_unstructured
6. Dedupe against CTIS/CT.gov:
   - if EUCT or NCT present → link, don't duplicate criteria from HTML
   - if title+sponsor+phase fuzzy match → link candidate for human confirm
   - else → status=needs_enrichment
7. Enrichment: if NCT/EUCT found later, pull registry and prefer registry I/E text
```

### LLM output schema (`TrialStub`)

```jsonc
{
  "source": "linkos_koc",
  "source_url": "https://...",
  "retrieved_at": "ISO-8601",
  "title": "string|null",
  "acronym": "string|null",
  "nct_id": "NCTxxxxxxxx|null",
  "eu_ct_id": "2024-......-00|null",
  "eudract_id": "2019-......-..|null",
  "phase": "I|II|III|IV|other|null",
  "conditions": ["..."],
  "centers": [{"name": "FN Motol", "city": "Prague"}],
  "status_text": "otevřená|nabírá|...",
  "inclusion_hints": ["free text bullets if page has them"],
  "exclusion_hints": [],
  "contacts": [{"email": null, "phone": null, "name": null}],
  "confidence": 0.0,
  "raw_excerpt": "verbatim snippet for audit"
}
```

### Prompt rules (important)

- **Extract only what is on the page** — no inventing NCT/EUCT.
- If ID missing, set null and lower `confidence`.
- Prefer Czech center names normalized to: `FN Motol`, `Homolka`, `VFN`, `Bulovka`, `Vinohrady`, …
- Output JSON only; keep `raw_excerpt` ≤ ~2k chars.
- Run with **EU Data Zone** model (`gpt-6-1-sol-dz-eu`); page text is not patient PHI but stay consistent with stack.

### Per-source adapters (thin)

| Source | Notes |
|--------|--------|
| Linkos KOC active studies | Diagnosis-grouped lists; Motol as checkbox/center label |
| Linkos KDHO paediatric list | Often has protocol names + “otevřená”; may lack NCT |
| klinicketesty.cz center pages | Often NCT-backed; still parse then prefer CT.gov |
| fnmotol.cz KH page | Usually **no trial list** — skip scrape, use coordinator |

Store adapter selectors in `data/trials_unstructured/adapters/*.yml` (css/xpath + example URL).

### Deduping logic (sketch)

```text
if nct_id in ctgov_studies → link
elif eu_ct_id in trials_search → link
elif fuzzy(title, sponsor/center) > threshold → queue review
else → manual / coordinator
```

---

## 4. Coordinator → contact & ask

For trials **only known inside the hospital** (or HTML stub without IDs).

### Who

| Org | Channel | Notes |
|-----|---------|--------|
| FN Motol OKH | `studie@fnmotol.cz` (start-up coordinators on [fnmotol.cz KH page](https://www.fnmotol.cz/o-nas/klinicke-hodnoceni-ve-fn-motol/)) | ~90 contracts/year; commercial + academic (CZECRIN) |
| Homolka science / clinical studies dept | Via Homolka “Klinické studie” / Motol–Homolka merge contacts | Oncology participates in multicentre Ph II/III; **no public list** |
| Challenge owners (Motol/Homolka oncology) | Hackathon channel | Ask for “currently recruiting at our KOC” export |

### What to ask for (one email template)

Subject: `Avicenna / Rakathon — recruiting oncology trials list (Motol & Homolka)`

Please send a spreadsheet (or PDF) of **currently recruiting** interventional trials at your site with columns:

1. Public title / acronym  
2. NCT number (if any)  
3. EU CT / EudraCT (if any)  
4. Phase  
5. Indication / cohort  
6. Principal investigator / study coordinator contact  
7. Whether inclusion/exclusion can be shared as protocol synopsis PDF  

We will match **only against anonymised hackathon data**, keep protocol files offline, and not republish confidential docs.

### After reply

```text
1. Save attachment → data/trials_manual/raw/{date}_{org}/
2. If CSV/XLSX → load to trials_manual table
3. If PDF/DOCX → LLM stub extract (same TrialStub schema) + human spot-check
4. Link NCT/EUCT into CT.gov/CTIS pulls
5. Mark rows source=coordinator, verified_by=, verified_at=
```

### Governance

- Do **not** commit protocol PDFs or emails with personal phones to public git.
- Prefer registry text for matching criteria once an ID exists.
- Coordinator-only trials: flag `public_registry=false` in UI (“site-confirmed”).

---

## 5. Unified matching feed (downstream)

Build a view / export `trial_card` for the matcher:

```text
trial_uid          = ctis:{eu} | ctgov:{nct} | manual:{uuid}
geo_rank           = Motol/Homolka > other Prague > Brno/Ostrava > CZ > EU > world
criteria_source    = ctis_retrieve > ctgov eligibility_text > llm_html > manual
sites              = from CTIS Part II or CT.gov locations
crosswalk          = nct ↔ eu_ct when known
```

---

## 6. Suggested next steps (hackathon)

1. Finish CTIS `retrieve --czechia` (if still running).  
2. ~~Run `ctgov_to_sqlite.py ingest` + `stats`~~ — done (~552 distinct NCT; Motol/Homolka flags).  
3. One Linkos page → LLM stub prototype (10 trials) to validate schema.  
4. Send Motol coordinator email once; import whatever they return as `trials_manual`.

---

## 7. References

- CTIS public portal: https://euclinicaltrials.eu/  
- CT.gov API v2: https://clinicaltrials.gov/data-api/api  
- Motol KH admin: https://www.fnmotol.cz/o-nas/klinicke-hodnoceni-ve-fn-motol/  
- Linkos active KOC studies: https://www.linkos.cz/lekar-a-multidisciplinarni-tym/personalizovana-onkologie/klinicke-hodnoceni-a-klinicky-vyzkum/aktivni-klinicke-studie/  
- Structure notes: `CTIS_TRIALS_STRUCTURE.md`, `IRIS_AVICENNA_BRIEF.md`

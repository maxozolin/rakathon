# Subagent task: atomize assigned trials into CriteriaPacks

You are acting as the LLM atomizer described in
`/home/crimson/dev/rakathon/prompts/TRIAL_PACK_BUILDER_PROMPT.md`. READ THAT FILE
FIRST — it is the normative spec. Also read the worked example
`/home/crimson/dev/rakathon/matcher/skills/trial-data-format/example_pack.json`
and the hand-authored demo `/home/crimson/dev/rakathon/matcher/packs/NCT06252649.json`.

## Your job
For each assigned trial id, produce ONE schema-valid
`avicenna.criteria-pack/0.1` JSON file at
`/home/crimson/dev/rakathon/matcher/packs/<TRIAL_ID>.json` and validate it.

## Where the input comes from
All input is PUBLIC registry text in the local catalog DB (read-only):
`/home/crimson/dev/rakathon/data/catalog/trial_catalog.sqlite`, table `trials`.
For each id query:
```
SELECT trial_id, registry, title, study_type, sex, min_age_years, max_age_years,
       conditions_json, inclusion_json, exclusion_json, last_update
FROM trials WHERE trial_id = '<ID>';
```
`inclusion_json` / `exclusion_json` are JSON arrays of eligibility bullets (already split).

## Hard rules (from the prompt — obey exactly)
1. Extract ONLY what the text states. Never import "typical" protocol values.
2. Never flip polarity: inclusion bullets -> `criterion_type:"inclusion"`,
   exclusion bullets -> `criterion_type:"exclusion"`.
3. `source_text` must be the bullet text verbatim (you may strip a leading
   bullet glyph/space). Use the whole bullet.
4. Opaque is a valid, SAFE output: a criterion you cannot safely encode has
   `"atoms": []` and `"completeness_note": "opaque_text"`. WHEN IN DOUBT, GO OPAQUE.
   A wrong atom is worse than an opaque one.
5. Output JSON only; validate it.

## What to encode as real atoms (only these safe patterns)
- **Structured min age** -> inclusion `inc:age-min`, atom
  `demographics.age ge {"value":<min>,"unit":"a"}`, completeness_note `complete`.
- **Structured max age** -> inclusion `inc:age-max`, atom
  `demographics.age le {"value":<max>,"unit":"a"}`, `complete`.
- **Structured single sex** (sex = male/female, NOT "all") -> inclusion
  `inc:sex`, atom `demographics.administrative_gender eq
  {"system":"http://hl7.org/fhir/administrative-gender","code":"male|female"}`, `complete`.
- **ECOG 0-1 / <=2 etc.** -> `performance.status le {"value":N,"unit":"{ECOG}"}`,
  `"relation":"at_screening"`, complete.
- **"measurable disease per RECIST"** -> `disease.recist_measurable eq true`, complete.
- **"metastatic"** -> `disease.metastatic eq true`. **"locally advanced"** ->
  `disease.locally_advanced eq true`.
- **Active/untreated brain metastases (exclusion)** ->
  `disease.cns_metastases eq true`, completeness_note `partial`,
  note "active/untreated not encoded".
- **Pregnant (exclusion)** -> `safety.pregnant eq true`, complete.
- **A named prior drug in a CLOSED list (exclusion "prior X or Y")** ->
  `logic:{"op":"not"}` over one `not_exists` atom, `fact_key:"therapy.event"`,
  `scope:{"time_extent":"lifetime","concepts":[lowercase INN,...],
  "ontology_version_pin":"avicenna-seed/1.0.0"}`. If the list is open ("e.g.",
  "such as", a drug CLASS) -> go OPAQUE.

Everything else (organ function, lab thresholds you are unsure of, disease codes
you are not certain map exactly, "adequate X", line counts, response/progression,
investigator judgment, consent, willingness, specific comorbidities without a
code you are sure of) -> **opaque criterion** (`atoms:[]`,
`completeness_note:"opaque_text"`).
Consent / willingness / "investigator's opinion" bullets ->
`"hardness":"procedural_pre_screen"`; all other criteria `"hardness":"hard"`.

## Envelope
```json
{
  "schema_version": "avicenna.criteria-pack/0.1",
  "pack_id": "<TRIAL_ID>@<last_update>/trial-pack-builder-llm/1.0.0",
  "trial_id": "<TRIAL_ID>",
  "criteria_completeness": "partial",
  "generated_at": "2026-10-17T00:00:00Z",
  "arms": [{"arm_id":"main","arm_name":"All participants","study_type":"<interventional|observational>"}],
  "criteria": [ ... ]
}
```
- `study_type`: map catalog `observational` -> `"observational"`, else `"interventional"`.
- Use `"criteria_completeness":"partial"` (safe default).
- Every criterion needs: `criterion_id` (unique, e.g. `inc:<slug>` / `exc:<slug>`),
  `criterion_type`, `hardness`, `arm_scope:null`, `source_text`, `atoms`,
  `completeness_note`. Multi-atom criteria also need `logic:{"op":"all|any|not","notes":null}`.
- Every atom needs `atom_id`, `predicate_type`, `arm_scope:null`, `source_text`,
  plus type fields. `biomarker.result`/`lab.result` atoms MUST carry `concept`.
  If you'd need to guess a code/unit/threshold, go opaque instead.

## Validate EVERY file (required)
From `/home/crimson/dev/rakathon/matcher`:
```
python -c "import json,sys; from avicenna_matcher.validator import validate; validate(json.load(open(sys.argv[1])),'criteria_pack'); print('VALID', sys.argv[1])" packs/<TRIAL_ID>.json
```
If it errors, FIX the JSON and re-run until it prints VALID. Do not leave invalid files.

## Report back
List each trial id with: VALID/FAILED, number of criteria, and number of
criteria with real atoms (non-opaque). Keep it short.

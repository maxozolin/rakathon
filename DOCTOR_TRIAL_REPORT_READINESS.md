# Doctor-facing trial shortlist: readiness and 20-minute delivery plan

## Executive decision

**We can aim to deliver a small, evidence-backed “trials to pursue / patients to review” report within 20 minutes. We cannot responsibly deliver a list of confirmed eligible patients from the current package and pilot results.**

The missing piece is not another large matching run. It is a clinically coherent connection between **currently available trial/site/arm**, **the patient's relevant disease episode and evidence**, and **specific unresolved screening requirements**.

Use these doctor-facing categories:

| Category | Meaning |
|---|---|
| **Priority for trial-team review** | Disease/setting and key available evidence plausibly fit; no supported disqualifier identified in the evaluated requirements. Important requirements may remain unresolved |
| **Possible candidate — obtain specified evidence** | A plausible disease-level fit with named, potentially decision-changing gaps |
| **Not supported by reviewed evidence** | A specific, evidence-backed failure of an applicable requirement, with uncertainty/context disclosed; not a definitive exclusion based on missing data |
| **Not assessable from this package** | Protocol opacity, missing disease/episode context, incompatible timing or other gaps prevent a useful recommendation |

`eligible_pending_review` means **modeled gates cleared**, not enrolled/eligible. It MUST NOT be displayed as “eligible.” A bare `needs_chart_review` result is not itself a recommendation: it can represent a strong candidate, an irrelevant trial or an opaque protocol.

This readiness report contains no patient identifiers, values or linked results and can be shared with models without patient access. The actual doctor-facing patient–trial report must remain inside the approved event/hospital boundary.

## What is available

- Local public CT.gov/CTIS catalogs with eligibility text and site/status metadata. These are snapshots, not verified live site availability.
- The supplied patient FHIR export; full upload was acknowledged by IRIS. Storage is ephemeral; acknowledgement is not independent reconciliation or durability.
- A deterministic matcher, canonical patient-packet adapter, explainable criterion outputs and synthetic regression tests.
- Local structural/candidate-coverage audit and small real-data experiments.
- Evidence that structured demographics and selected explicit narrative facts can be represented. The treatment pilots preserved performance scores, historical biomarkers and therapy evidence without fabricating missing information.

The larger run's useful positive demonstration was an **observational lymphoma registry**, not proof of treatment-trial eligibility. Treatment pilots remained predominantly manual review because criteria, patient facts and temporal context were incomplete. Those labels do not demonstrate that patients are unsuitable.

The referenced code/test status is an operational snapshot. None of these activities established clinical sensitivity, specificity, a calibrated eligibility probability or clinician-adjudicated gold labels.

## Missing requirements and delivery blockers

| Missing item | Why it matters | Minimum action in the next 20 minutes |
|---|---|---|
| **Active site/arm availability** | Registry-wide recruiting does not prove the relevant Prague/Motol/Homolka cohort is open | Inspect trial and site status, snapshot/retrieval date, arm/cohort; flag coordinator confirmation required. Do not call a trial “open locally” without supporting site evidence |
| **Relevant primary disease and current setting** | A code may be generalized, historical or unrelated to the target episode; breast diagnosis alone does not establish metastatic HR+/HER2− disease | Manually review a few coherent cases; link the disease, histology, state and treatment setting. Preserve conflicts and suppressed precision |
| **Faithful trial gate packs** | Largely opaque packs cannot differentiate a close treatment fit from an irrelevant one | Curate the selected trial's decisive gates from full source text; retain every remaining requirement as visible unresolved. Do not invent standard lab cutoffs or soften hard criteria |
| **Decision-changing patient facts** | ECOG, assay-specific markers, prior agents/setting, recurrence/progression and safety often control candidacy | Extract only explicit evidence for the selected pairs; keep evidence pointers, clinical dates and unknowns. Avoid an exhaustive all-patient extraction attempt |
| **Valid evaluation time** | Source dates are shifted; null anchor and unbounded recency currently leave screening predicates unresolved | Keep real screening freshness unresolved. For a demonstration, use only a separately agreed, caller-supplied shifted historical context, clearly labeled—not a backdated screening claim |
| **Validated units/assays/concepts** | A displayed number or marker label can have incompatible meaning | Use only existing validated mappings. Otherwise retain original evidence and state “requires normalization/confirmation.” Do not manually guess LOINC, UCUM conversions or assay equivalence |
| **Prior-therapy absence/reconciliation** | Missing events do not prove no prior excluded drug or treatment | Completeness remains empty; use only scoped explicit negatives when documented. Tell the doctor exactly which history needs reconciliation |
| **Review priority logic** | A high score or one top-level state conceals important missing gates | Rank disease/setting fit, source-supported key facts, site practicality and feasible next checks separately from eligibility. Disclose supported failures and unresolved hard requirements |
| **Clinical and technical sanity review** | A correct-looking packet can still misattribute a marker, invert an exclusion or select historical evidence | Review the final small set against original local evidence and verbatim criteria; verify input/output structure and temporal semantics |
| **Usable delivery and ownership** | A raw JSON result does not help a doctor act | Produce a short local report with patient pseudonym, trial ID/site, evidence, blockers, next action and confirmation owner; arrange authorized delivery, not public sharing |

### Especially important in this dataset

- Deliberately suppressed/generalized age and diagnosis precision cannot be recovered from narrative.
- Report metadata time and encounter/effective time can differ.
- A recent note can repeat old biomarker, stage or treatment history.
- Biomarker results must stay linked to disease, specimen, assay and time; ER protein status is not ESR1 mutation status.
- Prescription/billing/planned therapy is not necessarily administration, a line number or complete lifetime treatment history.
- Generic “labs normal,” test orders, remission, local-recurrence negatives and organ-specific negatives cannot become precise screening measurements or universal disease absence.
- RECIST, tissue, current pregnancy/reproductive status and study consent may require new assessment or confirmation outside this export.

## Minimum doctor-facing report

**Title:** “Pre-screening trial opportunities — clinician and study-team review required.”

Header MUST state source snapshot, preparation time, evaluated scope, shifted-date limitation and confidentiality. Separate treatment opportunities from observational registries. Include no heuristic probability as if clinically calibrated.

For each recommended pair, provide:

| Field | Required content |
|---|---|
| Patient reference | Local pseudonym resolvable by the authorized clinician; never a name in shared artifacts |
| Trial | Registry ID, title, treatment/research type, phase and relevant arm |
| Site / availability | Actual relevant site, registry/site status and retrieval date; coordinator verification status |
| Why pursue | Explicit disease/setting fit and a small number of evidence-backed key facts, with local source references |
| Important failures | Any supported hard failure, with criterion source and patient evidence. Do not hide it under a relevance score |
| Missing / conflicting | Criterion-specific gaps, including whether evidence is absent, unextracted, stale, unsupported, conflicting or protocol-defined |
| Matcher status | Exact authoritative state with plain-language explanation; no bare “eligible” |
| Recommendation | Priority review / obtain evidence / not supported / not assessable, with the rationale |
| Next action | Specific question/test/reconciliation/coordinator contact, assigned owner and sequence |

Suggested wording:

> “Worth reviewing with the study team because the documented disease context and selected available facts align with the listed requirements. Eligibility is unconfirmed. Before referral/enrollment, verify the following outstanding requirements: …”

For modeled positive results:

> “All evaluated modeled gates cleared; additional protocol, consent, site and current screening review is required. This is not confirmed eligibility.”

Do not label a missing-code control “close” merely because the engine did not reject it. A recommendation needs positive relevance evidence. Do not report a patient–trial count as a clinical yield estimate.

## Twenty-minute execution plan

Time-boxed plan, not a promise of verified clinical conclusions:

| Time | Action | Deliverable |
|---|---|---|
| **0–3 min** | Select a narrow disease/setting and a few recruiting local trial/cohort candidates; inspect current stored site/status metadata | Small candidate set with availability caveats |
| **3–8 min** | Manually review a few patient cases for primary disease/episode, explicit performance/biomarker facts and relevant therapy evidence | Evidence-linked packets; uncertain facts remain unknown |
| **8–13 min** | Faithfully structure decisive criteria; preserve all residual gates as unresolved; validate and run matcher | Criterion-level outputs with no invented anchors or completeness |
| **13–17 min** | Review contradictions, failures and decision-changing missing evidence; prioritize actions | A small actionable shortlist, not a mass “eligible” list |
| **17–20 min** | Assemble and sanity-check the local doctor report; confirm authorized recipient/delivery | Confidential review report with concrete next steps |

If the timeline slips, reduce the number of pairs instead of dropping eligibility requirements. If no disease-coherent actionable pair can be supported, deliver a clear evidence-gap report and the next checks needed—not a fabricated positive list.

**Do not spend the deadline on:** full-cohort reprocessing, changing model infrastructure, forcing packets to be complete, deriving therapy lines without evidence, or presenting opaque criteria as passed.

## What would improve usefulness after this deadline

1. Clinician-reviewed candidate and exclusion labels, including apparent misses, to measure extraction and matching errors.
2. Faithfully curated trial/arm packs and ongoing availability updates.
3. Local clinical extraction with specimen/episode/negation/time handling and validated mappings.
4. Authorized treatment-history reconciliation with scope and provenance.
5. A versioned ranking/review policy based on decision-changing gaps and practical review effort.
6. Scoped application identities, verified restart/persistence strategy and event retention controls.

## Release checks and limitations

Before handing the actual report to a doctor:

- [ ] Every recommended pair has positive disease/setting relevance evidence, not merely no rejection.
- [ ] Trial/site/arm status and its verification limitations are visible.
- [ ] All relevant hard requirements are represented or explicitly unresolved; no favorable partial graph hides omissions.
- [ ] Patient facts resolve to local source evidence and retain generalization, time, assay and subject context.
- [ ] No missing fact became an explicit negative, not-tested, or completeness assertion.
- [ ] Shifted dates are not presented as real screening recency; no automatic “today” anchor.
- [ ] Supported disqualifiers, contradictions and unassessed requirements are visible.
- [ ] Treatment and observational participation are clearly separated.
- [ ] No calibrated probability, confirmed eligibility or consent is claimed without evidence.
- [ ] The report is delivered only within the approved boundary to an authorized recipient; sensitive copies/logs follow retention rules.

**Conclusion:** the fastest useful product is a small, transparent **review-and-action report**. The doctor should be able to see why each opportunity is worth pursuing, what could block it, and what to verify next. The current engine and package support parts of this workflow, but they do not yet support an honest fully automatic treatment-eligibility report.

Sources: current matcher implementation/design, patient/trial builder prompts, `reports/LARGER_BATCH_ENGINE_FINDINGS.md`, `reports/TARGETED_TREATMENT_ENGINE_FINDINGS.md`, and the authorized prior dataset audits. This report introduces no new patient-level findings and does not independently verify live site recruitment or clinical eligibility.

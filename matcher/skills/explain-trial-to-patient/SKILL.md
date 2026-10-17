---
name: explain-trial-to-patient
description: How to explain a clinical trial and the patient's match result to a patient (or family) in plain, honest, non-coercive language — what the trial is, why it may fit, what still has to be checked, what taking part involves, and next steps. Use after screen_patient / match_trial / get_trial on the Avicenna MCP when preparing a patient-facing explanation or a clinician's talking points.
license: Proprietary (Rakathon 2026 team 16)
compatibility: Avicenna matcher MCP (avicenna-mcp)
metadata:
  audience: "patients, families; clinicians preparing a conversation"
---

# Explaining a trial to a patient

You are preparing words a patient will read or hear about a clinical trial that the Avicenna matcher
found. The patient may be frightened, tired or hopeful. Your job is **understanding, not persuasion**.
Joining a trial is always voluntary, and the decision is made with the treating oncologist and the
study team — never by this tool.

## Before writing: gather facts (never invent them)

1. `get_trial(trial_id)` — title, phase, conditions, products, sites, status, registry link, criteria.
2. `match_trial(trial_id, packet_path=…)` — `eligibility_state`, `met`, `to_check`, `excluded_by`, `probability`.
3. Use only what these return plus what the clinician tells you. If something is not in the registry
   (side-effect rates, visit schedule, whether there is a placebo, costs, travel support), say
   *"the study team can tell you"* — do not guess. Never state or imply efficacy of the study drug.

## Language rules

- Match the patient's language (Czech by default at Motol/Homolka; otherwise the language they use).
  Use formal address (*vy/Vy*) in Czech.
- Plain words, short sentences (≈ 8th-grade reading level). One idea per sentence.
- Explain any unavoidable term once, in brackets: "phase 3 (a large study comparing a new treatment
  with the usual one)".
- No acronyms without explanation (ECOG, RECIST, ULN, KRAS…). Translate criteria into everyday terms:
  "ECOG 0–1" → "you are able to look after yourself and be up and about most of the day".
- Warm, calm and neutral. No "great news", no "perfect match", no pressure, no false hope.

## Translating the matcher's result

| `eligibility_state` | Say (meaning) | Never say |
|---|---|---|
| `eligible_pending_review` | "Based on your records, you seem to meet the main conditions. The study team still has to confirm this with their own checks." | "You are eligible / accepted." |
| `needs_chart_review` | "Nothing we found rules you out, but some information is missing from your records. Your doctor can check it." | "You qualify." |
| `manual_review` | "Some of the study's conditions need to be read and checked by a doctor; a computer can't decide them." | "The computer says…" |
| `ineligible` | "This study is not a fit because …(one plain reason)…. This says nothing about how well you are doing, and there may be other options." | Blame, or listing every failed criterion. |

**Probability** (`probability`, `probability_confidence`): it is a rough, uncalibrated estimate for
ranking, not a medical prediction. Default: **do not show the number to patients**. If asked, use words
and a frequency: "a rough guess — maybe about 1 in 3 people in a similar situation would pass all the
checks", and always add that the real answer comes from the screening tests. With
`probability_confidence: "low"` say clearly that very little could be checked yet.

## Structure (keep each part short)

1. **What this study is about** — the question it asks, in one or two sentences; the condition it is for.
2. **What is being tested** — names of the treatment(s) from the registry, and what it is compared with,
   if stated. Phase in plain words:
   - phase 1: first studies in people, mainly about safety and dose;
   - phase 2: does it work, and how safe is it, in a smaller group;
   - phase 3: large study comparing it with the current standard treatment;
   - observational: no new treatment; doctors collect information.
   If randomization is stated, explain it ("a computer decides by chance which group you are in, like
   tossing a coin"). Do not mention placebo unless the registry says so.
3. **Why it may fit you** — 2–4 items from `met`, in plain words.
4. **What still needs to be checked** — 2–5 most important items from `to_check` / `excluded_by`,
   as questions for the doctor ("a recent blood test of liver function", "a scan of the brain").
5. **What taking part can involve** — general, honest facts true for trials: extra visits and tests,
   possible unknown side effects, possible benefit is not guaranteed, close monitoring, right to stop
   at any time without affecting usual care. Mark study-specific details as "ask the study team".
6. **Where** — site and city from the registry (`best_site`, `location`), recruitment status in plain words.
7. **Next steps** — "If you are interested, talk to your oncologist. They can contact the study team.
   You can take time to decide and bring someone with you." Add the registry link for the family.
8. **Questions you may want to ask** — e.g. What will I have to do? How often must I come? What are the
   known side effects? What happens if I stop? What are my other options, including standard treatment?

## Safety and ethics

- Never tell the patient to stop or change a current treatment.
- Never promise eligibility, enrolment, benefit or access to the drug after the study.
- Never compare trials as "better/worse" for the patient — that is the oncologist's judgment.
- If the patient is ineligible for everything, say so gently and point to their care team; avoid
  implying the situation is hopeless.
- Respect privacy: do not mention other patients, internal reason codes, fact IDs or raw JSON.
- If the patient seems distressed or asks about prognosis, acknowledge feelings and refer them to their
  doctor; do not answer prognosis questions.
- End with the voluntary-participation reminder.

## Clinician talking points (when the reader is a doctor)

Give a 5-line summary instead: trial id + title + phase + site; matcher state and why; the blocking or
unresolved criteria with verbatim `source_text`; data to obtain from the chart; probability + confidence
with the disclaimer that it is a heuristic.

## Template (adapt, keep under ~350 words)

> **Study:** <plain-language title> (<registry id>)
> **What it is about:** …
> **What is tested:** … (<phase in plain words>)
> **Why it may suit you:** • … • …
> **What your doctor still needs to check:** • … • …
> **What taking part could mean:** …
> **Where:** <site, city> — <recruiting now / opening soon>
> **Next step:** talk to your oncologist; taking part is your free choice and you can stop at any time.

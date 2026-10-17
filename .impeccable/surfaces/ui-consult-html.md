---
version: 1
slug: "ui-consult-html"
primary_target: "ui/consult.html"
related_targets: []
---

# Consult view: one patient, candidate trials

Scope: `ui/consult.html`, a static HTML/CSS mock. Visitor mode: Operate. Build path: code-led.

Audience and job: a treating oncologist in a consult checks which atomized trials are plausible for one patient, what blocks each one, and what to check next. They then refer the patient to the trial coordinator. Data is synthetic only (`matcher/tools/mock_patient_demo.py`).

## Direction contract

THESIS: The patient's trial options read like a cumulative lab report. Each trial is a panel, each criterion is a row, and each row carries a flag. The category default is a card grid of trials with match-percentage scores; this surface refuses that.

OWN-WORLD:
- Cool clinical paper ground with an ink-blue shell header.
- Hairline-ruled, zebra-banded flowsheet rows.
- State inks used only for meaning: green = met, red = disqualifies, hatched amber = unresolved, grey = not applicable.
- One reserved blue for the selected trial and the primary action.
- A single system sans throughout, with tabular numerals.

STORY: The oncologist sees in seconds which trials are plausible. They believe the verdict because every row shows the registry wording, the evidence and the reason. Then they do one thing: refer to the coordinator, or first check the listed items.

FIRST VIEWPORT:
- Desktop: patient strip; trial rail (flag strip plus verdict word) with a flag legend; then the selected trial's verdict sentence, its "check before referral" list and the criteria flowsheet. Primary action top-right.
- Mobile: a compact patient strip, and the verdict above the fold, with actions in a fixed bottom bar.

FORM: cumulative lab report (laboratory flowsheet), candidate 5 of 7 on the ordered list. seed:92461fa9c227651d

SIGNATURE: the flag column and the flag strip. Every criterion row starts with an authored-SVG flag cell. Each trial in the rail shows its criteria as one strip of flag cells, so the whole report can be read at a glance.

RAISES:
- Reserved active colour (orienteering).
- Tabular-numeral discipline (Ikeda).
- A persisted per-row "checked" mark (convention catalog).

RISK: dense and calm; it may read as a report before it reads as a dashboard.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

---
name: Avicenna Trial Pre-screen
description: A cumulative lab report for one patient against candidate trials, where unknown stays visibly unknown.
colors:
  paper: "oklch(0.984 0.004 230)"
  paper-2: "oklch(0.958 0.008 235)"
  band: "oklch(0.968 0.006 232)"
  rule: "oklch(0.885 0.01 240)"
  rule-strong: "oklch(0.78 0.015 245)"
  ink: "oklch(0.24 0.03 252)"
  ink-2: "oklch(0.42 0.025 250)"
  ink-3: "oklch(0.52 0.02 250)"
  shell: "oklch(0.31 0.055 252)"
  shell-ink: "oklch(0.97 0.01 240)"
  shell-ink-2: "oklch(0.84 0.03 245)"
  shell-rule: "oklch(0.40 0.05 252)"
  accent: "oklch(0.50 0.16 256)"
  accent-ink: "oklch(0.42 0.15 256)"
  accent-tint: "oklch(0.945 0.03 256)"
  met: "oklch(0.46 0.11 152)"
  met-tint: "oklch(0.935 0.045 152)"
  fail: "oklch(0.50 0.18 27)"
  fail-tint: "oklch(0.94 0.04 27)"
  open: "oklch(0.50 0.11 68)"
  open-fill: "oklch(0.80 0.13 80)"
  open-tint: "oklch(0.955 0.05 85)"
  na: "oklch(0.55 0.012 250)"
  na-tint: "oklch(0.94 0.005 250)"
  on-accent: "oklch(1 0 0)"
  selection: "oklch(0.86 0.07 256)"
  shell-deep: "oklch(0.25 0.045 252)"
  shell-field: "oklch(0.36 0.055 252)"
  shell-field-hover: "oklch(0.39 0.055 252)"
  shell-field-rule: "oklch(0.46 0.05 252)"
  shell-field-rule-hover: "oklch(0.6 0.05 252)"
  hover: "oklch(0.935 0.01 240)"
  accent-press: "oklch(0.38 0.14 256)"
  open-hatch: "oklch(0.9 0.08 85)"
  open-edge: "oklch(0.82 0.1 80)"
  open-edge-strong: "oklch(0.7 0.12 75)"
  accent-on-ink: "oklch(0.85 0.06 256)"
typography:
  headline:
    fontFamily: "\"Segoe UI Variable Text\", \"SF Pro Text\", system-ui, -apple-system, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 680
    lineHeight: 1.2
    letterSpacing: "-0.015em"
  title:
    fontFamily: "\"Segoe UI Variable Text\", \"SF Pro Text\", system-ui, -apple-system, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: "-0.012em"
  verdict:
    fontFamily: "\"Segoe UI Variable Text\", \"SF Pro Text\", system-ui, -apple-system, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 680
    lineHeight: 1.5
    letterSpacing: "-0.01em"
  section:
    fontFamily: "\"Segoe UI Variable Text\", \"SF Pro Text\", system-ui, -apple-system, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 650
    lineHeight: 1.5
  body:
    fontFamily: "\"Segoe UI Variable Text\", \"SF Pro Text\", system-ui, -apple-system, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "\"tnum\" 1"
  body-sm:
    fontFamily: "\"Segoe UI Variable Text\", \"SF Pro Text\", system-ui, -apple-system, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "\"tnum\" 1"
  label:
    fontFamily: "\"Segoe UI Variable Text\", \"SF Pro Text\", system-ui, -apple-system, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1.35
  caption:
    fontFamily: "\"Segoe UI Variable Text\", \"SF Pro Text\", system-ui, -apple-system, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.5
  code:
    fontFamily: "ui-monospace, \"SF Mono\", \"Cascadia Mono\", Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  hair: "1px"
  xs: "2px"
  sm: "3px"
  md: "4px"
spacing:
  "3xs": "2px"
  "2xs": "0.25rem"
  xs: "0.375rem"
  sm: "0.5rem"
  md: "0.75rem"
  lg: "1rem"
  xl: "1.25rem"
  "2xl": "1.5rem"
  "3xl": "2rem"
  "4xl": "3rem"
components:
  shell:
    backgroundColor: "{colors.shell}"
    textColor: "{colors.shell-ink}"
    padding: "0.625rem 1.5rem"
  synthetic-band:
    backgroundColor: "oklch(0.25 0.045 252)"
    textColor: "{colors.shell-ink-2}"
    typography: "{typography.caption}"
    padding: "0.3rem 1.5rem"
  patient-select:
    backgroundColor: "oklch(0.36 0.055 252)"
    textColor: "{colors.shell-ink}"
    rounded: "{rounded.md}"
    padding: "0.3rem 1.9rem 0.3rem 0.6rem"
  patient-strip:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    padding: "1.25rem 1.5rem 1.125rem"
  trial-rail:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink}"
    width: "21.5rem"
    padding: "1rem 0 2rem"
  trial-link:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink}"
    padding: "0.875rem 1.25rem 0.9375rem"
  trial-link-hover:
    backgroundColor: "oklch(0.935 0.01 240)"
  trial-link-current:
    backgroundColor: "{colors.accent-tint}"
    textColor: "{colors.accent-ink}"
  flag-strip-cell:
    width: "0.4375rem"
    height: "0.875rem"
    rounded: "{rounded.hair}"
  verdict-panel:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    padding: "1.25rem 0 1.375rem"
  verdict-word:
    typography: "{typography.verdict}"
  check-next-item:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0.45rem 0.5rem"
  check-next-item-hover:
    backgroundColor: "{colors.band}"
  flowsheet-header:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink-2}"
    typography: "{typography.caption}"
    padding: "0.5rem 0.75rem"
  flowsheet-row:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    padding: "0.625rem 0.75rem"
  flowsheet-row-band:
    backgroundColor: "{colors.band}"
  flowsheet-row-target:
    backgroundColor: "{colors.accent-tint}"
  flag-ok:
    backgroundColor: "{colors.met-tint}"
    textColor: "{colors.met}"
    rounded: "{rounded.sm}"
    size: "1.75rem"
  flag-open:
    backgroundColor: "{colors.open-tint}"
    textColor: "{colors.open}"
    rounded: "{rounded.sm}"
    size: "1.75rem"
  flag-fail:
    backgroundColor: "{colors.fail}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    size: "1.75rem"
  flag-na:
    backgroundColor: "{colors.na-tint}"
    textColor: "{colors.na}"
    rounded: "{rounded.sm}"
    size: "1.75rem"
  segmented-filter:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.md}"
    padding: "2px"
  segmented-filter-option:
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "0.3rem 0.7rem"
  segmented-filter-selected:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "0.5rem 0.875rem"
  button-primary-hover:
    backgroundColor: "{colors.accent-ink}"
  button-primary-active:
    backgroundColor: "oklch(0.38 0.14 256)"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0.5rem 0.875rem"
  button-secondary-hover:
    backgroundColor: "{colors.paper-2}"
  button-secondary-active:
    backgroundColor: "{colors.rule}"
  disclosure-link:
    textColor: "{colors.accent-ink}"
    typography: "{typography.caption}"
    rounded: "{rounded.xs}"
  mobile-action-bar:
    backgroundColor: "oklch(0.984 0.004 230 / 0.96)"
    padding: "0.625rem 1rem"
  status-toast:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.md}"
    padding: "0.5rem 0.75rem"
---

# Design System: Avicenna Trial Pre-screen

## Overview

**Creative North Star: "The Cumulative Lab Report"**

The screen reads like the cumulative results sheet a clinician already trusts: a dark institutional header, a patient strip, then a ruled flowsheet where every criterion is a row with a flag in its own column, the source wording, the evidence with its date and provenance, and the assessment. Nothing is a card and nothing floats. Hierarchy comes from rules, bands and type weight on cool paper, the way a printed lab report separates sections with hairlines rather than boxes.

Density is clinical: 15px body, 14px table text, tabular figures everywhere, generous line height, and tight but regular vertical rhythm. Colour is reserved for state. The four outcome inks (met green, disqualifier red, unresolved amber, not-blocking grey) are the only saturated hues besides the single blue used for interaction and selection. Unknown is drawn, not implied: an unresolved criterion carries a question glyph in the flowsheet and a hatched cell in every flag strip, so it never reads as either a pass or a fail.

The signature is the flag strip: one small cell per criterion, inclusion criteria first, a gap, then exclusion criteria, in trial order. It appears in each trial rail entry and, larger, in the verdict panel, so a clinician can compare the shape of three trials at a glance before reading a word.

**Key Characteristics:**
- Ruled flowsheet, not cards: hairline rules and alternate row bands carry structure.
- Four state inks, each paired with a glyph, and a hatched fill for unresolved.
- One interaction blue for links, focus, primary action and current selection.
- Flat surfaces; depth only from the dark shell, the paper-2 rail and three small functional shadows.
- Tabular figures and dated, sourced evidence on every row.

## Colors

A cool, low-chroma paper-and-ink palette under a deep navy shell, with saturated colour held back for state and the one action blue.

### Primary
- **Chart Blue** (`accent`): the only interaction colour. Primary button fill, focus outline (2px, 2px offset), caret, checkbox accent, current trial ring, and text-selection hue.
- **Deep Chart Blue** (`accent-ink`): link and disclosure text, the current trial's name, primary button hover. 8.2:1 on paper.
- **Blue Wash** (`accent-tint`): background of the current trial in the rail and of a flowsheet row jumped to from the check-next list.

### Secondary (state inks)
- **Met Green** (`met`) on **Met Wash** (`met-tint`): criterion met or exclusion ruled out on recorded evidence; the "Eligible, pending review" verdict word.
- **Disqualifier Red** (`fail`) on **Disqualifier Wash** (`fail-tint`): recorded evidence disqualifies. The flowsheet flag inverts to a solid red tile with a white cross so the one decisive state is the heaviest mark on the page.
- **Unresolved Amber** (`open`) with **Hatch Amber** (`open-fill`) and **Amber Wash** (`open-tint`): a person must check. `open` is the text and glyph ink (5.9:1 on paper); `open-fill` exists only to draw the hatching in strips.
- **Screening Grey** (`na`) on **Grey Wash** (`na-tint`): non-blocking or not applicable; checked at screening.

### Neutral
- **Report Paper** (`paper`): page ground, main column, table header and patient strip.
- **Rail Paper** (`paper-2`): the trial rail, segmented-filter trough, code chips and the engine-notes block.
- **Row Band** (`band`): every second flowsheet row and the check-next hover.
- **Hairline** (`rule`) and **Section Rule** (`rule-strong`): row dividers versus section, table-head and control borders.
- **Report Ink** (`ink`), **Secondary Ink** (`ink-2`, 7.5:1 on rail paper), **Muted Ink** (`ink-3`, 5.3:1 on paper): text tiers. `ink-3` is for counts, the legend footnote, empty evidence and reviewed-row text only.
- **Navy Shell** (`shell`) with `shell-ink`, `shell-ink-2` and `shell-rule`: the institutional header. A darker synthetic-data band sits above it.

### Named Rules
**The State Ink Rule.** Green, red, amber and grey mean criterion or verdict state and nothing else. They are never decoration, never a brand accent, never a section colour.

**The Never By Colour Alone Rule.** Every state ink travels with a glyph (check, cross, question, dash) and a word. A flowsheet flag without its glyph, or a verdict without its word, is a defect.

**The One Blue Rule.** Interaction and selection share one hue. Nothing else on the page is blue.

## Typography

**Display Font:** none; the system UI stack (Segoe UI Variable Text, SF Pro Text, system-ui, then Roboto, Helvetica Neue, Arial) carries every role.
**Body Font:** the same stack, with tabular numerals enabled on `body`.
**Label/Mono Font:** ui-monospace, SF Mono, Cascadia Mono, Consolas for criterion IDs, reason codes and engine notes.

**Character:** a single neutral sans used at many precise weights (400 to 680), like the typeset body of a lab report. Hierarchy comes from weight and size steps of roughly one sixteenth of a rem, never from a second family.

### Hierarchy
- **Headline** (680, 1.5rem, 1.2, -0.015em): the selected trial's short name. One per screen.
- **Title** (650, 1.375rem, 1.25, -0.012em; 1.125rem under 860px): the patient summary in the patient strip.
- **Verdict** (680, 1.25rem, -0.01em): the verdict word with its 1.25rem glyph in the verdict panel.
- **Section** (650, 1.0625rem): flowsheet title. Sub-sections ("Check before referral", notes headings) step down to 650 at 0.875rem.
- **Body** (400, 0.9375rem, 1.5, tabular): lede and regimen lines, capped at 52 to 70ch.
- **Body small** (400, 0.875rem): flowsheet cells, patient facts (values at 550), check-next text.
- **Label** (600, 0.8125rem): verdict words in the rail, rail and legend headings, filter options (550), registry line.
- **Caption** (400 to 600, 0.75rem): table head (600), evidence date and source, criterion meta, counts.

### Named Rules
**The Tabular Rule.** Figures are tabular everywhere (`font-variant-numeric: tabular-nums` on body), so counts, dates and ECOG values align down a column.

**The Weight Ladder Rule.** Emphasis is a weight step (550, 600, 620, 650, 680), not colour, italics or capitals. Sentence case throughout; no uppercase labels.

## Layout

A full-width report, not a centred page. Top to bottom: synthetic-data band, navy shell (brand, anchor date, policy version, patient select), patient strip, then a two-column workspace: a fixed 21.5rem trial rail on rail paper and a fluid main column (`minmax(0, 1fr)`, padding 1.5rem 2rem 3rem).

The main column stacks: trial head (title, regimen, registry line, actions right-aligned), the verdict panel as a two-column grid (verdict and coverage strip left, check-next list right, ratio 1 : 1.15) bounded by hairlines above and below, the flowsheet bar (title plus segmented filter), the flowsheet table, and a notes grid (`auto-fit, minmax(18rem, 1fr)`) under a section rule.

Flowsheet columns: flag 2.25rem, criterion 38%, evidence 23%, assessment 26%, checked 4.5rem centred. Inclusion and exclusion are separated by group header rows.

Spacing steps cluster on 0.125rem multiples: 2px, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1, 1.25, 1.5, 2 and 3rem. Horizontal page gutter is 1.5rem (1rem on mobile); row padding 0.625rem 0.75rem.

**Breakpoints.**
- **≤1080px:** the verdict panel stacks to one column; anchor and policy leave the shell.
- **≤860px:** single column. The rail becomes a horizontal scroll-snap row of trial entries (`min(19rem, 84vw)` each) with population and counts hidden. The flowsheet head disappears and each row becomes a three-column grid (flag, stacked criterion/evidence/assessment, checkbox). The legend and the patient gap note hide, patient facts cap at three, and the actions move to a fixed bottom action bar with a dark status toast above it.

## Elevation & Depth

Flat by default. Depth is tonal: the navy shell is the only dark plane, the rail sits one step down on rail paper, and alternate row bands give the table its grain. Inset 1px rings stand in for borders where a box must not shift layout (current trial, unresolved flags, n/a strip cells, selected filter).

### Shadow Vocabulary
- **Button lift** (`box-shadow: 0 1px 2px oklch(0.3 0.08 256 / 0.25)`): primary button only; removed when disabled.
- **Selected segment** (`box-shadow: 0 1px 2px oklch(0.3 0.03 250 / 0.14), 0 0 0 1px var(--rule)`): the chosen option inside the segmented filter.
- **Bottom bar** (`box-shadow: 0 -4px 12px oklch(0.3 0.03 250 / 0.08)`): the fixed mobile action bar, separating it from scrolling content.

### Named Rules
**The Ruled Not Boxed Rule.** Sections are separated by hairlines and bands, never by floating cards or drop shadows. Shadows exist only on the three controls above.

## Shapes

Square-shouldered and small-radius. Controls, buttons, toasts and the check-next hit area use 4px; flags and filter segments 3px; code chips, focus outlines and disclosure buttons 2px; strip cells 1px. Nothing is pill-shaped or circular. Rules are 1px. The flag is a 1.75rem square tile; the strip cell is a 0.4375rem by 0.875rem bar (1.125rem tall and up to 1.75rem wide in the verdict panel). Icons are 16-unit line SVGs, 1.75 stroke (2 to 2.25 inside flags and the verdict), round caps and joins.

## Components

### Shell
- **Character:** an institutional header, quiet and dark.
- **Structure:** navy `shell` bar with a 1px `shell-rule` bottom edge; brand ("Avicenna", 650 at 1rem, with "Trial pre-screen" in `shell-ink-2`), an inline anchor/policy definition list, and the patient select. Above it, a darker synthetic-data band in caption type.
- **Patient select:** raised navy field (`oklch(0.36 0.055 252)`), 1px `oklch(0.46 0.05 252)` border, 4px radius, custom chevron; hover lifts border and fill one step over 150ms.

### Patient strip
- **Character:** the report's identity block.
- **Structure:** title-size patient summary, synthetic ID in `ink-2`, a wrapping row of label/value facts (values at 550), and an amber gap note with a circled-exclamation glyph naming fields absent from the record. Bottom hairline.

### Trial rail with flag strip
- **Character:** a list of candidate trials, sorted by verdict then by share of met criteria.
- **Entry:** short name (620), registry ID, population line, then a foot row with the verdict word (glyph plus label, in its state ink) and the flag strip; a caption line of counts ("15 criteria: 11 met · 4 open"). Entries are separated by top hairlines.
- **Hover:** fill shifts to `oklch(0.935 0.01 240)` over 150ms.
- **Current:** `aria-current="page"`, `accent-tint` fill with a full 1px inset ring in accent at 45% alpha, and the name in `accent-ink`. Never a side stripe.
- **Flag strip:** one cell per criterion in trial order, 2px gaps, a wider empty gap between inclusion and exclusion. Met is a solid green cell; disqualifier solid red; unresolved a 135° hatch of `open-fill` and a pale amber (2px bands) inside an amber ring; n/a an empty cell with a `rule-strong` outline. The strip is `aria-hidden`; the verdict word and counts line (the coverage sentence in the verdict panel) carry the same information in text.
- **Legend:** "Reading the flags" under the rail: the four flowsheet flags beside plain definitions, plus a footnote explaining strip order. Hidden on mobile.

### Verdict panel
- **Character:** the answer, stated once, with its caveat.
- **Structure:** verdict word at verdict size with glyph, in its state ink; a one-sentence lede in `ink`; the large flag strip with a coverage sentence ("11 of 15 applicable criteria assessed from the record"); then a caveat in `ink-2` stating that the best result is "eligible, pending review" and the trial site decides.
- **Verdict vocabulary:** "Eligible, pending review" (green, check), "Needs chart review" and "Manual review" (amber, question), "Ineligible" (red, cross).

### Check-next list
- **Character:** next action over score.
- **Structure:** an ordered list headed by the action ("Check before referral", "Why it is ruled out", "Find in the chart", "Confirm at screening"). Each item is a full-width button: counter number, the criterion wording clamped to three lines with the trial's own words underlined, the criterion ID, and a right-aligned reason tag in amber or red.
- **Behaviour:** hover fills `band`; click resets the filter if needed, scrolls the matching flowsheet row to centre (instant under reduced motion), tints it `accent-tint` and focuses its Details control.

### Flowsheet table with flag column
- **Character:** the cumulative results sheet itself.
- **Head:** sticky, paper ground, caption type at 600 in `ink-2`, `rule-strong` bottom rule; the evidence column states the anchor date.
- **Group rows:** "Inclusion" / "Exclusion" at 650 with "n of m" in caption, over a `rule-strong` rule.
- **Rows:** hairline dividers, every second row on `band`, top-aligned cells. Columns: flag tile; criterion (full parent wording in `ink-2` with the atomized span underlined in `ink` at 560, ID and a "Details" disclosure below); evidence (value at 560, then date, source and "Reviewed" or "Unreviewed"); assessment (state-ink title, then plain reason in `ink-2`); "Checked" checkbox in a 2.25rem hit area.
- **Flag tiles (1.75rem, 3px):** met is green check on green wash; unresolved is amber question on amber wash with an inset amber ring; disqualifier is a white cross on solid red; not blocking is a grey dash on grey wash. Each includes a visually hidden word.
- **Details row:** a hidden full-width row (indented 2.25rem) with three auto-fit blocks: engine result (criterion, outcome, reason code and category, hardness), checkable parts, and facts used, in caption type with monospace code chips on rail paper.
- **Empty view:** centred `ink-2` message with a "Show All Criteria" text button.

### Segmented filter
- **Style:** a radio group in a rail-paper trough with a `rule-strong` 1px border, 4px radius and 2px inner padding. Options are label type at 550 in `ink-2` with a count in `ink-3`.
- **States:** hover darkens text to `ink`; checked lifts onto paper with the selected-segment shadow; keyboard focus draws the 2px accent outline at 1px offset. Options: All, Needs attention, Met or ruled out, Not blocking. On mobile the group fills the width and wraps.

### Buttons
- **Shape:** gently squared (4px), 0.5rem by 0.875rem padding, 600 weight at 0.875rem, 16px line icon with 0.45rem gap, Title Case labels.
- **Primary:** accent fill and border, white text, button-lift shadow. Hover moves to `accent-ink`; active to `oklch(0.38 0.14 256)`. Used once per screen: "Refer to Trial Coordinator" ("Refer Anyway" when ineligible, "Referral Drafted" and disabled after use).
- **Secondary:** paper fill, `rule-strong` border, `ink` text ("Copy Summary"). Hover moves to rail paper with an `ink-3` border; active to `rule`.
- **Disabled:** 50% opacity, not-allowed cursor, no shadow.
- **Text buttons:** disclosures and undo are borderless `accent-ink` text in caption size; underline on hover; the chevron rotates 90° when expanded.

### Mobile bottom action bar
- **Style:** under 860px the action pair docks to the viewport bottom on paper at 96% opacity, with a `rule-strong` top rule, the bottom-bar shadow and safe-area padding. Both buttons share the width equally.
- **Status toast:** feedback ("Referral drafted…", "Summary copied…") appears as a dark `ink` toast with paper text, 4px radius, just above the bar, and hides when empty. On desktop the same live region is a right-aligned caption line under the actions. Undo links inside the toast use a light blue `oklch(0.85 0.06 256)`.

### States
- **Focus:** every focusable element gets a 2px `accent` outline at 2px offset; segmented options at 1px offset.
- **Hover:** a single tonal step in fill or border, 150ms; never movement or scale.
- **Current / target:** `accent-tint` fill (plus inset ring for the current trial).
- **Reviewed:** a criterion marked "Checked" drops its wording to `ink-3`; the mark persists per patient and trial in local storage.
- **Disabled:** 50% opacity.
- **Empty:** explicit sentences ("No matching data in record", "Nothing outstanding.", "None listed in the local registry snapshot."), never a blank cell.

### Motion
Motion is state feedback only. Colour, border and background transitions run 150ms on `cubic-bezier(0.16, 1, 0.3, 1)`; the disclosure chevron rotates over 180ms on the same curve. The check-next jump uses smooth scrolling. There are no entrance animations, no loaders and no layout animation. Under `prefers-reduced-motion: reduce` all transitions collapse to 0.01ms and the jump scrolls instantly.

## Do's and Don'ts

### Do:
- **Do** reserve `met`, `fail`, `open` and `na` (and their tints) for criterion and verdict state, each paired with its glyph and its word.
- **Do** draw unresolved as hatching (135°, 2px bands of `open-fill` and pale amber inside an amber ring) wherever state is shown as a cell without a glyph, so unknown never reads as met or failed in greyscale.
- **Do** write the best verdict as "Eligible, pending review" and keep the caveat that the trial site decides.
- **Do** mark selection with `accent-tint` plus a full 1px inset ring (current trial) or a full-row tint (jump target).
- **Do** separate sections with `rule` and `rule-strong` hairlines and alternate `band` rows, on flat paper.
- **Do** show every evidence value with its date, its source and whether it was reviewed.
- **Do** keep figures tabular and emphasis as a weight step.
- **Do** keep the flag strip in trial order: inclusion, gap, exclusion.

### Don't:
- **Don't** use the state inks as decoration, section colour or brand colour, and don't introduce a fifth state hue.
- **Don't** show state by colour alone; a flag without its glyph and hidden word, or a strip without a verdict word or count sentence beside it, is incomplete.
- **Don't** render a bare "Eligible", a percentage score or a ranking number.
- **Don't** fold unresolved into met or failed counts, colours or icons.
- **Don't** mark selection or state with a coloured side stripe (a thick left or right border on a row or entry).
- **Don't** put criteria, trials or the verdict in floating cards or behind drop shadows beyond the three listed.
- **Don't** use blue for anything that is not interactive or selected.

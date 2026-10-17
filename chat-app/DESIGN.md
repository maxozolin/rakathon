# Avicenna Chat: design system ("Lázeňská kolonáda")

The patient-facing chat (`static/index.html`) is styled as a Czech spa-town programme: a mineral-green colonnade
header, and answers handed over as programme slips. It is meant for an anxious patient on a phone at home, so it
should feel calm and accompanied, not clinical and not like a generic chatbot. This is a separate world from the
clinician console documented in the root `DESIGN.md`.

## Colour (Restrained, with a committed shell)
| Token | Value | Role |
|---|---|---|
| `--spring` | `#e6ede7` | page ground (spring water); arch openings |
| `--spring-line` | `#cbd8cf` | hairlines on the ground |
| `--green` / `--green-deep` | `#2c5a4d` / `#1f4439` | header shell, user messages, primary action, headings |
| `--on-green` / `--on-green-2` | `#f3f7f4` / `#cfdcd6` | text on green |
| `--card` | `#fffefb` | slip card stock, dock |
| `--copper` | `#b4772f` | rubric rule, stamps, list markers, link underline (non-text) |
| `--copper-ink` | `#84531c` | copper text (slip tab, copy, stop button) |
| `--copper-hair` | `#e3d3bc` | rules inside slips |
| `--ink` / `--ink-2` / `--ink-3` | `#1c2622` / `#44544d` / `#53635c` | text (all ≥4.5:1 on ground and card) |
| `--rust` / `--rust-soft` | `#9a3b1e` / `#f8ece6` | errors only |

## Type
- **Voice:** Alegreya Sans 700/800, self-hosted from `static/fonts/` (latin + latin-ext, OFL). Used for the brand,
  welcome headline, section headings, slip tab, table heads and stamps.
- **Reading:** the system UI stack at 17px (16px on phones), line-height 1.55, prose ≤68ch. Times and tables use
  tabular figures.

## Components
- **Colonnade header:** green band ending in an opaque 28px SVG arcade (36px pitch, piers, imposts). Holds the
  CS/EN segmented toggle, *New conversation* and *Settings* (labels collapse to icons under 600px).
- **Slip:** card stock with a square top under a 3px copper rubric rule, rounded foot, soft offset shadow. Used for
  the welcome programme, every answer and the settings popover.
- **Slip tab:** `Avicenna · 17. 10. · 12:27` (logo mask + date and time in tabular figures) above each answer.
- **Programme stamps:** double copper ring, tinted fill, tilted −8°.
- **Starters:** full-width ruled rows with a copper chevron that nudges on hover.
- **User message:** green ticket, right-aligned, 12/12/3/12 radius.
- **Dock:** card-stock strip holding document chips (horizontally scrolling on phones), the composer (1.5px green
  frame, 10px radius, green focus outline) and the disclaimer.
- **System notice:** left-aligned, with a copper dot anchored to the first line.
- **Error:** rust rule and rust text on `--rust-soft`.

## Motion
One authored moment: a new answer *unrolls* from its copper rule (`clip-path`, 0.8s exponential ease-out). While
an answer streams, a copper underline draws beneath "Searching the registries…". Both are disabled under
`prefers-reduced-motion`.

## Don't
- Don't use emoji or glyphs as icons (inline SVG, 2px stroke).
- Don't use coloured left/right stripes, glows or gradients.
- Don't use cream grounds or a display serif.
- Don't use red except for errors.

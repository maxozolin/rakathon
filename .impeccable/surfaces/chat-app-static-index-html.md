---
version: 1
slug: "chat-app-static-index-html"
primary_target: "chat-app/static/index.html"
related_targets: []
---

# Avicenna Chat: patient self-serve conversation

Scope: `chat-app/static/index.html` (single file, vanilla JS, vendored marked + DOMPurify). Visitor mode: Operate. Build path: code-led (no image generation).

Audience and job: this surface serves a different audience from PRODUCT.md's clinician. It is for a patient or relative, at home on a phone in the evening, often anxious after a diagnosis. They ask in their own words, in Czech or English, which clinical trials in Czechia might be worth raising with their doctor, and they may attach reports. Success: they feel accompanied and not processed, and they leave with something concrete to take to their oncologist. It feels wrong if it reads as a cold hospital system or as a generic AI chatbot.

Must stay: CS/EN toggle, uploads (drag/drop, chips, remove), markdown answers, stop/copy, model settings, disclaimer, all JS IDs.

## Direction contract

THESIS: The conversation is a spa-town programme card handed over at the colonnade, a printed day plan of calm steps. It refuses the category default: centred greeting, grey bubbles, a pill composer.

OWN-WORLD:
- Mineral-spring green shell with a cast-iron arch edge.
- Pale spring-water ground.
- White card-stock answers under a copper rubric rule, with copper stamps and tabular times.
- Alegreya Sans for the programme's voice; system sans for reading.

STORY: the patient sees a programme of three steps, asks or picks a starter, and each answer arrives as a dated programme slip they can copy and take to their doctor.

FIRST VIEWPORT (390px):
- Green colonnade header (logo, Avicenna, CS/EN, new chat, settings) ending in arches.
- Left-set headline, one lead line.
- The "Your programme" card with three stamped rows.
- Starter questions as ruled rows.
- The composer docked on white.

FORM: Lázeňská kolonáda, IMPECCABLE'S PICK, position 1 on the ordered list. seed:c661bea764aa6a5d

SIGNATURE: the programme slip. Each answer unrolls downward from its copper rule, which is the one motion; its tab carries "Avicenna · HH:MM" in tabular figures.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

---
name: rebbe.dev Braided Light
description: Thoughtful Jewish guidance expressed through source-first mineral surfaces and a four-strand braid.
colors:
  mineral-canvas: "#f3f6fa"
  mineral-surface: "#fafcfe"
  white-surface: "#ffffff"
  ink: "#122033"
  slate: "#52647c"
  mineral-line: "#c6d2e1"
  mineral-line-strong: "#9fb0c6"
  braid-indigo: "#315da8"
  braid-indigo-strong: "#214784"
  braid-indigo-soft: "#e4ebf6"
  night-canvas: "#101722"
  night-surface: "#161f2c"
  night-ink: "#eff4fa"
  night-slate: "#a9b7c8"
  night-line: "#34445a"
  night-indigo: "#86a8e3"
  success: "#18734d"
  error: "#b23a3a"
typography:
  display:
    fontFamily: "Hanken Grotesk, Noto Sans Hebrew, Arial, sans-serif"
    fontSize: "clamp(3.3rem, 5.45vw, 6rem)"
    fontWeight: 560
    lineHeight: 0.96
    letterSpacing: "-0.04em"
  headline:
    fontFamily: "Hanken Grotesk, Noto Sans Hebrew, Arial, sans-serif"
    fontSize: "clamp(2rem, 3.4vw, 3.35rem)"
    fontWeight: 680
    lineHeight: 0.98
    letterSpacing: "-0.04em"
  body:
    fontFamily: "Hanken Grotesk, Noto Sans Hebrew, Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Hanken Grotesk, Noto Sans Hebrew, Arial, sans-serif"
    fontSize: "0.76rem"
    fontWeight: 720
    lineHeight: 1.2
    letterSpacing: "0.16em"
rounded:
  small: "8px"
  control: "10px"
  structure: "14px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  section: "64px"
components:
  button-primary:
    backgroundColor: "{colors.braid-indigo-strong}"
    textColor: "{colors.white-surface}"
    rounded: "{rounded.control}"
    padding: "13px 20px"
    height: "50px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.braid-indigo-strong}"
    rounded: "{rounded.control}"
    padding: "13px 20px"
    height: "50px"
  input:
    backgroundColor: "{colors.mineral-surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.small}"
    padding: "10px 12px"
    height: "44px"
  surface-card:
    backgroundColor: "{colors.mineral-surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.structure}"
    padding: "20px"
---

# Design System: rebbe.dev Braided Light

## Overview

**Creative North Star: "Braided Light"**

Braided Light makes source-aware Jewish guidance feel calm, serious, and humane. Four strands represent context, halachic reasoning, ethical review, and voice; they remain countable in the mark and explanatory moments, then resolve into one readable answer. The world pairs cool mineral surfaces with sparse indigo emphasis and image-native woven material.

The public surface may persuade with scale and material, while the conversational app and admin become progressively quieter and denser. Across every mode, source legibility and the boundary between guidance and psak take precedence over spectacle.

**Key Characteristics:**

- Four-strand geometry and a reduced lowercase `r` are the owned signature.
- Cool mineral light and dark surfaces carry one restrained indigo accent.
- Source sheets, thin rules, and asymmetric layouts make provenance visible.
- Hanken Grotesk stays direct and contemporary; Noto Sans Hebrew protects Hebrew reading.
- Red and green appear only for genuine error and success states.

## Colors

The palette feels like paper, slate, and indigo illumination rather than ceremonial gold or generic technology blue. The frontmatter is the normative token source; dark mode maps the same semantic roles onto the night tokens.

### Primary

- **Braid Indigo:** The normal interactive accent for links, focus, source markers, and explanatory strands.
- **Strong Braid Indigo:** Primary calls to action and high-emphasis controls on light surfaces.
- **Night Indigo:** The accessible accent and primary-control fill on dark surfaces.

### Neutral

- **Mineral Canvas and Surface:** Page ground and inset reading surfaces in light mode.
- **Ink and Slate:** Primary reading text and supporting explanation.
- **Mineral Lines:** Dividers, table containment, and field boundaries; use the strong line only when separation must be unmistakable.
- **Night Canvas, Surface, Ink, and Slate:** Equivalent semantic roles in dark mode, not an inverted afterthought.

### Named Rules

**The One Indigo Rule.** Indigo is the sole brand accent; it should organize attention, not coat the interface.

**The Semantic Signal Rule.** Reserve red and green for actual error and success. Never use them as decoration or product categories.

## Typography

**Display Font:** Hanken Grotesk (with Noto Sans Hebrew and Arial fallback)
**Body Font:** Hanken Grotesk (with Noto Sans Hebrew and Arial fallback)
**Hebrew Font:** Noto Sans Hebrew (with Hanken Grotesk and Arial fallback)

**Character:** The same broad grotesk voice moves from low-tension editorial display type to compact operational labels. Hebrew is a first-class script, and numeric metrics use tabular lining figures.

### Hierarchy

- **Display** (560, fluid up to 6rem, 0.96): Public hero statements; tightly tracked and balanced.
- **Headline** (680, fluid up to 3.35rem, 0.98): App greetings and admin view titles.
- **Body** (400, 1rem, 1.55): Explanations, answers, and working copy; long-form reader text opens to approximately 1.75-1.82 line height.
- **Label** (720, 0.76rem, 0.16em, uppercase): Section eyebrows and source metadata, never paragraph text.

### Named Rules

**The Reading First Rule.** Long-form answers use relaxed leading and constrained measure; operational density belongs in navigation, metrics, and labels.

## Layout

The landing page uses an asymmetric Source Loom: a compact promise beside a larger static answer, inside a fluid 1500px maximum canvas with gutters from 20px to 64px. Later sections change topology rather than repeating equal card rows. The app uses a 292px rail, an 1180px workspace, and a 760px reading measure. Admin uses a 248px rail and a dense task-first content plane.

Responsive layouts collapse by function. Landing reorganizes at 1180px, 860px, and 560px; the app moves the rail to a controlled overlay at 820px and compresses further at 640px; admin replaces desktop tabs and tables with a view selector and result summaries below 820px/720px. Every action retains a minimum 44px target, all content remains usable at 200 percent zoom, and bidi content uses `dir="auto"`.

Spacing follows an 8px-biased rhythm, with 16-24px component interiors and fluid 32-64px sectional gaps. Asymmetry creates emphasis, but reading columns remain calm and aligned.

## Elevation & Depth

The system is flat by default. Tonal layering, thin rules, translucent source sheets, and the photographed braid establish depth; a single ambient material shadow lifts dialogs, menus, and key proof surfaces. Sticky headers use a restrained blur over the active canvas.

### Shadow Vocabulary

- **Material lift** (`0 18px 48px rgba(28, 54, 89, 0.12)`): Dialogs, menus, and selected showcase surfaces in light mode.
- **Night material lift** (`0 20px 54px rgba(0, 0, 0, 0.28)`): The same roles in dark mode.
- **Focus halo** (`0 0 0 3px rgba(49, 93, 168, 0.28)`): Paired with a 2px visible outline; never used as decoration.

### Named Rules

**The Material, Not Glass Rule.** Blur may stabilize sticky chrome, but primary content should read as mineral paper, woven fiber, or translucent source sheets, not glassmorphism.

## Shapes

Structural containers use gently curved 14px corners. Fields and compact controls use 8px; prominent CTA controls use 10px. Pills are reserved for semantic tags, status, and toggles. Thin rectangular rules and the continuous braid balance the curves. Circles appear only for avatars, indicators, or spinning progress.

**The Meaningful Pill Rule.** A 999px radius must communicate status, category, or toggle state; it is not a default button silhouette.

## Components

### Buttons

- **Shape:** Compact rectangular control (10px landing CTA; 8px operational controls), never a generic pill.
- **Primary:** Strong indigo on light surfaces and light indigo with dark ink in dark mode; at least 44px high.
- **Hover / Focus:** Transform or opacity only; hover may lift by 2px. Focus combines an indigo outline and halo.
- **Quiet:** Transparent with an explicit line and indigo text; underlined text actions use a generous underline offset.

### Chips

- **Style:** Pills only for semantic status. Curated prompt actions are 8px rectangular mini-cards with an icon, title, and supporting line.
- **State:** Selected states use indigo-soft fill and a clear accent boundary.

### Cards / Containers

- **Corner Style:** Structural 14px radius.
- **Background:** Surface or raised-surface semantic tokens, with one-pixel mineral lines.
- **Shadow Strategy:** Flat at rest; material lift only when an element truly floats.
- **Internal Padding:** Usually 16-24px, increasing for editorial proof surfaces.

### Inputs / Fields

- **Style:** Persistent label, strong mineral stroke, 8px radius, at least 44px high.
- **Focus:** Indigo border plus the shared visible focus halo.
- **Error / Disabled:** Error uses semantic red with written status; disabled controls retain readable structure and reduced opacity.

### Navigation

Landing navigation is quiet and centered between brand and actions. App and admin navigation use task-first rails with bordered active states, local icons, and compact metadata. Mobile navigation must be an accessible overlay or selector with explicit close paths and restored focus.

### Source Loom

The signature explanatory component contains exactly four countable SVG strands, four stage labels, and a readable result. Draw the braid once with SVG stroke motion; under reduced motion, render the complete static form immediately. Source references remain adjacent and distinguish locally matched material from model knowledge.

## Do's and Don'ts

### Do:

- **Do** keep the four strands countable wherever the braid explains the product mechanism.
- **Do** use real woven and translucent-sheet assets at identity-bearing moments, with quiet operational surfaces around them.
- **Do** preserve persistent labels, visible focus, 44px targets, reduced-motion fallbacks, and `dir="auto"` for user and source content.
- **Do** keep guidance limits and human referral visually adjacent to the answer they qualify.
- **Do** use locally vendored fonts, icons, and production imagery.

### Don't:

- **Don't** reintroduce the Star of David as the product mark or reduce the braid to decorative squiggles.
- **Don't** repeat generic equal-card grids when a reader, rail, loom, table, or divided metric field communicates the information better.
- **Don't** use pills as the default shape, gradients as atmosphere, or red/green as ornamental brand colors.
- **Don't** imitate sourced text with fake legible writing inside generated imagery.
- **Don't** imply that source matching is claim-level verification or that the product provides binding psak.

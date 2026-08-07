---
name: Visualang
description: A focused studio console for turning spoken audio into illustrated, replayable visualizations.
colors:
  ultramarine: "#1d2a63"
  ultramarine-strong: "#16204d"
  cornflower: "#8fa7ff"
  cornflower-bright: "#5b7cf0"
  porcelain: "#f3f4f8"
  surface-white: "#ffffff"
  field-white: "#fafafd"
  ink: "#1a2036"
  ink-muted: "#5b6178"
  line: "#e2e4ee"
  line-strong: "#c9cde0"
  wash: "#e7ecfa"
  wash-strong: "#dfe5fa"
  night: "#12151d"
  night-surface: "#1a1e29"
  night-field: "#151924"
  night-ink: "#e9ebf2"
  night-ink-muted: "#9aa1b5"
  night-line: "#272c3a"
  night-line-strong: "#343b4e"
  night-wash: "#232d4d"
  signal-red: "#8f2f2a"
  signal-red-bg: "#fbe4e2"
  night-signal-red: "#f2b0aa"
  night-signal-red-bg: "#46201d"
  success-green: "#1f6d43"
  success-green-bg: "#e0f0e7"
  night-success-green: "#8fd3ae"
  night-success-green-bg: "#1c3328"
  warning-bg: "#f7ecd8"
  night-warning-bg: "#3a2f1c"
  stage-black: "#0d1016"
typography:
  display:
    fontFamily: "Schibsted Grotesk, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.2
  headline:
    fontFamily: "Schibsted Grotesk, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.25
  title:
    fontFamily: "Schibsted Grotesk, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Schibsted Grotesk, Helvetica Neue, Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Schibsted Grotesk, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
    lineHeight: 1.2
  caption:
    fontFamily: "Schibsted Grotesk, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.2
rounded:
  control: "0.5rem"
  card: "0.75rem"
  pill: "999px"
spacing:
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.ultramarine}"
    textColor: "{colors.surface-white}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "11px 22px"
    height: "44px"
  button-secondary:
    backgroundColor: "{colors.surface-white}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    height: "44px"
  text-field:
    backgroundColor: "{colors.field-white}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "11px 12px"
    height: "44px"
  content-card:
    backgroundColor: "{colors.surface-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "20px 22px"
---

# Design System: Visualang

## Overview

**Creative North Star: "The Studio Console"**

Visualang is a focused console that turns spoken audio into an illustrated, replayable visualization. The chrome is a clean, modern product surface — cool neutrals, a single sans-serif family, one ultramarine accent — so that all warmth and character come from the generated imagery on its dark stage. The tool disappears into the task; the visualization is the star.

The interface has exactly one identity moment: the deep ultramarine top bar that carries the wordmark and the pipeline stepper. Everything below it is quiet porcelain and white. Familiar affordances everywhere; earned familiarity over invention.

The system explicitly rejects the warm-editorial AI formula (cream canvas, serif display, terracotta accents) as well as generic AI startup styling, chatbot framing, glassmorphism, decorative glows, and tracked-uppercase eyebrow labels.

**Key Characteristics:**

- One committed color: ultramarine chrome on the top bar; restrained everywhere else
- A single type family (Schibsted Grotesk) across headings, labels, buttons, and data
- The pipeline stepper (Source → Transcript → Scenes → Video) is the primary status surface
- The visualization stage is near-black so imagery glows
- Light and dark themes with identical semantic hierarchy; dark is "Night Cinema"

## Colors

### Primary

- **Ultramarine** (`ultramarine`): The single action and identity color in light mode — top bar fill, primary buttons, active states, focus.
- **Ultramarine Strong** (`ultramarine-strong`): Hover/pressed shade for ultramarine surfaces.
- **Cornflower** (`cornflower`): Non-text accent on dark grounds — wordmark dot, progress track fill, done-step ticks on the bar.
- **Cornflower Bright** (`cornflower-bright`): The primary action color in dark mode, where full ultramarine would vanish.

### Neutral

- **Porcelain** (`porcelain`): Light-theme page ground — a cool, blue-biased near-white. Never warm-tinted.
- **Surface White** (`surface-white`): Cards and raised surfaces in light mode.
- **Field White** (`field-white`): Input fills in light mode.
- **Ink / Ink Muted** (`ink`, `ink-muted`): Primary and secondary light-theme text.
- **Line / Line Strong** (`line`, `line-strong`): Hairline and control borders.
- **Wash / Wash Strong** (`wash`, `wash-strong`): Ultramarine-tinted fills for chips, active steps, and info notices.
- **Night...** (`night`, `night-surface`, `night-field`, `night-ink`, `night-ink-muted`, `night-line`, `night-line-strong`, `night-wash`): The dark-theme equivalents of the above.
- **Stage Black** (`stage-black`): The media stage behind imagery in both themes.

### Semantic

- **Signal Red** (`signal-red` / `night-signal-red`, with `-bg` fills): Errors and destructive status only.
- **Success Green** (`success-green` / `night-success-green`, with `-bg` fills): Completion confirmation only.
- **Warning** (`warning-bg` / `night-warning-bg`): Cautionary notices, paired with ink text.

### Named Rules

**The One Bar Rule.** Ultramarine may fill exactly one large surface: the top bar. Below it, ultramarine appears only on the current primary action, selection, and focus.

**The Stage Owns the Warmth Rule.** Generated imagery supplies all warmth and saturation. Chrome neutrals stay cool and quiet so scenes read as the subject.

**The Semantic Pairing Rule.** Error, warning, and success states always pair color with text or iconography. Color alone never carries status.

## Typography

**Single Family:** Schibsted Grotesk (Helvetica Neue, Arial fallbacks) for every role — headings, body, labels, buttons, and playback data.

**Character:** A modern grotesque with enough personality to avoid the Inter monoculture, tuned for product UI. No display serif; no second family.

### Hierarchy

- **Display** (600, `1.5rem`, 1.2): The single main heading per view.
- **Headline** (600, `1.25rem`, 1.25): Visualization titles in the preview header.
- **Title** (600, `1.125rem`, 1.3): Section names and card headings.
- **Body** (400, `1rem`, 1.6): Instructions, help, status detail; prose capped near 70 characters.
- **Label** (600, `0.875rem`, 1.2): Buttons, field labels, segmented controls, stepper items.
- **Caption** (600, `0.75rem`, 1.2): Chips, timecodes, and dense metadata. Timecodes use tabular numerals.

### Named Rules

**The Fixed Ramp Rule.** Product type uses the fixed rem ramp above — no fluid clamp() headings, no sizes off the ramp.

**The Plain Status Rule.** Progress and error language is concise sentence case. No tracked-uppercase eyebrows; the only uppercase in the UI is nothing at all.

## Elevation

The system is flat. Hierarchy comes from the cool ground / white card / dark stage layering, hairline borders, and tonal washes — not shadows.

### Shadow Vocabulary

- **Control Pop** (`0 1px 2px rgba(13, 16, 22, 0.14)`): Segmented-control active thumb and small raised controls only.
- **Stage Fade** (`linear-gradient(transparent, rgba(8, 11, 16, 0.86))`): The media-control scrim over the bottom edge of the stage. Media-only.

### Named Rules

**The Flat Console Rule.** Cards use border + fill, never border + shadow. No ambient panel shadows, no blur, no glassmorphism anywhere.

**The No Nested Cards Rule.** A card never contains another bordered card. Internal grouping uses spacing and hairline separators.

## Components

### Buttons

- **Shape:** `0.5rem` corners, 44px minimum target height, Label typography.
- **Primary:** Ultramarine fill (Cornflower Bright in dark mode), white text. Hover darkens to Ultramarine Strong over 150ms; no lift, no shadow.
- **Secondary / Ghost:** White (or `night-surface`) fill, ink text, `line-strong` border.
- **Focus:** 2px solid focus ring (`ultramarine` light / `cornflower` dark) with 2px offset.
- **Disabled:** Reduced-contrast fill and text, no pointer affordance, still ≥3:1 against ground.

### Top Bar

- **Style:** Full-width ultramarine fill in light mode; `night` fill with a hairline bottom border in dark mode. Contains the wordmark (text + cornflower dot), the pipeline stepper, and the theme toggle.
- **Stepper:** Source → Transcript → Scenes → Video as caption-size pills. Current step gets a translucent white wash (light bar) or `night-wash` fill; completed steps get a check and cornflower text; pending steps are bar-muted.

### Segmented Control (source mode)

- **Style:** A pill-less `0.5rem` track (`wash`-toned fill) containing equal buttons; the active option is a white (or `night-wash`) thumb with Control Pop shadow.

### Cards

- **Corner Style:** `0.75rem`.
- **Background:** Surface White / `night-surface` with a `line` border.
- **Padding:** 20–22px. No shadows, no blur, no accent stripes.

### Inputs / Fields

- **Style:** 44px minimum height, `0.5rem` corners, `line-strong` border, `field-white` / `night-field` fill.
- **Focus:** 2px ring with 2px offset plus border-color shift to the action color.
- **Error:** A filled Signal Red notice with icon and message below the field.
- **File Upload:** Dashed `line-strong` border on the drop target; `:focus-within` shows the standard ring.

### Status Notices

- **Style:** `0.5rem` corners, 12–16px padding, semantic tonal fill, no border stripe.
- **Behavior:** Errors use `role="alert"`; routine progress uses a polite live region.

### Visualization Stage

- **Composition:** A 16:9 Stage Black field dominates the preview. Playback controls overlay only the bottom edge via the Stage Fade scrim.
- **Controls:** Play/pause, timeline, elapsed/total time, and playback speed with 44px+ targets; timecodes in tabular numerals.
- **Motion:** Scene crossfades run 400ms; slow Ken Burns drift may follow each scene's duration. Under `prefers-reduced-motion`, drift and spinners stop and crossfades become instant.

## Do's and Don'ts

### Do:

- **Do** keep the stepper, status copy, and stage in one legible column — the workflow reads top to bottom.
- **Do** make the visualization stage the largest element once imagery exists.
- **Do** give every interactive component default, hover, focus, active, and disabled states.
- **Do** keep body copy near 70 characters and maintain WCAG 2.2 AA contrast in both themes.
- **Do** provide a reduced-motion alternative for every animation.
- **Do** use skeleton or inline progress for waiting states, with concrete stage names.

### Don't:

- **Don't** reintroduce the warm-editorial formula: cream grounds, serif display type, terracotta accents, storybook framing.
- **Don't** use glassmorphism, backdrop blur, ambient panel shadows, radial glows, or gradient text.
- **Don't** use tracked-uppercase eyebrows or numbered section scaffolding.
- **Don't** put ultramarine on decoration — it marks the bar, actions, selection, and focus only.
- **Don't** use purple-gradient AI styling, chatbot framing, token pills, or "magic" language.
- **Don't** stack shadows with borders, nest cards, or add colored side stripes.
- **Don't** use any second typeface; Schibsted Grotesk carries everything.

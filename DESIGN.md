---
name: Visualang
description: A focused lesson studio for turning spoken material into illustrated learning videos.
colors:
  burnt-clay: "#8f4d32"
  soft-terracotta: "#b96e4d"
  library-sage: "#54734f"
  soft-sage: "#7d9b75"
  studio-canvas: "#f5f0e8"
  warm-paper: "#fffaf4"
  ink-brown: "#251d14"
  secondary-ink: "#5c4738"
  night-studio: "#16110d"
  night-paper: "#2d231c"
  night-ink: "#f4eadf"
  signal-red: "#8b2b2b"
typography:
  display:
    fontFamily: "Playfair Display, Georgia, serif"
    fontSize: "clamp(2rem, 3.8vw, 3.45rem)"
    fontWeight: 600
    lineHeight: 1.05
  headline:
    fontFamily: "Playfair Display, Georgia, serif"
    fontSize: "1.8rem"
    fontWeight: 600
    lineHeight: 1.22
  title:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "1.15rem"
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "1rem"
    fontWeight: 700
    lineHeight: 1.2
rounded:
  field: "16px"
  context: "18px"
  panel: "24px"
  pill: "999px"
spacing:
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.burnt-clay}"
    textColor: "{colors.warm-paper}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "13.6px 20px"
    height: "52px"
  button-secondary:
    backgroundColor: "{colors.warm-paper}"
    textColor: "{colors.ink-brown}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "13.6px 20px"
    height: "52px"
  text-field:
    backgroundColor: "{colors.warm-paper}"
    textColor: "{colors.ink-brown}"
    typography: "{typography.body}"
    rounded: "{rounded.field}"
    padding: "14.4px 16px"
    height: "54px"
  content-panel:
    backgroundColor: "{colors.warm-paper}"
    textColor: "{colors.ink-brown}"
    rounded: "{rounded.panel}"
    padding: "clamp(20px, 3vw, 40px)"
---

# Design System: Visualang

## Overview

**Creative North Star: "The Illustrated Lesson Studio"**

Visualang is a focused workspace that turns spoken material into a finished learning artifact. The interface should feel cinematic only when imagery is the subject: the generated preview receives the largest visual field, while source input, progress, export, and download controls remain structured and quiet. This is a product workflow, not a film-marketing page.

The visual language pairs editorial serif type with a restrained clay-and-sage palette. Warmth comes from the imagery, type, and accents rather than from decorative effects. Controls use familiar affordances, status remains legible during long waits, and the interface becomes denser or simpler according to the current stage instead of presenting every function at once.

The system explicitly rejects generic AI startup styling, chatbot framing, prompt playgrounds, token dashboards, cosmic decoration, and empty SaaS hero compositions. Craft must serve the learning workflow and the exported video.

**Key Characteristics:**

- Image-led preview with restrained surrounding chrome
- Editorial warmth paired with product-level interaction clarity
- One continuous source-to-download workflow
- Strong status communication without dashboard noise
- Light and dark themes that preserve the same semantic hierarchy

## Colors

The palette uses burnt clay for action, library sage for completion, and deep brown neutrals for a warmer alternative to generic gray UI.

### Primary

- **Burnt Clay** (`burnt-clay`): The accessible primary action, active selection, and light-theme focus color.
- **Soft Terracotta** (`soft-terracotta`): A supporting atmospheric accent; never a substitute for the stronger action color where contrast matters.

### Secondary

- **Library Sage** (`library-sage`): Completion and positive progress indicators.
- **Soft Sage** (`soft-sage`): Low-intensity atmospheric support and non-text decoration.

### Neutral

- **Studio Canvas** (`studio-canvas`): The light-theme page field.
- **Warm Paper** (`warm-paper`): Primary light surfaces and text over dark media controls.
- **Ink Brown** (`ink-brown`): Primary light-theme text.
- **Secondary Ink** (`secondary-ink`): Supporting copy that still meets body-text contrast requirements.
- **Night Studio** (`night-studio`): The dark-theme page field.
- **Night Paper** (`night-paper`): Elevated dark-theme surfaces.
- **Night Ink** (`night-ink`): Primary dark-theme text.
- **Signal Red** (`signal-red`): Error text and destructive status only.

### Named Rules

**The One Action Color Rule.** Burnt Clay identifies primary action, current selection, and focus. It is not page decoration.

**The Preview Owns the Color Rule.** Generated artwork may be visually rich; surrounding controls stay neutral enough that the lesson remains dominant.

**The Semantic Pairing Rule.** Error, warning, information, and success states always combine text or iconography with color. Color alone never carries status.

## Typography

**Display Font:** Playfair Display (with Georgia and serif fallbacks)  
**Body Font:** Source Serif 4 (with Georgia and serif fallbacks)

**Character:** Playfair gives lesson titles and major stage headings an editorial, story-led voice. Source Serif 4 keeps forms, status, and supporting text readable without introducing a conflicting UI typeface.

### Hierarchy

- **Display** (600, `display`, 1.05): One primary stage heading per view; balance wrapping and prevent overflow on narrow screens.
- **Headline** (600, `headline`, 1.22): Lesson titles and prominent preview context.
- **Title** (700, `title`, 1.3): Workflow steps, download groups, and compact section names.
- **Body** (400, `body`, 1.6): Instructions, help, progress detail, and status messaging; prose is capped near 70 characters per line.
- **Label** (700, `label`, 1.2): Buttons, field labels, selectors, and compact controls. Labels use Source Serif 4, never the display face.

### Named Rules

**The One Editorial Moment Rule.** Playfair is reserved for the current stage heading or lesson title. Controls, labels, data, and status always use Source Serif 4.

**The Plain Status Rule.** Progress and error language is concise sentence case. Tracked uppercase text is not a default section scaffold.

## Elevation

The system is flat and tonal by default. Canvas, paper, field, and media layers establish hierarchy before shadows do. A low ambient shadow may separate the main lesson panel from the page, while the preview uses an inset vignette to keep controls legible over imagery. Blur is restricted to media controls where it preserves context; ordinary panels must not become decorative glass cards.

### Shadow Vocabulary

- **Panel Ambient** (`0 24px 60px -32px var(--color-shadow)`): Main stage separation only; never stack it across nested containers.
- **Control Lift** (`0 10px 20px -14px rgba(37, 29, 20, 0.45)`): Brief hover feedback on actionable buttons.
- **Preview Vignette** (`inset 0 0 160px rgba(15, 10, 7, 0.45)`): Media-only contrast support behind overlaid controls.

### Named Rules

**The Flat Workflow Rule.** Source, progress, and download structures use tonal contrast and dividers first. Shadows are reserved for the primary stage and interaction feedback.

**The No Nested Glass Rule.** Never place translucent blurred cards inside another elevated or blurred panel.

## Components

Components should feel tactile enough to confirm interaction and restrained enough to disappear once the user begins the lesson workflow.

### Buttons

- **Shape:** Full pill (`pill`) with a minimum 52px target height.
- **Primary:** Burnt Clay background, Warm Paper text, bold Source Serif label, and 13.6px by 20px padding.
- **Hover / Focus:** Hover lifts by 1px over 150ms. Focus uses a 3px solid semantic focus ring with a 3px offset. Disabled controls lose lift and use explicit muted foreground and background colors.
- **Secondary:** Paper-toned surface, Ink Brown text, and a subtle full border; it never competes with the current primary action.

### Source Mode Control

- **Style:** A wrapping set of 52px-high buttons with 16px corners, icon-plus-label content, and clear active fill.
- **State:** The active option uses Burnt Clay and Warm Paper. Hover changes border emphasis and lifts by 1px; focus follows the global ring.

### Cards / Containers

- **Corner Style:** Main stage panels use 24px corners on wide screens and approximately 19px on narrow screens. Internal notices and fields use 16px corners.
- **Background:** Warm Paper in light mode and Night Paper in dark mode.
- **Shadow Strategy:** Only the principal stage may use Panel Ambient. Internal groups use spacing, separators, or tonal fill.
- **Border:** One subtle full perimeter border. Colored side stripes are prohibited.
- **Internal Padding:** 20–40px for a principal panel; 16–20px for notices and internal groups.

### Inputs / Fields

- **Style:** 54px minimum height, 16px corners, full subtle border, paper-toned fill, and 14.4px by 16px padding.
- **Focus:** A 3px semantic ring with 3px offset and a stronger border color.
- **Error / Disabled:** Error text appears in a filled Signal Red notice with an icon or explicit message. Disabled state remains readable and visibly non-interactive.
- **File Upload:** A dashed full border is permitted for the drop target; keyboard focus remains visible on the label through `:focus-within`.

### Status Notices

- **Style:** 16px corners, compact 16px padding, subtle full border, and semantic tonal fill.
- **Behavior:** Errors use `role="alert"`; routine progress uses a polite live region. Dismiss controls inherit the notice color and retain an accessible name.

### Illustrated Preview Player

- **Composition:** A 16:9 image field dominates the preview state. Playback controls overlay only the lower edge of the image, using a dark tonal fade rather than a separate floating toolbar.
- **Controls:** Play/pause, timeline, elapsed time, duration, title, and playback speed use familiar media affordances with 44px or larger targets.
- **Motion:** Scene fades last 800ms. Ken Burns motion follows the duration of each scene and stops under reduced-motion preferences.
- **Responsive Behavior:** At 672px and below, controls become full-width rows, the timeline stacks, and the lesson title may wrap.

## Do's and Don'ts

### Do:

- **Do** make the generated preview the largest visual element once imagery is available.
- **Do** preserve the source, processing, preview, export, and download sequence as one legible workflow.
- **Do** use Burnt Clay for the single current primary action and Library Sage for completion.
- **Do** keep body copy near 70 characters per line and maintain WCAG 2.2 AA contrast.
- **Do** provide visible focus, keyboard operation, text-plus-color status, and reduced-motion behavior.
- **Do** let dark media controls overlay the preview while keeping ordinary product surfaces mostly flat and tonal.

### Don't:

- **Don't** use generic AI startup interfaces built around purple gradients, cosmic glows, sparkles, or “magic” language.
- **Don't** use chatbot, prompt-playground, agent-dashboard, or token-pill interaction models.
- **Don't** use floating glass cards, empty center-column SaaS heroes, or decorative metrics that obscure the workflow.
- **Don't** use generic content-generation framing that makes language learning or the exported video feel secondary.
- **Don't** use noisy progress messaging, low-contrast controls, or motion that competes with the user’s task.
- **Don't** copy a film-marketing landing page: no full-screen background video, giant slogan, or form floating over unpredictable imagery.
- **Don't** use colored side-stripe borders, gradient text, nested cards, or border-plus-wide-shadow decoration.
- **Don't** use Playfair Display for buttons, labels, playback data, or status messages.

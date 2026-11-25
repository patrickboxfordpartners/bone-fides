# Bone Fides — Design System

Extracted from the landing page (`designs/landing-20261108/finalized.html`,
built with /design-html, Pretext inline tier). Applies to future /design-shotgun
and /design-html runs in this repo.

## Palette

Warm-dark, parchment-ink. Text sits warm, never pure white; backgrounds sit
brown-dark, never pure black.

```css
:root {
  --bg: #171310;        /* page background */
  --bg2: #1f1a15;       /* raised surfaces (cards, slideshow frame) */
  --ink: #efe6d3;       /* primary text, warm parchment */
  --dim: #9b8f7c;       /* secondary text, muted tan */
  --faint: rgba(239, 230, 211, .14);  /* hairline borders */
  --accent: #d08152;    /* terracotta — italic emphasis, key numbers, focus ring */
  --gold: #c2a05a;      /* kickers, labels, links */
  --ok: #8fb996;        /* confidence: corroborated (green) */
  --bad: #d9776b;       /* confidence: thin (red) */
}
```

Confidence gold (single strong source) = `--gold`. Score numbers use `--accent`.

## Type

Single family: **Fraunces** (Google Fonts, variable, opsz 9..144), Georgia serif
fallback. Italic light weights carry emphasis.

```html
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,300..900&display=swap" rel="stylesheet">
```

| Role | Size | Weight | Notes |
|---|---|---|---|
| Body | 17px, lh 1.6 | 350 | |
| Lede | clamp(19px, 2.2vw, 24px) | 350 | `--dim` |
| Hero h1 | clamp(44px, 7.2vw, 92px), lh .98 | 380, ls −.015em | `<em>` = accent italic 500 |
| Section head | clamp(27px, 3.4vw, 40px), lh 1.12 | 380 | |
| Closing h2 | clamp(34px, 5vw, 62px), lh 1.05 | 380 | |
| Card/dossier head | clamp(24px, 2.6vw, 32px) | 400 | |
| Step h4 | 21px | 480 | |
| Kicker/label | 10.5–11px | — | uppercase, ls .3em, `--gold` |
| Stat number | clamp(30px, 3.6vw, 46px) | 420 | tabular-nums, ls −.01em |
| Small body/captions | 13.5–15.5px | 340–480 | captions italic `--dim` |
| Wordmark | 19px | 560, ls .01em | `<em>` = accent italic |

Weights are light (350–480) with emphasis via 560; never bold-black. Display
sizes are fluid via clamp; small labels fixed.

## Spacing & Layout

```css
--pad: clamp(20px, 5vw, 72px);   /* page gutter */
--measure: 66ch;                  /* body copy max width */
```

- Section rhythm: `padding-top: clamp(48px, 7vw, 88px)`
- Hero: `clamp(56px, 9vw, 108px)` top / `clamp(40px, 6vw, 64px)` bottom
- Hairline dividers: `1px solid var(--faint)`
- Focus ring: `2px solid var(--accent); outline-offset: 3px`
- Uppercase micro-labels always `.18em–.3em` letterspacing

## Motion

- Reduced-motion respected: `@media (prefers-reduced-motion: reduce)` kills smooth scroll
- Slideshow: slow Ken Burns (`transform 7.5s ease-out`), 1s crossfade, captions
  rise 10px on .5s ease
- Image legibility floor: bottom gradient to `#171310` under captions

## Voice

Editorial, evidentiary, restrained. Emphasis = italic Fraunces in terracotta,
not size jumps. Numbers are claims — always tabular, always traceable to a
source link.

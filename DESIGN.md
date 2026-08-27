---
name: Reconciliation Console
description: A dense, cool-grey finance operations console where colour marks severity and nothing else.
colors:
  background: "oklch(0.985 0.002 250)"
  surface: "oklch(1 0 0)"
  surface-raised: "oklch(0.975 0.003 250)"
  foreground: "oklch(0.21 0.012 254)"
  muted: "oklch(0.955 0.004 250)"
  muted-foreground: "oklch(0.47 0.012 254)"
  border: "oklch(0.9 0.005 250)"
  border-strong: "oklch(0.82 0.008 252)"
  accent: "oklch(0.45 0.035 253)"
  accent-foreground: "oklch(0.99 0 0)"
  ring: "oklch(0.55 0.09 250)"
  critical: "oklch(0.48 0.17 25)"
  critical-bg: "oklch(0.955 0.028 25)"
  warn: "oklch(0.47 0.1 75)"
  warn-bg: "oklch(0.96 0.038 85)"
  ok: "oklch(0.44 0.09 155)"
  ok-bg: "oklch(0.955 0.03 155)"
  info: "oklch(0.47 0.09 245)"
  info-bg: "oklch(0.955 0.028 245)"
  dark-background: "oklch(0.165 0.008 254)"
  dark-surface: "oklch(0.196 0.009 254)"
  dark-surface-raised: "oklch(0.232 0.01 254)"
  dark-foreground: "oklch(0.93 0.004 250)"
  dark-muted: "oklch(0.246 0.01 254)"
  dark-muted-foreground: "oklch(0.71 0.011 252)"
  dark-border: "oklch(0.29 0.011 254)"
  dark-border-strong: "oklch(0.38 0.014 254)"
  dark-accent: "oklch(0.72 0.06 250)"
  dark-accent-foreground: "oklch(0.16 0.01 254)"
  dark-ring: "oklch(0.66 0.1 250)"
  dark-critical: "oklch(0.75 0.15 25)"
  dark-critical-bg: "oklch(0.29 0.07 25)"
  dark-warn: "oklch(0.83 0.13 85)"
  dark-warn-bg: "oklch(0.3 0.06 75)"
  dark-ok: "oklch(0.76 0.12 155)"
  dark-ok-bg: "oklch(0.27 0.05 155)"
  dark-info: "oklch(0.76 0.1 245)"
  dark-info-bg: "oklch(0.28 0.05 245)"
typography:
  metric-lg:
    fontFamily: "var(--font-geist-mono), ui-monospace, 'SF Mono', monospace"
    fontSize: "26px"
    fontWeight: 600
    lineHeight: "32px"
    letterSpacing: "-0.01em"
    fontFeature: "tabular-nums"
  metric:
    fontFamily: "var(--font-geist-mono), ui-monospace, 'SF Mono', monospace"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: "24px"
    letterSpacing: "-0.01em"
    fontFeature: "tabular-nums"
  figure:
    fontFamily: "var(--font-geist-mono), ui-monospace, 'SF Mono', monospace"
    fontSize: "12.5px"
    fontWeight: 400
    letterSpacing: "-0.01em"
    fontFeature: "tabular-nums"
  title:
    fontFamily: "var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: "1.45"
    letterSpacing: "-0.01em"
  body:
    fontFamily: "var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: "1.45"
    letterSpacing: "normal"
  body-dense:
    fontFamily: "var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: "1.45"
    letterSpacing: "normal"
  secondary:
    fontFamily: "var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: "1.45"
    letterSpacing: "normal"
  micro:
    fontFamily: "var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif"
    fontSize: "11.5px"
    fontWeight: 400
    lineHeight: "1.45"
    letterSpacing: "normal"
  label:
    fontFamily: "var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif"
    fontSize: "10.5px"
    fontWeight: 500
    letterSpacing: "0.07em"
rounded:
  tight: "2px"
  focus: "3px"
  sm: "4px"
  full: "9999px"
motion:
  ease-out: "cubic-bezier(0.23, 1, 0.32, 1)"
  duration-feedback: "120ms"
  duration-orient: "140ms"
  duration-expand: "200ms"
spacing:
  cell-x: "12px"
  cell-y: "6px"
  panel-x: "16px"
  panel-y: "10px"
  gutter: "16px"
  gutter-wide: "24px"
components:
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "0px"
  panel-header:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    typography: "{typography.title}"
    padding: "10px 16px"
  table-header-cell:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.muted-foreground}"
    typography: "{typography.label}"
    padding: "8px 12px"
  table-row:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    typography: "{typography.body-dense}"
    padding: "6px 12px"
    height: "28px"
  table-row-hover:
    backgroundColor: "color-mix(in oklch, var(--muted) 50%, transparent)"
  table-row-expanded:
    backgroundColor: "color-mix(in oklch, var(--muted) 70%, transparent)"
  pill-critical:
    backgroundColor: "{colors.critical-bg}"
    textColor: "{colors.critical}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "2px 6px"
  pill-warn:
    backgroundColor: "{colors.warn-bg}"
    textColor: "{colors.warn}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "2px 6px"
  pill-ok:
    backgroundColor: "{colors.ok-bg}"
    textColor: "{colors.ok}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "2px 6px"
  pill-info:
    backgroundColor: "{colors.info-bg}"
    textColor: "{colors.info}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "2px 6px"
  pill-neutral:
    backgroundColor: "{colors.muted}"
    textColor: "{colors.muted-foreground}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "2px 6px"
  decision-button:
    backgroundColor: "transparent"
    textColor: "{colors.foreground}"
    typography: "{typography.micro}"
    rounded: "{rounded.sm}"
    padding: "4px 8px"
    height: "28px"
  decision-button-hover:
    backgroundColor: "{colors.muted}"
  decision-button-subtle:
    backgroundColor: "transparent"
    textColor: "{colors.muted-foreground}"
    typography: "{typography.micro}"
    rounded: "{rounded.sm}"
    padding: "4px 8px"
    height: "28px"
  filter-chip:
    backgroundColor: "transparent"
    textColor: "{colors.muted-foreground}"
    typography: "{typography.micro}"
    rounded: "{rounded.sm}"
    padding: "3px 8px"
  filter-chip-active:
    backgroundColor: "color-mix(in oklch, var(--accent) 10%, transparent)"
    textColor: "{colors.foreground}"
    typography: "{typography.micro}"
    rounded: "{rounded.sm}"
    padding: "3px 8px"
  input-text:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    typography: "{typography.body-dense}"
    rounded: "{rounded.sm}"
    padding: "6px 10px"
    height: "34px"
  tab:
    backgroundColor: "transparent"
    textColor: "{colors.muted-foreground}"
    typography: "{typography.body-dense}"
    padding: "0 12px"
    height: "36px"
  tab-active:
    backgroundColor: "transparent"
    textColor: "{colors.foreground}"
    typography: "{typography.body-dense}"
    padding: "0 12px"
    height: "36px"
  status-dot:
    rounded: "{rounded.full}"
    size: "7px"
---

# Design System: Reconciliation Console

## Overview

**Creative North Star: "The Working Window"**

This console is one window in a row of windows. The operator has a bank portal on one
side and a spreadsheet on the other, and this has to sit between them without asking
for a different kind of attention than either. That is the whole design thesis: it
belongs in that row. System type, system density, system restraint. There is no front
door, no brand moment, no first impression to earn — the operator arrives mid-task and
leaves mid-task, several times a day.

The surface is a single cool-grey ramp, near-neutral (chroma 0.002–0.014) with a
consistent blue-leaning hue around 250–254, so nothing in the base palette reads as a
colour decision. Against that ramp, four chromatic tokens — critical, warn, ok, info —
are the only saturated things on screen, and they mean severity and nothing else.
Colour is a signal with a fixed cost: every additional coloured element makes the one
row that needs a person harder to find. Structure comes from hairline rules and flat
panels, never from shadow, never from a card floated over a background.

Density is deliberate and is the feature the operator would miss first. Table rows are
28px, base type is 13px, table type 12.5px, and metadata drops to 11.5px. An operator
scanning 150 variances should not scroll through padding to do it. Figures are set in
Geist Mono with tabular numerals via the `.num` class, so digits fall into a column and
a wrong order of magnitude is visible by shape before it is read.

**Key Characteristics:**

- One cool-grey ramp; four chromatic tokens, all of them severity.
- Accent is reserved for links and the active tab marker. It is not a brand colour.
- Rules and flat panels. Zero `box-shadow` in the entire system.
- 28px rows, 13px base, 10.5px uppercase labels at 0.07em.
- Mono tabular figures via `.num`; a proportional number in a table is a visible bug.
- Dark theme is authored, not derived: surfaces get **lighter** as they elevate.

## Colors

A single cool-grey ramp carries every surface, every rule, and all text; saturation
appears only where the interface is telling the operator how bad something is.

### Primary

- **Slate Link** (`accent`, light `oklch(0.45 0.035 253)` / dark
  `oklch(0.72 0.06 250)`): the only non-severity colour in the system, and barely a
  colour at 0.035 chroma. It marks links (a copyable ID that navigates), the active
  tab's 2px bottom marker, and the active filter chip's border and 10% tint. It is
  never a button fill, never a header background, and never decorative.
  `accent-foreground` (light `oklch(0.99 0 0)` / dark `oklch(0.16 0.01 254)`) exists
  for the inverted-on-accent case and is currently unused — leave it that way unless a
  real filled-accent surface appears.
- **Focus Slate** (`ring`, light `oklch(0.55 0.09 250)` / dark
  `oklch(0.66 0.1 250)`): higher chroma than accent because it must be unmistakable.
  Used for the one app-wide focus ring and, at 28% mix, for `::selection`.

### Secondary

None. The system has one accent and four severity tokens. Do not introduce a second
brand hue.

### Neutral

- **Page Grey** (`background`, light `oklch(0.985 0.002 250)` / dark
  `oklch(0.165 0.008 254)`): the ground behind everything. In light it sits *below*
  surface; in dark it is the darkest value in the system.
- **Panel White** (`surface`, light `oklch(1 0 0)` / dark `oklch(0.196 0.009 254)`):
  every panel, the sticky header (at 95% with a backdrop blur), and table body rows.
- **Raised Grey** (`surface-raised`, light `oklch(0.975 0.003 250)` / dark
  `oklch(0.232 0.01 254)`): the sticky table head, and any surface that sits *on* a
  panel. Note the direction reversal between themes — this is the elevation rule.
- **Ink** (`foreground`, light `oklch(0.21 0.012 254)` / dark
  `oklch(0.93 0.004 250)`): all primary text and every figure.
- **Second Voice** (`muted-foreground`, light `oklch(0.47 0.012 254)` / dark
  `oklch(0.71 0.011 252)`): labels, hints, subcategories, footnotes, unresolved values,
  and neutral status dots. Roughly half the text on a dense screen.
- **Wash** (`muted`, light `oklch(0.955 0.004 250)` / dark `oklch(0.246 0.01 254)`):
  row hover (50%), expanded row (70%), neutral pill fill, skeleton fill, ghost hover.
- **Hairline** (`border`, light `oklch(0.9 0.005 250)` / dark
  `oklch(0.29 0.011 254)`): the default border colour for *every* element — it is
  assigned globally via `* { border-color: var(--border) }`, so a bordered element that
  says nothing about colour is already correct.
- **Rule** (`border-strong`, light `oklch(0.82 0.008 252)` / dark
  `oklch(0.38 0.014 254)`): reserved for structural separation — the table head's
  bottom rule, the primary decision button's edge, the Ask submit button, scrollbar
  thumbs. It marks hierarchy, not emphasis.

### Tertiary — Severity

The four chromatic pairs. Each has a text-weight token and a background-weight `-bg`
token, and they are always used together with the border at 25% of the text token.

- **Critical** (light `oklch(0.48 0.17 25)` on `oklch(0.955 0.028 25)` / dark
  `oklch(0.75 0.15 25)` on `oklch(0.29 0.07 25)`): failure, an untraceable figure, an
  unrecoverable error, a stopped scheduler. The highest chroma in the system (0.17)
  and the only token permitted to dominate a screen.
- **Warn** (light `oklch(0.47 0.1 75)` on `oklch(0.96 0.038 85)` / dark
  `oklch(0.83 0.13 85)` on `oklch(0.3 0.06 75)`): an open variance, an unexplained
  value, confidence below 0.5. This is the "needs a person" colour, and the queue is
  designed so that it is the thing the eye lands on.
- **OK** (light `oklch(0.44 0.09 155)` on `oklch(0.955 0.03 155)` / dark
  `oklch(0.76 0.12 155)` on `oklch(0.27 0.05 155)`): complete, verified, traced,
  accepted, scheduler running. Deliberately the lowest-chroma severity in light mode —
  good news does not need to shout.
- **Info** (light `oklch(0.47 0.09 245)` on `oklch(0.955 0.028 245)` / dark
  `oklch(0.76 0.1 245)` on `oklch(0.28 0.05 245)`): in-flight state, an explained but
  undecided variance, a human-authored audit event.

### Named Rules

**The Severity-Only Rule.** If a coloured element is not reporting how bad something
is, the colour is wrong. Category, source, batch, tier, strategy, and every other
dimension are grey. There is no palette to assign a new dimension to, and inventing
one breaks the queue's only scanning mechanism.

**The Two-Token Rule.** A severity is never a text colour alone. It is
`text-{severity}` + `bg-{severity}-bg` + `border-{severity}/25`, so it reads at a
glance and still passes contrast against its own tint. The single exception is a
figure's inline emphasis — a sub-0.5 confidence value takes `text-warn` on the row's
own background, because a tinted cell inside a 28px row is heavier than the signal
deserves.

**The Colour-Plus-Word Rule.** Severity always ships with the word. A pill states its
status in text; the traceability line says "could not be traced" rather than relying on
a red chip. Colour accelerates a scan the operator could complete without it.

## Typography

**UI Font:** Geist Sans, loaded via `next/font` as `--font-geist-sans`, with
`ui-sans-serif, system-ui, sans-serif` behind it.
**Figure Font:** Geist Mono as `--font-geist-mono`, with
`ui-monospace, "SF Mono", monospace` behind it.
**Display Font:** none. There is no display tier in this system.

**Character:** Two members of one family doing two different jobs. Geist Sans is a
neutral grotesque that reads as system UI rather than as a brand — exactly what a
window sitting beside a bank portal should be. Geist Mono carries every figure, and
the shift from proportional to monospace is the visible line between prose and data.

### Hierarchy

- **Metric Large** (Mono, 600, 26px / 32px, `-0.01em`, tabular): the single headline
  figure on a batch overview. One per screen region at most.
- **Metric** (Mono, 600, 17px / 24px, `-0.01em`, tabular): the standard `Metric`
  component value — the number the operator came to read.
- **Figure** (Mono, 400, 12.5px, `-0.01em`, tabular): every amount, ratio, ID, ref, and
  count inside a table or definition list. Applied through the `.num` class.
- **Title** (Sans, 600, 13px, `-0.01em` via `tracking-tight`): panel headers and the
  status page's `h1`. There is no larger heading anywhere in the console.
- **Body** (Sans, 400, 13px / 1.45): the `body` default. Prose that is genuinely being
  read — descriptions, explanations — capped at `max-w-prose`.
- **Body Dense** (Sans, 400, 12.5px): table cells, tabs, inputs, buttons. The default
  for anything inside a data structure.
- **Secondary** (Sans, 400, 12px): categories, suggested actions, in-row detail.
- **Micro** (Sans, 400, 11.5px, or 11px for the least important line): hints,
  subcategories, counts in a panel header, footnotes, decision buttons.
- **Label** (Sans, 500, 10.5px, `0.07em`, uppercase, `muted-foreground`): the `.label`
  class. Every table column head, every metric label, every detail-section heading.
  Present, but never competing with the value beneath it.

### Named Rules

**The `.num` Rule.** Every number the operator might compare against another number
carries `.num`. It is not a style choice — it is what makes a wrong order of magnitude
visible by column shape before the digits are read. A proportional figure in a table is
a defect, not a variation.

**The No-Display Rule.** 26px is the largest type in the system and it is a figure, not
a heading. There is no hero type, no italic serif, and no font that is not Geist.

**The Label-Above Rule.** A label sits above its value at 10.5px uppercase and never
grows to compete with it. If a label needs more prominence, the value is in the wrong
place.

## Layout

A single centred column, `max-width: 1400px`, with 16px gutters that widen to 24px at
`md`. The chrome is minimal and fixed: a 44px sticky header (`surface` at 95% with a
backdrop blur, hairline bottom rule) holding the wordmark and two nav links, and a
static footer stating that all figures are computed from integer paise.

Inside `main`, vertical rhythm is a 16px stack (`space-y-4`) of full-width panels. Panels
do not float, do not centre themselves, and do not have a maximum width narrower than
the column. Batch sub-navigation is a 36px tab strip sitting directly on the content's
top rule.

Within a panel the spacing is deliberately tighter than the page: 16px horizontal /
10px vertical for panel headers and filter bars, and 12px / 6px for table cells, which
is what produces the 28px row. The variance detail pane splits at `lg` into
`minmax(0,1fr) minmax(0,340px)` — evidence on the left, the model's account of itself
on the right, so the records are read before the explanation is.

Responsive behaviour is horizontal-scroll-first, not stack-first: `DataTable` wraps its
table in `overflow-x-auto` and preserves every column rather than collapsing a dense
grid into cards. The operator at partial window width would rather scroll a table
sideways than lose the column alignment that makes the table readable.

### Named Rules

**The Column-Preserving Rule.** A wide table scrolls inside its own container. It never
reflows into stacked cards, and the page body never scrolls horizontally.

**The 28px Rule.** A table row is 28px (12px / 6px cell padding at 12.5px type). Any
change that increases row height needs a reason stronger than "it looks roomier".

## Elevation & Depth

**There are no shadows in this system.** `box-shadow` appears nowhere in `globals.css`
and nowhere in the components. Depth is carried entirely by tonal steps and hairline
rules: a panel is `surface` inside a `border` on a `background` ground, and a raised
element steps one value along the ramp rather than lifting off the page.

Light and dark move in opposite directions, and this is the system's most distinctive
property. In light, `background` (0.985) is the brightest ground and surfaces step
*down* toward it — `surface` 1.0, `surface-raised` 0.975 — reading as paper on a
desk. In dark, the ramp inverts its logic rather than its values: `background` 0.165 →
`surface` 0.196 → `surface-raised` 0.232. **Dark surfaces get lighter as they
elevate.** A dark theme produced by inverting the light values would put the table head
*darker* than the rows and destroy the depth cue.

Motion is banned by default and hover is instant. Exactly four animations exist, each
built from the tokens above: the variance row's expand and collapse
(`grid-template-rows` + opacity, 200ms), a figure marking that it changed under a live
refresh (background tint decaying over 200ms), arrival in a new console section
(opacity, 140ms), and in-flight feedback on an operator-triggered request (opacity,
120ms). Each carries its own reduced-motion variant, keeping the opacity or colour
change that makes a state legible and dropping the size change. Nothing loops, nothing
enters on page load, and nothing moves that the operator is not directly manipulating.

### Named Rules

**The No-Shadow Rule.** Depth is a tonal step plus a hairline. A drop shadow anywhere
in this console — and especially wrapped around a single number — is a defect.

**The Lighter-When-Raised Rule.** In dark mode, elevation increases lightness. Any new
dark surface value must be lighter than the surface it sits on, never darker.

**The Flat-Panel Rule.** Panels do not nest. A section inside a panel is a `.label`
heading and content, not a second bordered box.

## Shapes

Near-square. Radii exist to soften a hit target, not to give the interface a
personality: `rounded-sm` (4px) on pills, chips, buttons, inputs, and the row-expand
control; 3px on the focus ring and skeleton; 2px on the smallest inline marks; and
`rounded-full` only on the 7px status dot.

**Panels have no radius at all.** A panel is a rectangle with a 1px `border` hairline —
the same treatment a spreadsheet gives a range. Borders do all the structural work, at
two weights only: `border` for every hairline (assigned globally, so it is the default
for any bordered element) and `border-strong` for the table head's bottom rule and the
edge of a primary action. Severity-tinted containers use the severity token at 25–40%.

### Named Rules

**The Square-Panel Rule.** Containers are rectangular. Rounding appears only on things
the operator clicks or on a dot.

## Components

### Panels

- **Character:** a bordered rectangle, nothing more.
- **Shape:** no radius; 1px `border` hairline.
- **Background:** `surface`.
- **Header:** 10px / 16px padding, hairline bottom rule, 13px semibold title, optional
  12px `muted-foreground` description beneath, optional right slot for a count line
  (11.5px `.num`, `muted-foreground`).
- **Nesting:** none. Use a `.label` heading for internal sections.

### Tables

- **Head:** sticky, `surface-raised`, `border-strong` bottom rule, cells are `.label`
  (10.5px uppercase) at 8px / 12px.
- **Row:** 28px — 6px / 12px cells at 12.5px, hairline bottom border.
- **States:** hover `muted` at 50%; expanded `muted` at 70%; pending `opacity-60`
  while an optimistic write is in flight.
- **Numeric columns:** right-aligned and `.num`. Value and confidence sort by clicking
  the column's own label; the active sort key shows its direction inline.
- **Expand control:** a 24px square ghost button carrying `▶` / `▼` at 10px, with
  `aria-expanded`, `aria-controls`, and a screen-reader label naming the row's amount.

### Pills

- **Style:** `rounded-sm`, 2px / 6px, 10.5px uppercase 500, with the severity's three
  tokens — text, `-bg` fill, and border at 25%.
- **Content:** always a word, never a bare colour. Status enums pass through `humanise`
  before display.
- **Figure pills:** a cited amount renders as an `ok` or `critical` pill with `.num`
  and `normal-case`, marking traceable versus untraceable at a glance.

### Buttons

There is no filled primary button in this console. Actions are bordered and quiet,
because on a queue screen a row of filled buttons would out-shout the severity signal
the operator is scanning for.

- **Decision (Accept):** 28px min-height, `rounded-sm`, `border-strong`, transparent
  fill, 11.5px, hover `muted`.
- **Decision (Write off):** same geometry, `border` hairline and `muted-foreground`
  text — subordinate but not hidden.
- **Submit (Ask):** 34px min-height, `border-strong`, 12.5px 500, hover `muted`.
- **Disabled:** `opacity-50` and `cursor-not-allowed`.
- **Ghost:** transparent, `muted-foreground`, hover `muted` + `foreground`. Used for
  nav links and the expand control.

### Filter Chips

- **Style:** `rounded-sm`, 3px / 8px, 11.5px, hairline border, `muted-foreground`.
- **Active:** `accent` border at 40%, `accent` fill at 10%, `foreground` text, 500,
  plus `aria-current`. One of the two sanctioned uses of accent.
- **Grouping:** each group is preceded by a `.label` ("Status", "Category"); every group
  carries an explicit "All" chip rather than relying on an empty state to mean all.

### Inputs

- **Style:** 34px min-height, `surface`, hairline border, `rounded-sm`, 6px / 10px,
  12.5px, placeholder in `muted-foreground`.
- **Focus:** the global treatment only — 2px `ring` outline at 2px offset. Fields do
  not get their own focus colour.

### Navigation

- **Header nav:** 12.5px `muted-foreground` links, 6px / 8px, hover `muted` +
  `foreground`.
- **Batch tabs:** 36px, 12.5px, 12px horizontal, `border-b-2` transparent at rest;
  active takes `border-accent`, `font-medium`, `foreground`, and `aria-current="page"`.
  The 2px accent underline is the system's only persistent accent mark.

### Status Dot

- **Style:** 7px circle, `rounded-full`, filled with the severity token — or
  `muted-foreground` for neutral. Always `aria-hidden`; the adjacent text carries the
  meaning.
- **No live variant.** Status dots never pulse. A dot reports a state; a pulsing dot
  competes with the severity colours an operator is scanning for.

### Metric

- **Structure:** `.label` above, `.num` value below at 17px (or 26px for `lg`), optional
  11px `muted-foreground` hint beneath.
- **Colour:** `foreground` unless a severity applies, in which case the value takes the
  severity's *text* token only — no fill, no border, no card.

### Empty, Error, and Loading States

- **Empty:** centred, 56px vertical padding, 13px medium title over a 12px
  `muted-foreground` line that says what is actually true — a filtered-out queue and a
  genuinely clean batch get different sentences.
- **Error:** a panel with `critical` border at 30% and `critical-bg` at 40%; 13px
  semibold `critical` title, 12px detail at 80% `foreground`, optional 11.5px hint.
- **Skeleton:** `muted` fill, 3px radius, static. It holds the shape of what is
  loading; it does not shimmer.

### Traceability Block (signature component)

The component the product exists for. Under a "Cited amounts" `.label`, every figure
the model quoted renders as a `.num` pill — `ok` if it was found in the records above,
`critical` if it was not — followed by a plain-English verdict line: "Every figure in
this explanation was found in the records above", or "Highlighted figures could not be
traced to the records above — treat this explanation with suspicion." The Ask surface
uses the same grammar at answer level, pairing a status dot with "Every figure traced"
or "Withheld — untraceable figure".

Nothing about this block is decorative, and it is never collapsed by default when a
figure failed to trace.

## Do's and Don'ts

### Do:

- **Do** treat `web/app/globals.css` as the normative token source. This file describes
  it; where they disagree, the CSS wins and this file is wrong.
- **Do** put every number the operator may compare into `.num`.
- **Do** use a severity's three tokens together — text, `-bg`, and border at 25%.
- **Do** gloss backend enums through `humanise` or an explicit copy map before display;
  `book_to_fee_account` reaches the operator as "Post to the payment-processing fee
  account".
- **Do** say what is absent. A null confidence renders as `—`, an unexplained variance
  says the model declined to classify rather than guess.
- **Do** keep new dark values lighter than the surface they sit on.
- **Do** let a wide table scroll inside its own container and keep every column.
- **Do** state severity in words alongside the colour.

### Don't:

- **Don't** add a `box-shadow` anywhere — least of all around a single number.
- **Don't** nest a card inside a card. Use a `.label` heading.
- **Don't** use `accent` for anything except a link, the active tab marker, and the
  active filter chip. It is not a brand colour and it is not a button fill.
- **Don't** colour a non-severity dimension. Category, source, tier, and strategy are
  grey.
- **Don't** introduce a hero section, a marketing gradient, glassmorphism, an
  illustration, an emoji, decorative iconography, italic serif display type, or the
  warm undifferentiated "AI beige" palette of generated product UI.
- **Don't** animate anything outside the four sanctioned animations, and never a status
  dot, a severity badge, a chart entrance, or a page-load entrance.
- **Don't** write celebratory microcopy. A cleared queue is stated, not congratulated.
- **Don't** grow a row past 28px or a label past 10.5px without a stated reason.
- **Don't** revive `web/components/ui/button.tsx`. It is unused shadcn scaffolding
  referencing `--primary`, `--secondary`, `--destructive`, and `--radius-md`, none of
  which this system defines; it should be deleted, not wired up.

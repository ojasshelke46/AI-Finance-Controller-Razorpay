# Brand — Reconciliation Console

_Status: active_

Not a consumer dashboard. This is a tool a finance operations person keeps open all
day, next to a bank portal and a spreadsheet. It should look like it belongs in that
row of windows.

## Principles

1. **Data first, chrome last.** No hero sections, no illustrations, no cards with
   drop shadows around a single number. Rows, rules, and figures.
2. **Colour marks severity and nothing else.** If everything is coloured, nothing
   reads as urgent, and the one row that needs attention stops standing out. The base
   palette is a single cool-grey ramp; chromatic tokens appear only on status.
3. **Figures are monospace and tabular.** Digits align in a column so a wrong order
   of magnitude is visible by shape before it is read.
4. **Density is a feature.** 28px rows, 12–13px type. An operator scanning 150
   variances should not scroll through padding to do it.
5. **Every number is traceable.** Where a figure came from a model rather than from
   arithmetic, the interface says so.

## Palette

Defined as tokens in `web/app/globals.css`. Light and dark both explicit — dark is
not an inversion, surfaces get lighter as they elevate.

| Token | Role |
|---|---|
| `background` / `surface` / `surface-raised` | page, panel, nested panel |
| `foreground` / `muted-foreground` | primary text, secondary text |
| `border` / `border-strong` | hairline rules, table head rules |
| `accent` | links and the active tab marker — the only non-severity colour |
| `critical` | failure, untraceable figure, unrecoverable error |
| `warn` | open variance, unexplained value — needs a person |
| `ok` | complete, verified, traced |
| `info` | in-flight, human-authored audit event |

## Typography

- **UI:** Geist Sans via `next/font`, 13px base.
- **Figures:** Geist Mono, `font-variant-numeric: tabular-nums`, applied through the
  `.num` class so a stray proportional number in a table is a visible mistake.
- **Labels:** 10.5px, uppercase, 0.07em tracking, muted — present but never competing
  with the value beneath them.

## Voice

Plain, specific, and never cheerful about money. "Needs a person to decide", not
"Action required!". State what is true and what it costs: "Highlighted figures could
not be traced to the records above — treat this explanation with suspicion."

Enum values from the backend are always glossed into English before display. An
operator reading `book_to_fee_account` cold should see "Post to the payment-processing
fee account".

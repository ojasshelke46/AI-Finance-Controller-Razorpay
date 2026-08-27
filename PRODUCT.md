# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary: a finance operations person.** They keep this console open all day, in a
row of windows next to a bank portal and a spreadsheet, and switch between the three
constantly. In a working session they scan 150+ variances, often quickly, often at the
end of a long shift. Their job is not to browse: it is to get through the queue, decide
the cases a machine could not decide, and be able to defend every decision afterwards.

That scene sets the bar. They arrive mid-task, not at a front door. They already know
the domain vocabulary. They will not read an onboarding tour, and they will notice
padding before they notice polish, because padding is what stands between them and
the next row.

## Product Purpose

Reconcile payments across three sources — Razorpay settlements, the bank statement,
and the internal ledger — and surface only what could not be resolved automatically.
The matcher works in tiers (exact, normalised, fee-aware, aggregate); whatever survives
matching becomes a variance with an explanation, a confidence, and a suggested action.

Success is the operator reaching an empty queue with every decision traceable. Not
time-on-site, not engagement. An operator who never has to open this console because
the system resolved everything itself is the best possible outcome, not a failure.

## Positioning

The console does not ask to be trusted; it shows its work. Every variance carries the
underlying records, the matching tier and strategy that grouped them, the residual, and
the specific figures the explanation cited — each marked traceable or not. Where a
figure came from a model rather than from arithmetic, the interface says so on screen,
and the Q&A surface withholds an answer outright when a figure in it cannot be traced
back to the records. A neighbouring tool can also call an LLM; it cannot truthfully
copy "we tell you, per figure, which numbers we could not verify."

## Operating Context

- **Windowed, not full-screen.** One of several windows, often at partial width,
  beside a bank portal and a spreadsheet. It should look like it belongs in that row.
- **Long sessions, repeat visits.** Opened in the morning and left open. Auto-refresh
  (30s) runs on the status page, so the interface changes under the operator's eyes
  without them asking.
- **Queue work, not exploration.** The dominant motion is scan → expand a row → read
  the evidence → decide → next row. Sorting by value or confidence, and filtering by
  status or category, are how the queue is narrowed.
- **Figures are integer paise.** Nothing is rounded before display. Amounts are
  Indian-locale formatted; times use `en-IN`, 24-hour.
- **Autonomous background.** A scheduler polls Razorpay, resumes stalled batches,
  retries unexplained variances and writes a daily rollup on a fixed schedule. The
  status page reports whether it is running; the operator does not drive it.

## Capabilities and Constraints

- **Surfaces:** Status (`/`), Batches list (`/batches`), and per-batch Overview,
  Variance queue, Audit trail, and Ask (Q&A) tabs.
- **Decisions available on a variance:** Accept, or Write off. Applied optimistically;
  the server write is authoritative and a failure rolls the row back with a message.
- **Backend enums are never displayed raw.** `book_to_fee_account` reaches the
  operator as "Post to the payment-processing fee account"; `flag_for_human` as
  "Needs a person to decide". Any new enum needs a gloss before it ships.
- **Model output is bounded, not assumed.** A variance may legitimately have no
  explanation ("The model declined to classify this case rather than guess") and a
  null confidence, which renders as an em dash — never as zero.
- **Stack:** Next.js 15 / React 19 / Tailwind v4 front end (`web/`), FastAPI +
  Supabase back end (`api/`). Tokens live in `web/app/globals.css`.
- **Known drift, not product truth:** `web/components/ui/button.tsx` is unused shadcn
  scaffolding referencing tokens (`--primary`, `--secondary`, `--destructive`,
  `--radius-md`) that this system does not define. It is not part of the console and
  should be deleted rather than wired up.

## Brand Commitments

**Name:** Reconciliation Console. **Voice:** plain, specific, never cheerful about
money. "Needs a person to decide", not "Action required!". State what is true and what
it costs: "Highlighted figures could not be traced to the records above — treat this
explanation with suspicion." No exclamation marks, no congratulation on a cleared
queue, no first-person system voice.

**Mode: Operate.** This is a finance operations console — not a landing page and not a
consumer dashboard. Every design decision serves an operator completing a task, never
persuasion. There is nothing on any screen whose job is to convince.

**Anti-references — banned outright:**

- hero sections
- marketing gradients
- glassmorphism
- cards with drop shadows wrapped around a single number
- illustrations
- emoji
- decorative iconography (an icon must carry meaning no adjacent word carries)
- celebratory microcopy
- italic serif display type
- "AI beige" (the warm, soft, undifferentiated palette of generated product UI)
- nested cards
- pulsing status dots — no exceptions. The scheduler heartbeat used to pulse; it does
  not any more.

**Motion is banned by default.** This is a dense tool where an operator scans 150+ rows
fast, often tired. The severity colours are the only thing that should pull the eye, and
motion that carries no information competes with them directly. Exactly four animations
are permitted, and the list is closed:

1. Variance row expand and collapse — height and opacity, so the explanation reads as
   the row opening rather than as content appearing from nowhere.
2. A figure changing under a live update — marks that a value moved, nothing more.
3. Navigation between console sections — orientation only, fast enough not to be felt.
4. In-flight feedback for a request the operator triggered — Q&A submission and variance
   decisions. Feedback that the input was received, not decoration.

Everything else is banned, explicitly including status dots, severity badges, funnel or
chart entrances, hover effects that move layout, skeleton shimmer, anything on a loop,
anything that scales or slides an element not being directly manipulated, and any
entrance animation on page load. A table of 150 rows renders at once; it never cascades.

`brand.md` at the repo root is the long-form statement of the same commitments and
remains valid; where the two disagree, this file is the product record and
`DESIGN.md` is the visual record.

## Evidence on Hand

- `brand.md` — active brand statement, authored before this file.
- `web/app/globals.css` — the normative token source. Authoritative over any
  documentation, including `DESIGN.md`.
- Live console surfaces listed above, backed by a real matching engine
  (`api/matching/tier1..tier4`), explainer (`api/explain/`), and Q&A route.
- No customers, testimonials, benchmarks, pricing, SLAs, or certifications exist.
  Future work must not fabricate them.

## Product Principles

1. **Every number is traceable.** Where a figure came from a model rather than from
   arithmetic, the interface says so on screen. An untraceable figure is marked as
   untraceable, not quietly dropped and not quietly shown.
2. **Density is a feature.** 28px rows, 12–13px type. An operator scanning 150
   variances should not scroll through padding to do it.
3. **Colour marks severity and nothing else.** If everything is coloured, nothing
   reads as urgent, and the one row that needs attention stops standing out.
4. **Enum in, English out.** No operator should have to have read the prompt, the
   schema, or the matcher to understand a word on screen.
5. **Absence is stated, never implied.** No data, no explanation, and no confidence
   each have their own honest rendering. A blank cell is a bug.

## Accessibility & Inclusion

Keyboard-first: a skip link, one focus treatment for the whole app (2px ring, 2px
offset), and `aria-expanded` / `aria-controls` on every expandable row.
`prefers-reduced-motion: reduce` disables all animation, including the scheduler
heartbeat and skeleton shimmer. Severity is never carried by colour alone — a pill
carries its own word, and the traceability line states in text what the colour marks.
Both light and dark themes are explicit and independently legible; dark is not an
inversion.

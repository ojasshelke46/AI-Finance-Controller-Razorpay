# Console audit — 2026-08-27

Audit only. No code was changed; `git diff` is empty.

**Scope:** all six routes plus `web/components/*.tsx`, audited against `brand.md`,
`PRODUCT.md`, and `DESIGN.md`, followed by a detector pass over `web/`.

**Method note.** The redesign skill used for this pass is written for marketing
surfaces. Its checklist prescribes glassmorphism, grain overlays, background imagery,
"double the spacing", avoiding all-caps labels, and avoiding dense layouts — all of
which `PRODUCT.md` bans by name or Operate mode inverts. Those items were treated as
non-findings and are listed under *Advice rejected* at the end. Everything below comes
from the project's own authority.

**Detector.** `npx impeccable detect web/` resolves to the local detector at
`.claude/skills/impeccable/scripts/detect.mjs`; there is no `impeccable` package on
npm, so the npx form would have installed nothing or something unrelated. Run against
the Next.js project root it declines and asks for a URL; run against the file list it
returns `[]` with exit 0 — **zero findings**. That is a genuine clean result for what
static TSX/CSS regex scanning covers (banned fonts, easing, gradient fingerprints,
arbitrary z-index, viewport units). It does not cover the failures in this report,
which are semantic. A full browser pass needs `next dev` plus the FastAPI service
running, since every route renders `ErrorState` without it.

---

## Ranking

Ordered by damage to an operator's ability to finish the queue and defend the result.
Numbering is continuous; the tier headings are the ranking.

### Tier 1 — Breaks or misleads the core task

**1. The variance queue's default sort can bury the largest open variance.**
`variance-queue.tsx:58-68`. Sorting is by `Math.abs(variance_paise)` (or confidence)
across every row regardless of status. A ₹5,00,000 row already accepted or written off
sorts above a ₹4,00,000 row that is still open. The queue's stated job — "largest
first", the thing a person still has to decide — is not what the sort produces. The one
row that most needs attention is placed by a rule that does not know what "needs
attention" means. *Category: hierarchy.*

**2. ~~The Q&A console says an answer was withheld while displaying it.~~ WITHDRAWN.**
`qna-console.tsx:110-124` renders `answer.answer` for both states, which read as a leak
of the unverified draft. It is not: `api/routes/qna.py:405` returns `REFUSAL_MESSAGE` as
the answer whenever verification fails, so the text shown under a "Withheld" pill is the
refusal, not the draft. The console never displays an untraced answer. What did stand
from this finding — the verdict sitting below the words it applies to, and the absence
of any evidence behind "Every figure traced" — is addressed on the Q&A pass.
*Corrected 2026-08-27, during the page 6 rewrite.*

**3. The scan column shows a half-translated enum; the real gloss is hidden.**
`variance-queue.tsx:364` renders `humanise(variance.suggested_action)` → "Book to fee
account". The operator-facing gloss "Post to the payment-processing fee account" lives
in `ACTION_COPY` but only renders inside the expanded row (`526-528`). `humanise()` is a
prettifier — it swaps underscores for spaces — not a translation. The column an
operator scans 150 times per session is the one showing the untranslated value, and the
translation is behind a click. *Category: brand violation (raw enum) / voice.*

**4. Internal severity tokens are printed as user-facing labels.**
`audit-trail.tsx:151-154` renders `<Pill severity={...}>{actionSeverity(event.action)}</Pill>`,
so the pill's text is literally `critical`, `ok`, or `warn`. These are design-system
token names, not English. They also sit directly beside `humanise(event.action)`, which
already says "Batch complete" or "Ingest failed", so the pill adds a second, worse
statement of the same fact. *Category: brand violation (raw enum) / voice.*

**5. Actor and step enums render raw in four places.**
`audit-trail.tsx:144` (`{event.actor}` inside a Pill), `:150` (`{event.step}`), `:76`
and `:91` (the same values as filter chip labels), plus `app/page.tsx:218` and `:223`
on the status page event stream. An operator sees `system`, `scheduler`, `explain`,
`match_tier3` cold. `PRODUCT.md`: "Backend enums are never displayed raw." *Category:
brand violation (raw enum).*

**6. On the variances page, the largest unexplained value is styled identically to the
smallest.** The most important object on this page is the biggest open variance. It is
rendered at `text-[12.5px]` mono with `font-medium` — the same as row 150
(`variance-queue.tsx:339-341`). Its only distinction is being first, which finding 1
already undermines, and having more digits. Meanwhile the eye is pulled to the warn-
tinted Status pill and the two Decide buttons on every row. Nothing in the layout says
"this one, first." The panel header states count, open count and total value
(`:88-92`), but never the largest single exposure. *Category: hierarchy.*

### Tier 2 — Costs the operator time or inverts what matters

**7. The status page gives its largest type to money, not to autonomy proof.**
The file's own comment (`app/page.tsx:20-25`) states the page answers one question — is
the system working unattended — and that a screenshot should settle it. But the only
`size="lg"` metric on the page is "Total unexplained value" at 26px (`:126-136`), two
panels down. The scheduler proof — last run, next run, batches today — is 17px
(`:84-108`), and the strongest signal that it ran unattended is a 7px dot. The page has
two claims to primacy and resolves it in favour of the money. If the stated job is
correct, the 26px slot is in the wrong panel. *Category: hierarchy.*

**8. On the batch page, eval metrics outrank the operator's money.**
`app/batches/[id]/page.tsx:71-84`. Precision, Recall and F1 carry `size="lg"` (26px).
"Unexplained" — the figure that determines whether anyone has work to do — is 17px, and
sits sixth. Precision and recall are how the *system* is judged; unexplained value is
what the *operator* is judged on. *Category: hierarchy.*

**9. The batch list cannot be ranked by exposure.**
`app/batches/page.tsx:49-62`. Nine columns, no sort controls anywhere, and the two that
matter — Open and Unexplained — are eighth and ninth. To find the batch with the most
money outstanding, the operator reads down two right-hand columns by eye. The variance
queue has sortable columns (`SortButton`); this table did not get them. *Category:
hierarchy.*

**10. Accent is used as a chart fill on the tier funnel.**
`app/batches/[id]/page.tsx:202-206`. Matched tiers get `bg-accent`. Two rules break at
once: accent is reserved for links and the active tab marker, and colour marks severity
and nothing else. "Which tier claimed this record" is a category, not a severity. The
bar for the variance step correctly uses `bg-warn`, which is what makes the accent bars
read as a competing signal rather than as neutral structure. `bg-border-strong` on the
total row is the correct treatment and shows the fix already exists in the file.
*Category: brand violation (colour).*

**11. A panel wraps a single number, and takes half the viewport to do it.**
`app/page.tsx:114-138`. "Unexplained exposure" is a bordered panel with a header, a
description, a pill, and 16px padding around exactly one figure, occupying a full
`1fr` of a two-column grid — roughly 700px of a 1400px column for one value. This is
the anti-reference in `PRODUCT.md` ("cards with drop shadows wrapped around a single
number") in every respect except the shadow. *Category: density / brand violation.*

**12. Operator-facing errors print shell commands.**
`app/page.tsx:36` and `app/batches/page.tsx:29`:
"Start it with: cd api && uvicorn main:app --port 8000". The audience defined in
`PRODUCT.md` is a finance operations person with a bank portal and a spreadsheet open.
This tells them to run a Python ASGI server. The error is correct; its reader is wrong.
*Category: voice.*

### Tier 3 — Erodes the system's own rules

**13. Figures render outside `.num` in three places.**
`app/batches/[id]/page.tsx:102-104` — four counts ("N of M records matched into K
groups · J unmatched") in proportional sans inside a plain `<p>`.
`app/batches/page.tsx:87-90` — the Period column renders both dates without `mono`, so
a date column in a table of dates does not align.
`app/page.tsx:145` — a batch id (`slice(0, 8)`) inside a panel description, proportional.
*Category: brand violation (`.num`).*

**14. Four list surfaces run 34px rows instead of 28px.**
`app/page.tsx:183` (scheduled jobs), `app/batches/[id]/page.tsx:115` (records by
source), `:143` (variances by status), `app/batches/[id]/qna/page.tsx:48` (figures
available) all use `px-4 py-2` against the table standard of `px-3 py-1.5`. Roughly
34px versus 28px. Three of the four are short lists where the cost is small; the
by-status list grows with the enum and the facts list is already eight rows. No reason
is stated for the extra 6px, and the divergence means "a row" has two heights in one
console. *Category: density.*

**15. Three more raw enums, two of them dressed as figures.**
`variance-queue.tsx:347` — `{variance.subcategory}` unglossed.
`variance-queue.tsx:476` — `{variance.match_group.strategy}` rendered inside `.num`,
which styles a strategy name like `amount_date_window` as though it were a figure.
`app/batches/[id]/page.tsx:221` — `{step.strategy}` raw beside each funnel label.
*Category: brand violation (raw enum).*

**16. Engineer telemetry is shown to a finance operator.**
`qna-console.tsx:126` "Guard fired · regenerated" — "guard" is an implementation term
with no operator meaning. `:128-131` "N attempts · 4,812 chars of context". `:158`
"412ms · 1,240 tokens". None of this helps decide whether to trust an answer; the
traceability verdict does that work already. *Category: voice.*

**17. The audit trail's collapsed preview and expanded body are raw payload.**
`audit-trail.tsx:182-191` (`summarise`) emits `key=value` pairs straight from the JSON,
so raw field names appear in the row. `:166-167` dumps `JSON.stringify(detail, null, 2)`
on expand. Defensible as a deliberate machine-record view — the panel description says
so — but it is the only surface in the console that shows the operator unglossed
backend shape, and the collapsed preview leaks it into a row that is not opted into.
*Category: brand violation (raw enum) / voice.*

**18. A raw backend error string is rendered.** `qna-console.tsx:143` prints
`{attempt.error}` verbatim inside the verification detail. *Category: voice.*

### Tier 4 — Cosmetic drift

**19. Row hover is inconsistent.** `app/batches/page.tsx:67` uses `hover:bg-muted/60`;
`variance-queue.tsx:317` uses `hover:bg-muted/50`. Two tables, two hover values.

**20. A whole sentence is set in mono.** `app/batches/[id]/layout.tsx:46` puts `.num` on
a `<p>` containing "· N records · created ...", so the prose words render monospace
alongside the id and count. `.num` is for figures, not for lines that contain figures.

---

## Findings by requested heading

### 1. Brand violations

| # | Violation | Where |
|---|---|---|
| 10 | Accent used as a chart fill for a non-severity dimension | `[id]/page.tsx:206` |
| 3 | `suggested_action` shown via `humanise`, not the gloss | `variance-queue.tsx:364` |
| 4 | Severity token names printed as labels | `audit-trail.tsx:151-154` |
| 5 | `actor` / `step` raw, six sites | `audit-trail.tsx:76,91,144,150`; `page.tsx:218,223` |
| 15 | `subcategory`, `match_group.strategy`, `step.strategy` raw | `variance-queue.tsx:347,476`; `[id]/page.tsx:221` |
| 13 | Figures outside `.num`: funnel footer counts, Period dates, batch id | `[id]/page.tsx:102-104`; `batches/page.tsx:87-90`; `page.tsx:145` |
| 14 | 34px rows against the 28px rule, no reason stated | `page.tsx:183`; `[id]/page.tsx:115,143`; `qna/page.tsx:48` |
| 11 | Panel wrapped around a single number | `page.tsx:114-138` |
| 17 | Raw JSON keys in a collapsed row | `audit-trail.tsx:182-191` |

No other colour misuse found. Every other chromatic use — `text-warn` on open counts
and unexplained values, `info` on human-authored audit events, `border-ok` / `border-critical`
on answers, severity pills — is correctly severity-only. The `info`-for-human-actor
mapping is explicitly sanctioned by `brand.md`.

### 2. Detector findings

**Zero.** `detect.mjs --json` returns `[]`, exit 0, across `globals.css`, all six
routes, and all six components (`ui/button.tsx` included). No rule ids to report.

Two caveats worth recording rather than a clean bill of health: the static path is
regex matching over TSX and CSS and cannot see rendered output, and the browser path
needs both `next dev` and the FastAPI service up or every route renders `ErrorState`.
Every finding in this report was found by reading the code against the brief, not by
the detector — which is the expected division of labour, since none of these are
pattern-matchable defects.

### 3. Hierarchy failures

| Page | What the operator most needs | Is it the most prominent thing? |
|---|---|---|
| Status | Proof the scheduler ran unattended — last run completed, next run scheduled | **No.** Largest type (26px) is unexplained value, two panels down. Autonomy proof is 17px plus a 7px dot. (#7) |
| Batches | Which batch holds the most open money | **No.** Open and Unexplained are columns 8 and 9 of 9, and the table has no sort. (#9) |
| Batch detail | How much fell through to the variance queue | **No.** Precision, Recall and F1 take the three 26px slots; Unexplained is 17px and sixth. (#8) |
| Variances | The largest open variance | **No.** Same 12.5px as every other row; and the sort ignores status, so it may not even be first. (#1, #6) |
| Audit | The human-authored events in a machine trail | **Partly.** The `info` pill does mark them, but at the same size as everything else, and a redundant severity pill competes on every failed or complete row. (#4) |
| Q&A | Whether the answer can be trusted | **No.** The verdict sits below the answer, so the answer is read first, and "Every figure traced" is asserted with no evidence an operator can check. (The claim that an unverified answer leaks was withdrawn — see #2.) |

The pattern across five of six pages: the metric that proves the *system* works
outranks the figure the *operator* acts on.

### 4. Voice failures

- Severity token names as labels: "Critical", "Ok", "Warn" (#4).
- `humanise` standing in for a gloss: "Book to fee account" (#3).
- Raw enums read cold: `system`, `explain`, `match_tier3`, `amount_date_window` (#5, #15).
- Shell commands as operator error guidance (#12).
- "Guard fired · regenerated", "chars of context", "tokens", "ms" (#16).
- Raw backend error text (#18).
- "Every figure traced" asserted with nothing on screen to check it against (#2).

Nothing cheerful was found. No exclamation marks, no congratulation, no "Oops",
no emoji. The empty and error states are notably good: "Every record in this batch
reconciled cleanly. There is nothing for an operator to decide", and "The model
declined to classify this case rather than guess" are both exactly the register
`brand.md` asks for. The failures here are all unglossed-machine, not over-cheerful.

### 5. Density failures

- **#11** — half the status page viewport for one figure, inside a header-plus-padding
  panel. The largest single density cost in the console.
- **#14** — 34px rows in four lists, against a 28px standard the same app enforces
  elsewhere.
- `variance-queue.tsx:434` — the expanded detail uses `px-4 py-4` with `gap-5` and
  `space-y-4` internally, noticeably looser than the 28px table it opens from. Justified
  in part: this is read, not scanned. Noted, not charged.
- `primitives.tsx:190` — `EmptyState` at `py-14` (56px). Correct; an empty queue has no
  rows to cost.
- `app/page.tsx:159-168` — the scored-run panel's four metrics at `gap-y-4` inside
  `py-4` are fine on their own; they only look generous next to #11 taking equal width
  for one number.

No page is under-dense in the way the redesign skill warns about. The density problems
are localised and specific, not systemic.

---

## Advice rejected

From the redesign skill's checklist, deliberately not raised as findings, because
`PRODUCT.md` bans them or Operate mode inverts them:

- "Missing whitespace — double the spacing, let the design breathe." Density is the
  product here; the skill exempts data dashboards in its own text.
- "True glassmorphism", "grain and noise overlays", "spotlight borders", "colored
  tinted shadows", "background imagery behind sections". All banned by name, and the
  system has zero shadows by design.
- "All-caps subheaders everywhere — try lowercase italics or small-caps." The 10.5px
  uppercase label at 0.07em is the documented label style; italic serif is banned.
- "Lucide or Feather icons exclusively — use Phosphor or a custom set." The console
  uses no icon set at all (`lucide-react` is an unused dependency). Decorative
  iconography is banned; the correct action is removing the dependency, not swapping it.
- "Staggered entry, spring physics, smooth scroll with inertia, scroll-driven reveals."
  Motion is deliberately near-absent; the only two animations are gated behind
  `prefers-reduced-motion`.
- "Three equal card columns is the most generic AI layout." The metric grids are data
  rows, not feature cards.
- "Fake round numbers — use organic messy data." Every figure here is real, computed
  from integer paise.

One item from the skill that *does* apply and is already satisfied: skip-to-content
link, focus rings, active nav state, loading skeletons, empty states, error states,
back navigation. All present.

---

## Gate

Written report exists, findings ranked by operational impact. Zero code changes —
`git diff` is empty and no file under `web/` was modified.

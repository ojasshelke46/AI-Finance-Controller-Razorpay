# AI Finance Controller — multi-source payment reconciliation

Reconciles three records of the same money: Razorpay test-mode payments and
settlements pulled from the API, a bank statement CSV, and an internal ledger
XLSX. It produces match groups linking rows that describe one economic event, a
variance queue holding everything that did not reconcile, and for each variance
an LLM-written category, explanation and suggested action. A person works that
queue in the console and accepts, writes off, or reopens each row; every
decision writes an `audit_log` entry recording what the row looked like
beforehand.

## Running now

| | |
|---|---|
| Console | https://ai-finance-controller-razorpay.vercel.app |
| API | https://ai-finance-controller-razorpay-production.up.railway.app |
| Health | [`/health`](https://ai-finance-controller-razorpay-production.up.railway.app/health) — checks Supabase, the LLM chain and Razorpay, and reports which are down rather than a single green tick |

The scheduler runs on the deployed API, so the system keeps working with nobody
watching: it polls Razorpay every 15 minutes, resumes any batch left
non-terminal for 30 minutes, retries still-unexplained variances every 6 hours,
and writes a daily rollup. The status page shows the next run time for each of
those jobs and the events they have written, which is the honest way to show
autonomy — the schedule is a claim, the audit trail is the evidence.

`/health` calls the LLM chain for real, so it takes a few seconds and is
occasionally the slowest thing on the page. That is the check doing its job
rather than reporting a cached opinion.

## Where the numbers come from

Batch `ca2dafbe-995d-4e64-a76e-0da4263d075b`, scored `2026-09-01T21:26:28Z`.
The figures below are the `run_scores` row for that batch and can be read back
with `python -m scripts.run_pipeline ca2dafbe-995d-4e64-a76e-0da4263d075b`. This
run was not triggered by hand: the corpus was generated and left alone, and the
scheduler's `resume_stuck_batches` job picked it up autonomously
(`audit_log`: `resuming_stuck_batch`, 96 minutes after generation, actor
`scheduler`) and ran ingest through score in one uninterrupted pass.

This batch is a **generated corpus**, not live merchant data. Precision and
recall only exist because the generator recorded which rows belong to the same
economic event; no real dataset carries that, and the matchers are firewalled
from reading it (see below). Razorpay test-mode ingestion and the CSV/XLSX file
parsers are real code paths that run, but the numbers here are from the corpus,
because it is the only source that has an answer key to score against.

| | |
|---|---|
| Records processed | 1,198 |
| Match rate | 86.39% (1,035 of 1,198 rows placed in a group) |
| Precision | 1.000000 |
| Recall | 0.998858 |
| F1 | 0.999429 |
| True / false positives | 1,749 / 0 |
| False negatives | 2 |
| Explanation grounding rate | 96.67% |
| Unexplained value left open | ₹494.88 (49,488 paise) |
| Wall clock | 6,612.33s |
| Throughput | 0.1812 records/sec |
| LLM calls served | 23 |
| LLM cost estimate | $0.011450 |

The match rate has a ceiling below 100% by construction. 162 of the 1,198 rows
are noise the corpus injects deliberately — rows belonging to no economic event,
which a correct matcher must leave unmatched. That puts the ceiling at 1,036 of
1,198, or 86.48%; the run reached 86.39%, so it placed 1,035 of the 1,036 rows
that had a counterpart. Precision is pair-level, not group-level (see
[Measuring accuracy](#measuring-accuracy-without-letting-the-matchers-see-it)),
and zero false positives across 1,749 predicted pairs means no two rows from
different economic events were merged.

Wall clock and throughput are `run_scores.wall_clock_seconds` /
`records_per_second`, computed as documented in `eval/scorer.py`: earliest to
latest `audit_log` timestamp for the batch, divided into `total_txns`. Read
literally that is 0.18 records/sec, and read literally is misleading here for a
specific, checkable reason: that span includes the 96 minutes the batch sat
`pending` before the scheduler's own idle threshold
(`STUCK_AFTER_MINUTES = 30` in `runtime/scheduler.py`) made it eligible to
resume, which is autonomy working as designed, not the pipeline being slow.
The pipeline's own internal timer for that run — `audit_log`'s
`batch_complete` event, `elapsed_seconds`, a different field from a different
table than the `run_scores` row above — recorded 695.62 seconds from
`tier1` through `score`, 1,198 ÷ 695.62 ≈ 1.72 records/sec of actual
processing. Both numbers are real; they answer different questions.

The run produced 311 match groups and 169 variances, of which 161 were explained
and 8 remain open for a person.

## Architecture

```mermaid
flowchart TB
    subgraph sources[Sources]
        RZP[Razorpay test mode<br/>payments + settlements]
        CSV[bank_statement.csv]
        XLSX[ledger_export.xlsx]
    end

    RZP --> ING[ingest<br/>ingest/razorpay.py]
    CSV --> FILES[ingest/files.py]
    XLSX --> FILES
    ING --> TXNS[(txns<br/>integer paise)]
    FILES --> TXNS

    TXNS --> T1[tier 1 — exact<br/>ref + amount + date]
    T1 --> T2[tier 2 — normalised ref<br/>+ 1 paise / 3 day window]
    T2 --> T3[tier 3 — fee-aware<br/>gross / net reconstruction]
    T3 --> T4[tier 4 — aggregate settlement<br/>settlement_id, then bounded subset-sum]
    T4 --> GROUPS[(match_groups<br/>match_members)]

    GROUPS --> VQ[variance queue<br/>matching/variance.py]
    VQ --> VAR[(variances)]

    VAR --> EXP[explain<br/>explain/variance_explainer.py]
    EXP --> AUD[audit — second-pass critic<br/>eval/explanation_audit.py]
    AUD --> SCORE[score<br/>eval/scorer.py]
    SCORE --> RS[(run_scores)]

    EXP -. one client, 3 providers .-> LLM[lib/byteplus.py<br/>NVIDIA → BytePlus → OpenRouter]
    AUD -.-> LLM

    SCHED[scheduler — runtime/scheduler.py<br/>poll 15m · resume stuck 15m<br/>retry unexplained 6h · rollup daily] --> PIPE[runtime/pipeline.py<br/>9 resumable stages]
    PIPE --> ING

    RS --> API[FastAPI<br/>routes/console.py · routes/qna.py]
    VAR --> API
    API --> WEB[Next.js console<br/>web/]
    WEB --> HUMAN([person accepts /<br/>writes off / reopens])
    HUMAN --> AL[(audit_log)]
```

The nine stages are `ingest, tier1, tier2, tier3, tier4, variance, explain,
audit, score`, in that order, defined in `STAGES` in
[`api/runtime/pipeline.py`](api/runtime/pipeline.py). Each stage bookends itself
with an `audit_log` row and those rows are the resumption state — there is no
separate progress table. A batch that dies at the explain stage re-runs only
what did not record a `stage_exit`, which matters because the explain and audit
stages cost money in LLM calls.

## Why the model sits downstream of matching, and never inside it

Matching is arithmetic over integer paise, and arithmetic is checkable. A tier-3
match asserts that a gateway gross of 12,000 minus a fee of 240 minus tax of 43
equals the bank's net of 11,717; that claim is either true or it is not, it is
true identically on every run, and when it is wrong you can point at the number
that made it wrong. Handing that to a model would trade a property you can
verify for one you can only sample: the same batch could match differently on
Tuesday, a merged pair would carry no derivation you could audit, and the
failure mode is silent — two unrelated payments confidently joined, with a
fluent sentence explaining why. Reconciliation output is used to move money and
answer auditors, so a matcher that is right 97% of the time in an unpredictable
3% is worse than one that is right less often but tells you exactly which rows
it could not resolve. So the four tiers are deterministic, and everything they
cannot resolve goes to the variance queue rather than being guessed at. The
model then works only on that residue, where the deterministic answer has
already been established to not exist, and where its output is a *description*
routed to a person — never a write to a match group. This is also why the
firewall below is enforced at runtime rather than trusted: the whole argument
collapses if the matchers can see the answer key.

## Measuring accuracy without letting the matchers see it

The synthetic corpus stamps every row it generates with a `truth_group` — rows
projected from the same underlying economic event share one — and marks injected
noise rows `is_noise = true`. Those two columns are the answer key.

The firewall is a runtime assertion, not a convention. Every matcher declares
the only column list it will ever select and checks it against
`FORBIDDEN_COLUMNS = {"truth_group", "is_noise"}` at import, then re-checks the
columns actually returned by the database on every fetch —
`_assert_no_truth_columns` in each of
[`tier1_exact.py`](api/matching/tier1_exact.py),
[`tier2_normalised.py`](api/matching/tier2_normalised.py),
[`tier3_fee_aware.py`](api/matching/tier3_fee_aware.py),
[`tier4_aggregate.py`](api/matching/tier4_aggregate.py) and
[`variance.py`](api/matching/variance.py), and `_assert_no_forbidden` in
[`variance_explainer.py`](api/explain/variance_explainer.py). If a forbidden
column ever appears the run fails loudly rather than producing a number nobody
can trust. [`eval/scorer.py`](api/eval/scorer.py) is the deliberate inverse: it
is the one module that reads `GROUND_TRUTH_COLUMNS`, and it never writes back to
`txns` or `match_groups`.

Scoring is over **pairs**, not groups. A true positive is two rows that share a
`truth_group` placed in the same match group; a false positive is two rows in
one match group that do not share a `truth_group` (or where either is noise); a
false negative is a true pair left split. Group-level scoring would give a
17-member settlement the same weight as a 2-row pair and would score a group
that got 16 of 17 members right as a total failure — pair-level scoring gives
partial credit correctly, which matters most on the many-to-one settlements.

The explanation path is graded separately, because there is no `truth_group` for
"why does this variance exist": a second-pass critic re-reads the original record
alongside the explanation written about it and judges whether the reasoning
follows, whether the cited amounts are really present, and whether the suggested
action fits the category. Anything failing any check is reset to open. That pass
rate is `explanation_grounding_pct`.

A ground-truth leak in that explanation path — the corpus label reaching the
model through ordinary `description` and `raw` record fields — was found, fixed
at context-build time, guarded, and measured. Full methodology, the before/after
numbers, and what the leak was actually worth are in
[EVALUATION.md](EVALUATION.md).

## Setup

Needs Python 3.13 and a Supabase project. Node is needed only for the console
(steps 7–8; the build here was verified on Node 24.11.1 and `web/package.json`
declares no minimum). Razorpay credentials are needed only to ingest live
test-mode activity — the corpus path below does not call Razorpay, so steps 1–6
reach a scored run without them.

1. **Clone and configure the API environment.**
   ```bash
   git clone https://github.com/ojasshelke46/AI-Finance-Controller-Razorpay.git
   cd AI-Finance-Controller-Razorpay
   cp .env.example .env
   ```
   Fill in `.env`: `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` from the Supabase
   project's API settings, and **at least one** LLM key — `NVIDIA_API_KEY`,
   `BYTEPLUS_ARK_API_KEY`, or `OPENROUTER_API_KEY`. The provider chain tries
   them in that order and falls through to the next when one is unset or
   failing, so one working key is enough to complete a run. The base URL and
   model for each provider are already filled in. `RAZORPAY_KEY_ID` and
   `RAZORPAY_KEY_SECRET` (test mode) are only needed for live ingestion and can
   be left blank for steps 2–6; without them `/health` will report Razorpay
   down, which is accurate rather than broken.

   `FRONTEND_ORIGIN` is only needed when the API and the console are deployed to
   different origins. It is appended to the CORS allow-list alongside
   `http://localhost:3000` rather than replacing it, so local development keeps
   working either way; leave it blank when running both locally. The resolved
   list is logged once at startup, so which origins are actually active can be
   read off the deploy log instead of guessed at.

2. **Apply the migrations, in order.** There is no migration runner; paste each
   file into the Supabase SQL editor and run it:
   ```
   api/migrations/0001_init.sql
   api/migrations/0002_recon_engine.sql
   api/migrations/0003_txns_external_ref_unique.sql
   api/migrations/0004_drop_txns_external_ref_unique.sql
   api/migrations/0005_match_groups_variance_components.sql
   api/migrations/0006_run_scores_explanation_grounding.sql
   api/migrations/0007_run_scores_records_per_second.sql
   api/migrations/0008_enable_rls.sql
   ```
   0003 and 0004 must both be applied and in that order — 0004 drops an index
   0003 creates, and the pair is kept rather than collapsed so the schema history
   stays honest.

   0008 turns row level security on for every table and creates **no policies**,
   which is the intended end state rather than an unfinished one. RLS with no
   policies denies the `anon` and `authenticated` roles everything, and nothing
   here needs those roles: the API connects as `service_role`, which bypasses
   RLS, and the console reads through the API rather than querying Supabase from
   the browser. Skip it and the Supabase anon key — which is public by
   construction, since `NEXT_PUBLIC_` variables are compiled into the browser
   bundle — grants anyone who loads the deployed page full read and write on the
   database. See [Known limitations](#known-limitations).

3. **Install the Python dependencies.**
   ```bash
   cd api
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Generate a corpus.** This writes ~1,200 `txns` rows with a known answer key
   and prints the new batch id:
   ```bash
   python -m scripts.generate_corpus
   ```
   The seed is fixed (`CORPUS_SEED`, default `20260826`), so this is
   reproducible. `CORPUS_EVENTS` (default `506`) sets the size.

5. **Run the pipeline over that batch.** Substitute the batch id printed by
   step 4:
   ```bash
   python -m scripts.run_pipeline <batch_id>
   ```
   This runs all nine stages and prints the `run_scores` row. It ends with
   `GATE PASSED` when the batch reached `complete` and a scored row exists. The
   explain and audit stages make real LLM calls, so this takes a few minutes.

6. **Check the answer key never reached a model:**
   ```bash
   python -m scripts.leak_check <batch_id>
   ```

7. **Start the API** (from `api/`, with the venv active):
   ```bash
   uvicorn main:app --reload --port 8000
   ```
   `http://127.0.0.1:8000/health` reports Supabase, Razorpay and LLM
   reachability. Starting the API also starts the scheduler; set
   `SCHEDULER_ENABLED=0` to run the API without it.

8. **Start the console** (in a second terminal, from the repository root):
   ```bash
   cd web
   cp .env.example .env.local     # fill in the two NEXT_PUBLIC_SUPABASE_* values
   npm install
   npm run dev
   ```
   The console is at `http://localhost:3000`. Next.js reads `web/.env.local`,
   not the root `.env`; use the Supabase **anon** key there, never the service
   key, because `NEXT_PUBLIC_` variables are compiled into the browser bundle.

Other entry points: `python -m scripts.run_scorer <batch_id>` scores a batch on
its own, `python -m scripts.run_explainer_accuracy <batch_id> [batch_id]` grades
explainer categories and prints a before/after when given two batches,
`python -m scripts.chaos_test` runs the failure scenarios, and
`python -m scripts.run_qna_demo <batch_id>` exercises the grounded Q&A endpoint.
`scripts/seed_razorpay.py` additionally needs `playwright` (`pip install
playwright && playwright install chromium`), which is not in `requirements.txt`
because nothing in the pipeline path uses it.

## Known limitations

- **The corpus composition skews what category accuracy can tell you.** In the
  headline batch, 162 of the 169 graded variances are the same scenario type
  (injected noise rows). The explainer's category accuracy is therefore
  dominated by one case whose acceptable answers are deliberately broad
  (`missing_source_record` or `unexplained` both count), so the headline
  accuracy number is close to a measurement of that single scenario rather than
  of the classifier across the taxonomy. The scenarios that would discriminate
  hardest — fee splits, timing drift, duplicates — mostly get resolved by the
  deterministic tiers and never reach the variance queue at all.
- **The leak before/after was one seed, one provider, one run per condition.**
  Both runs were pinned to a single LLM provider so the redaction was the only
  variable, and neither condition was repeated, so there is no variance estimate
  and no claim that the deltas would survive re-running. See EVALUATION.md.
- **The evaluation harness depends on synthetic ground truth.** Precision,
  recall and F1 all derive from `truth_group`, which exists because the corpus
  generator wrote it. Real merchant data has no answer key, so on real data
  these numbers cannot be computed at all — the matchers would still run, but
  the only available signals would be the ones that need no ground truth: how
  much value ended up unexplained, and whether the reconciliation arithmetic
  closes.
- **Razorpay ingestion is test mode only,** against a seeded test account. It
  has not been run against a production merchant account or at production
  volume; the largest batch here is ~1,200 rows.
- **The batch lock is advisory,** a compare-and-set on a timestamp in
  `run_state`, sufficient for the single scheduler process this runs as. It is
  not a distributed lock.
- **There is no authentication.** The console and the API are both open: anyone
  with the URL can read every batch and act on a variance. That is a deliberate
  scope choice for a single-operator demo, not an oversight, but it is the first
  thing that would have to change before this saw a real merchant's data. RLS
  (migration 0008) closes direct database access, so the API is the only way in
  — it does not put a door on the API itself.
- **The database had RLS disabled until late in the build.** Every table was
  readable and writable with the public anon key, which is compiled into the
  browser bundle by design — verified at the time: `select` on `txns` returned
  live records, `insert` succeeded, `delete` returned 204. Fixed in 0008 and
  re-verified (anon `select` returns `[]`, `insert` is 401, a `delete` aimed at
  a row that exists leaves it there). Recorded here rather than quietly
  corrected, because "it is secure now" and "it was never exposed" are different
  claims and only the first one is true.
- **Q&A refuses rather than answers when it cannot trace a figure.** Every
  number in a generated answer is checked against the numbers in the supplied
  context; one regeneration is attempted, then the answer is withheld. That is
  the intended behaviour, but it means some legitimate questions get a refusal.
- **The Q&A guard verifies provenance, not correctness, and cannot do
  otherwise.** It checks that every number in an answer appears in the batch's
  own figures. It does not and cannot check that the answer combines those
  numbers into a true statement, so an answer built entirely from real figures
  can still assert a false relationship between them and pass the check —
  reproduced, with the exact question and reply, in
  [EVALUATION.md](EVALUATION.md#the-grounding-guard-checks-provenance-not-correctness).
  The UI says "Every figure traced to source data" rather than anything implying
  the answer is right, for this reason.
- **Older batches in the database are in mixed states.** Some early ones predate
  `run_scores` and carry no score. Several are `chaos_test.py` artifacts — real
  batches the scenarios create to inject a fault into, e.g. a corrupt CSV row or
  a duplicate ingest — and once the scheduler is running (the default; see
  Setup step 7) it eventually resumes and scores those too, same as it would
  any other non-terminal batch, so their state keeps changing rather than
  sitting fixed. `error_text` on one of them means a scenario's injected
  failure actually happened, not that something broke. Only the batch named
  above should be read as a result.

## Resilience

Six scripted failure scenarios, in [`api/scripts/chaos_test.py`](api/scripts/chaos_test.py),
run against the live system (`python -m scripts.chaos_test`, or a scenario
number to run one). Each asserts the specific expected behaviour, that the
service is still alive afterwards, and that the batch ended in a state you could
defend to an auditor:

1. every LLM provider broken — the batch still reaches scoring, variances stay open rather than being invented
2. Supabase connection drops mid-run — transient drops retry, a sustained outage fails the batch cleanly with a traceback, and the resume skips completed stages
3. Razorpay returns 429 — backs off and retries; a 401 fails fast instead of retrying
4. corrupt rows mid-CSV — the parser skips them with line numbers and keeps the good rows
5. the same range ingested twice — no duplicate rows
6. NVIDIA and BytePlus both degraded — OpenRouter answers as the third fallback, and the audit trail shows all three attempts in order

The three failures worth more than any of those are the ones nobody wrote a test
for. All three happened during the build, and each one changed the fallback
chain in [`api/lib/byteplus.py`](api/lib/byteplus.py):

- **BytePlus started returning HTTP 403** on a dead account. This taught the
  chain that an auth failure is not the same class of error as a malformed
  request. A genuine 4xx means the request was wrong and every provider will
  reject it identically, so it is raised immediately rather than hidden by
  retrying elsewhere; 401 and 403 mean *this provider* cannot serve anyone right
  now, which is exactly what fallback is for. Collapsing the two would either
  mask real bugs or strand the run on a dead key.
- **OpenRouter returned HTTP 200 with an error object in the body** — an
  upstream rate limit wearing a success status code. The chain read the 200 as
  success, found no `choices`, and raised a parse error, which surfaced a rate
  limit as if it were a bug in our own parsing and skipped the providers that
  could have answered. A 200 is now checked for an embedded error before being
  treated as an answer, and a retryable embedded code retries in place before
  handing off.
- **NVIDIA defaulted to reasoning mode.** Not sending a thinking parameter does
  not mean thinking is off on that endpoint: nemotron-3.5-lightning was spending
  most of its completion budget on a hidden `reasoning_content` field and
  intermittently returning an empty `content`, which failed downstream JSON
  parsing with nothing in the error explaining why. Disabling it explicitly took
  a health-check call from ~10s and 300+ tokens to ~600ms and 70 tokens. The
  lesson is that "we did not enable it" is not evidence a provider default is
  what you assumed — the only proof is reading what came back.

Every call records which provider served it, its model id, latency, and whether
it was the primary or a fallback, and that trail is written into `audit_log`
alongside the explanation it produced.

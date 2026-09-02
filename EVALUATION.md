# Explainer evaluation — ground-truth leak, 2026-09-01

A leak in the explanation path let the LLM read its own answer key. This
document is the finding, the fix, the guard against it reopening, and a
measured before/after on identical data.

## The leak

`api/scripts/generate_corpus.py` stamps the injected scenario label onto
every synthetic row twice, as ordinary record fields:

```python
"description": f"synthetic:{category}",
"raw": {"synthetic": True, "category": category},
```

`api/explain/variance_explainer.py`, in `_txn_detail`, passed both
straight into the context sent to the model:

```python
"description": t["description"],
"raw":         t["raw"],
```

So the explainer read strings like `"synthetic:fee_tax_split"` inside
the record it was reasoning over, then was asked to classify that same
variance. The runtime assertion that keeps `truth_group`/`is_noise`
away from every matcher (`_assert_no_forbidden`) never caught this,
because these aren't schema ground-truth columns — they're ordinary
`description`/`raw` fields the generator happened to fill with the
answer. `api/eval/explanation_audit.py`'s critic had the identical
exposure: it rebuilds the same context via `build_context` to grade the
explainer's output, so it was reading the same leaked fields when
judging whether an explanation was grounded.

## The fix

Redaction at context-build time, not in the generator. The label has to
stay in the database — `eval/scorer.py` grades matcher output against
`truth_group`, and `eval/explainer_accuracy.py` (new, see below) grades
the explainer's category against the same corpus label recovered from
`description`. Removing it at the source would take the answer key away
from every grader, not just the explainer.

`api/explain/variance_explainer.py`:

```python
_LEAK_KEYS = frozenset({"synthetic", "category", "truth_group"})
_LEAK_MARKERS = ("synthetic:", "truth_group")

def _redact(t: dict) -> dict:
    d = dict(t)
    if (d.get("description") or "").startswith("synthetic:"):
        d["description"] = ""
    raw = d.get("raw") or {}
    d["raw"] = {k: v for k, v in raw.items() if k not in _LEAK_KEYS}
    return d
```

Called inside `_txn_detail`, so every record reaching the model —
explainer and critic alike — is redacted before it's ever put in a
prompt. `explanation_audit.py` applies the identical `_redact` (imported
from `variance_explainer`, not reimplemented) to the txns it fetches for
the critic.

## The guard

A leak that reopens quietly is worse than one never closed — every
number since the regression would be measured against a model that
could read the answer, with nothing in the output saying so. So the
check is loud and structural, not a field-by-field review:

```python
def assert_no_leak(payload, *, where: str = "context") -> None:
    serialized = json.dumps(payload, default=str)
    for marker in _LEAK_MARKERS:
        if marker in serialized:
            raise AssertionError(...)
```

`build_context` calls `assert_no_leak` on every context it assembles,
checking the **serialized** form rather than the fields we remembered to
redact — a leak that reopens through some field nobody thought about is
exactly the case a field-by-field check misses.

`api/scripts/leak_check.py` is the standing GATE: fixtures prove the
guard actually raises (a guard that can't fail isn't a guard), then it
rebuilds every context a real batch would send — explainer and critic —
scans the serialized corpus for `"synthetic:"` and `"truth_group"`, and
separately confirms the label is *still in the database* (so nobody
"fixes" this by deleting the answer key the grader needs).

Run against both batches used for this measurement:

```
$ python -m scripts.leak_check <batch_id>
19/19 checks passed
GATE PASSED — no context reaching a model carries the corpus label,
and the label is still in the database for the scorer.
```

Passed on the pre-fix batch (proving the batch-level rebuild path
itself works — `build_context` redacts even when called against a
batch whose stored rows are unredacted, since redaction happens at
context-build time, not at ingest) and on the post-fix batch. 19/19,
both times.

## Measurement

**Method.** One corpus, `CORPUS_SEED=20260826` `CORPUS_EVENTS=506`
(1198 txns rows, 311 truth groups — verified identical row/group counts
on both runs), run through the full pipeline twice: once against the
explainer code as it stood with the leak, once after the fix. Both runs
were pinned to a single LLM provider (OpenRouter, `minimax/minimax-m3:free`)
by blanking the NVIDIA and BytePlus keys in-process — at the time of
the runs, NVIDIA's endpoint had an unrelated bug (defaulted to
reasoning mode, sometimes emptying the actual answer) and the BytePlus
key was dead, and even after fixing both, holding the provider fixed
across both runs isolates the redaction as the only variable. A
before/after served by a different mix of models would confound the one
thing under test.

Graded with `api/eval/explainer_accuracy.py` (new): maps each corpus
scenario to the explainer categories that are a defensible read of it
(e.g. `fee_tax_split` → `gateway_fee`/`gst_on_fee`), applied identically
to both runs, plus a mapping-independent signal — `leak_quotation_rate_pct`,
the share of explanations whose own text (explanation or subcategory)
recites corpus-label vocabulary (`"synthetic"`, `"genuine_noise"`,
`"fee_tax_split"`, etc). That one needs no judgment call: an explanation
containing that vocabulary is proof the model was reading the answer
key, not reasoning from the record.

| batch | role | provider | leak state |
|---|---|---|---|
| `906e7471-58aa-4769-a8e1-0613d6bcd1e1` | before | openrouter / minimax-m3:free | unredacted |
| `9adfb642-e4e3-4227-aff0-c035be3ecb08` | after | openrouter / minimax-m3:free | redacted |

### Results

| metric | before | after | delta |
|---|---:|---:|---:|
| `leak_quotation_rate_pct` | 40.24 | **0.00** | **−40.24** |
| `explanation_grounding_pct` | 96.67 | 93.33 | **−3.34** |
| `category_accuracy_pct` | 98.22 | 98.82 | +0.60 |
| graded | 169 | 169 | — |

Per-scenario (both runs graded all 169 rows the explainer classified):

| scenario | n | before acc | after acc |
|---|---:|---:|---:|
| genuine_noise | 162 | 100.0% | 100.0% |
| ref_format_drift | 1 | 100.0% | 100.0% |
| refund_chargeback | 6 | 50.0% | 66.7% |

### Reading the numbers

**`leak_quotation_rate_pct`, 40.24% → 0.00%, is the finding.** Before
the fix, 68 of 169 explanations — 40% — contained corpus-label
vocabulary in their own generated text. Sample subcategories the model
wrote, pre-fix: `"synthetic orphan, single ledger record"`,
`"synthetic orphan, immaterial amount"`. That is the model transcribing
`raw["synthetic"]` / `raw["category"]` into its own reasoning, not
reasoning from transaction data. Post-fix: zero. This number needs no
mapping judgment to trust — it's a literal string search — and it went
from a plurality of the batch to none.

**`explanation_grounding_pct` dropped 3.34 points.** This is the
critic's independent grade of whether an explanation's claims are
actually supported by the record it was given (see
`explanation_audit.py`) — a genuine cost, and the number closest to
"how good are the explanations, actually." Redacting the label removed
a source of unearned confidence: an explanation that could quote
`"synthetic:genuine_noise"` and build a subcategory around it was easier
to write and easier for the critic to accept than one that has to
justify the same conclusion from bare transaction fields alone.

**`category_accuracy_pct` barely moved, and went up.** This is the
counterintuitive result, and it's explained by corpus composition, not
by the leak being harmless. 162 of 169 graded rows (95.9%) are
`genuine_noise` — a scenario whose acceptable-answer set is
deliberately broad (`missing_source_record` **or** `unexplained`, both
count as correct — a noise row has no counterpart by construction, so
either honest answer is right). The leak told the model *which*
scenario it was looking at, but for genuine_noise that information
doesn't narrow which of the two acceptable buckets to pick — the model
still had to look at the bare record to decide between them, and it did
that about as well either way (100% both runs). The one scenario small
enough to show movement, `refund_chargeback` (n=6), actually improved
after the fix (50% → 66.7%) — with only 6 rows that's not a claim of a
real effect, just evidence the fix didn't break anything there either.
Category accuracy is the metric this write-up's own docstring warns is
"worth less than the delta" — precisely because a broad mapping can
absorb a leak's effect on rows where the acceptable set doesn't
discriminate. `leak_quotation_rate_pct` and `explanation_grounding_pct`
are where this leak's cost actually shows up.

### Caveats

- Single seed, single run per condition — no variance estimate. The
  `refund_chargeback` delta (n=6) is not statistically meaningful on
  its own; it's reported because it's part of the same graded set, not
  as a separate claim.
- Both runs pinned to OpenRouter's free-tier `minimax-m3` rather than
  the production NVIDIA-primary chain, specifically so the comparison
  isolates the redaction. Absolute accuracy/grounding numbers on the
  production chain (NVIDIA primary) have not been re-measured against
  this fix and may differ; the *before/after delta* is what this
  document claims, not the absolute numbers as a production baseline.
- `category_accuracy_pct` depends on the `ACCEPTABLE` scenario→category
  mapping in `explainer_accuracy.py`, which is a judgment call, applied
  identically to both runs. `leak_quotation_rate_pct` requires no such
  judgment and is the more trustworthy signal here.

## The grounding guard checks provenance, not correctness

This is a limit of the Q&A guard described above, found by adversarial
questioning of the deployed app. It is not fixed, because it is not
fixable by the mechanism that guard uses.

**What happened.** Asked *"How many payments failed in July 2025?"*, the
endpoint returned an answer stating that 6 variances were
`refund_offset` explanations and 2 were false negatives, presented as a
breakdown of the 8 unexplained variances. The green
"EVERY FIGURE TRACED" badge displayed alongside it.

That breakdown is false. `refund_offset` is a separate category, not a
subset of `unexplained`. "2 false negatives" is a run-score figure about
matcher pair accuracy, unrelated to the variance queue.

**Why the guard passed it.** Both numbers are really in the context. From
the batch's own `build_context` output:

```
  true positives: 1749, false positives: 0, false negatives: 2
...
  refund_offset [explained]: 6 variances, total Rs 845.25 (84525 paise)
  unexplained [open]: 8 variances, total Rs 494.88 (49488 paise)
```

`ungrounded_figures()` found nothing because there was nothing to find.
Every figure cited was traceable. The model recombined two real figures
into a false claim about their relationship — and 6 + 2 = 8 is exactly
what makes the recombination look plausible.

**Reproduced.** The original phrasing is intermittent: asked five more
times, the model correctly refused each time ("The data provided does
not contain any information about payment failures in July 2025..."),
which makes the failure more dangerous rather than less — a reader can
see several honest refusals and then one confident fabrication. Asking
directly for the decomposition reproduces it on demand. Against batch
`ca2dafbe-995d-4e64-a76e-0da4263d075b`, live:

> **Q:** What makes up the 8 open unexplained variances? Give the components.
>
> **A:** "The 8 open unexplained variances consist of 6 individual
> refund-offset variances and 2 variances classified under the
> missing_source_record unexplained category. Specifically: 6 variances
> with a total of Rs 845.25 (84525 paise) in the refund_offset category,
> and 8 unexplained variances with a total of Rs 494.88 (49488 paise) in
> the unexplained category."
>
> `verified: true`

And a second, differently-wrong instance from the same class:

> **Q:** Break down the 8 unexplained variances by category.
>
> **A:** "The 8 unexplained variances fall into three category groups: 3
> under timing_difference with a total of Rs 130.05 (13005 paise), 2
> under missing_source_record [explained] with a total of Rs 14,966.21
> (1496621 paise), and 3 under the unexplained [open] category with a
> total of Rs 494.88 (49488 paise)."
>
> `verified: true`

Both invent a decomposition that does not exist. Both pass, correctly by
the guard's own definition.

**Why this cannot be fixed by strengthening the guard.** The guard
verifies where a number came from. Verifying that a sentence draws a
*true* relationship between numbers it is entitled to cite is semantic
entailment over the domain, which is a research problem, not a
same-day one — and a half-implementation would move the false
confidence somewhere less visible rather than removing it.
`routes/qna.py` already says this about a different figure, in
`_member_counts_by_group`: an answer built on a stale-but-real number
"would be traceable to the context and still wrong — exactly the failure
the grounding guard cannot catch, because the guard verifies provenance,
not truth."

**What changed instead.** The claim was corrected to match the
mechanism. The badge reads "Every figure traced to source data", with a
line beneath it stating that traceable is not the same as correct and
that the relationships between figures are not checked; the Ask page and
README say the same. The answers above are still wrong. They are now
labelled as something a person has to check rather than something the
system has certified.

## Reproduce

```bash
cd api
python -m scripts.leak_check <batch_id>                         # GATE: guard holds
python -m scripts.run_explainer_accuracy <before_id> <after_id>  # before/after report
```

The provenance-vs-correctness limit above, against a running API:

```bash
curl -s -X POST "$API/qna/<batch_id>" -H 'Content-Type: application/json' \
  -d '{"question":"What makes up the 8 open unexplained variances? Give the components."}'
```

"""Grade the explainer's CATEGORY against the corpus's injected label.

=====================================================================
 THIS MODULE READS THE CORPUS LABEL ON PURPOSE.
=====================================================================
Same asymmetry as eval/scorer.py: the explainer must never see the
injected category (explain/variance_explainer.py redacts it out of every
context), and this module exists to read it and grade against it. It
never writes to txns or variances.

Two taxonomies, not one
-----------------------
The corpus labels a SCENARIO it generated ("fee_tax_split",
"value_date_drift"). The explainer returns a RECONCILIATION category
("gateway_fee", "timing_difference"). They are different vocabularies,
so grading needs a stated mapping from one to the other, and a mapping
is a judgement call — several explainer categories can be defensible for
the same scenario.

That is handled two ways:

  1. The mapping below is FIXED and applied identically to every run, so
     a before/after comparison measures the change and not the mapping.
     The absolute number is worth less than the delta; the report prints
     both and says so.

  2. A mapping-independent signal is reported alongside it:
     leak_quotation_rate, the share of explanations whose text literally
     contains "synthetic:". No judgement is involved in that one — an
     explanation quoting the corpus label is proof the model was reading
     the answer key rather than the record.

Only rows the EXPLAINER actually classified are graded. A variance the
model never reached still carries the provisional category the
deterministic queue gave it ("orphan_source_missing"), and grading those
would score the queue rather than the model. model_raw is non-null
exactly on rows the explainer wrote, so that is the filter.

Usage:
  python -m scripts.run_explainer_accuracy <batch_id>
"""

import logging
import re
from collections import Counter, defaultdict

from lib import db

logger = logging.getLogger("eval.explainer_accuracy")

_PAGE_SIZE = 1000

# Columns carrying the answer key. Named here the way scorer.py names
# GROUND_TRUTH_COLUMNS, so the deliberate asymmetry is visible in code.
LABEL_FIELDS = ("description", "raw")

_LABEL_RE = re.compile(r"^synthetic:(?P<category>\w*)$")

# Vocabulary that can only have come from the corpus label.
#
# Detecting the literal "synthetic:" is not enough: a model reading
# raw {"synthetic": true, "category": "genuine_noise"} paraphrases it
# into prose — observed output includes "flagged as synthetic
# genuine_noise" and subcategories like "synthetic noise orphan razorpay
# entry". Neither contains the colon, and both are the model reciting the
# answer key.
#
# "many_to_one" is deliberately NOT in this list even though the corpus
# uses it: tier4_aggregate writes the category "many_to_one_unresolved"
# onto the variance row itself, and that reaches the model legitimately
# as provisional_category. Counting it would charge the leak for a field
# the explainer is entitled to see.
_LEAK_VOCAB_RE = re.compile(
    r"synthetic"
    r"|genuine_noise"
    r"|fee_tax_split"
    r"|value_date_drift"
    r"|ref_format_drift"
    r"|refund_chargeback"
    r"|missing_one_source"
    r"|duplicate_one_source"
    r"|clean_3way",
    re.IGNORECASE,
)


def quotes_label(variance: dict) -> bool:
    """Did this row's model-written text recite the corpus label?

    Checks subcategory as well as explanation — subcategory is free text
    the model writes, and it is where the leak showed up most often.
    """
    for field in ("explanation", "subcategory"):
        if _LEAK_VOCAB_RE.search(variance.get(field) or ""):
            return True
    return False

# corpus scenario -> explainer categories that are a defensible read of it.
#
# Where a scenario admits more than one honest answer, all of them count.
# The rule used throughout: "unexplained" counts as CORRECT only where
# the record genuinely does not support a confident classification (a
# noise row has no counterpart to reason about), and counts as wrong
# where the arithmetic is right there in the record (a fee split).
ACCEPTABLE = {
    # The variance IS the fee and the GST charged on it.
    "fee_tax_split": {"gateway_fee", "gst_on_fee"},
    # Bank leg lands days after the gateway leg.
    "value_date_drift": {"timing_difference"},
    # One settlement credit covering many payments.
    "many_to_one": {"partial_settlement", "timing_difference"},
    "refund_chargeback": {"refund_offset", "chargeback"},
    "missing_one_source": {"missing_source_record"},
    "duplicate_one_source": {"duplicate_entry"},
    # Refs differ only in FORMAT. If this reached the variance queue the
    # matcher already failed to link them, and from the record alone the
    # missing counterpart is the honest read.
    "ref_format_drift": {"missing_source_record", "unexplained"},
    # A noise row has no counterpart by construction.
    "genuine_noise": {"missing_source_record", "unexplained"},
    # Should never produce a variance; if it did, the matcher slipped.
    "clean_3way": {"unexplained", "missing_source_record"},
}


def _page(table: str, columns: str, batch_id: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client().table(table).select(columns)
            .eq("batch_id", batch_id).order("id").range(o, o + _PAGE_SIZE - 1).execute()
        ).data
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return rows


def _fetch_by_ids(table: str, columns: str, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    rows: list[dict] = []
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        offset = 0
        while True:
            page = db.run_with_retry(
                lambda c=chunk, o=offset: db.get_client().table(table).select(columns)
                .in_("id", c).order("id").range(o, o + _PAGE_SIZE - 1).execute()
            ).data
            rows.extend(page)
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
    return rows


def _group_members(group_ids: list[str]) -> dict[str, list[str]]:
    members: dict[str, list[str]] = defaultdict(list)
    for i in range(0, len(group_ids), 100):
        chunk = group_ids[i:i + 100]
        offset = 0
        while True:
            page = db.run_with_retry(
                lambda c=chunk, o=offset: db.get_client().table("match_members")
                .select("match_group_id,txn_id").in_("match_group_id", c)
                .order("id").range(o, o + _PAGE_SIZE - 1).execute()
            ).data
            for r in page:
                members[r["match_group_id"]].append(r["txn_id"])
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
    return members


def label_of(txn: dict) -> str | None:
    """The injected scenario for one row, from either field it was
    stamped into. raw is checked too, so a row whose description was
    overwritten still grades."""
    match = _LABEL_RE.match(txn.get("description") or "")
    if match and match.group("category"):
        return match.group("category")
    raw_category = (txn.get("raw") or {}).get("category")
    return raw_category or None


def score_batch(batch_id: str) -> dict:
    variances = _page(
        "variances",
        "id,match_group_id,txn_id,variance_paise,category,subcategory,confidence,"
        "explanation,status,model_raw",
        batch_id,
    )

    txn_ids = {v["txn_id"] for v in variances if v.get("txn_id")}
    group_ids = [v["match_group_id"] for v in variances if v.get("match_group_id")]
    members_by_group = _group_members(list(set(group_ids)))
    for ids in members_by_group.values():
        txn_ids.update(ids)

    txns_by_id = {
        t["id"]: t for t in _fetch_by_ids("txns", "id,description,raw", list(txn_ids))
    }

    # Only rows the explainer itself wrote. `is not None` rather than
    # truthiness on purpose: a row the model answered with an empty or
    # malformed object still gets model_raw {} written to it, and that is
    # explainer output — a failure of it — not a row the explainer never
    # reached. Dropping those would quietly flatter the accuracy.
    classified = [v for v in variances if v.get("model_raw") is not None]

    graded = 0
    correct = 0
    ambiguous = 0
    unlabelled = 0
    confusion: dict[str, Counter] = defaultdict(Counter)
    per_scenario: dict[str, dict] = defaultdict(lambda: {"graded": 0, "correct": 0})
    misses: list[dict] = []

    for v in classified:
        involved = []
        if v.get("txn_id") and v["txn_id"] in txns_by_id:
            involved.append(txns_by_id[v["txn_id"]])
        for tid in members_by_group.get(v.get("match_group_id") or "", []):
            if tid in txns_by_id:
                involved.append(txns_by_id[tid])

        labels = {label_of(t) for t in involved}
        labels.discard(None)

        if not labels:
            unlabelled += 1
            continue
        if len(labels) > 1:
            # Records from two different generated scenarios ended up in
            # one variance — there is no single right answer to grade
            # against, so it is reported rather than scored either way.
            ambiguous += 1
            continue

        scenario = labels.pop()
        predicted = v.get("category") or "(none)"
        acceptable = ACCEPTABLE.get(scenario, set())

        graded += 1
        per_scenario[scenario]["graded"] += 1
        confusion[scenario][predicted] += 1
        if predicted in acceptable:
            correct += 1
            per_scenario[scenario]["correct"] += 1
        elif len(misses) < 25:
            misses.append({
                "variance_id": v["id"],
                "scenario": scenario,
                "predicted": predicted,
                "acceptable": sorted(acceptable),
                "confidence": v.get("confidence"),
                "explanation": (v.get("explanation") or "")[:200],
            })

    # Mapping-independent: did the model recite the answer key back?
    with_text = [v for v in classified if (v.get("explanation") or "").strip()]
    quoting = [v for v in with_text if quotes_label(v)]

    accuracy = round(100.0 * correct / graded, 2) if graded else None
    return {
        "batch_id": batch_id,
        "variances_total": len(variances),
        "explainer_classified": len(classified),
        "graded": graded,
        "correct": correct,
        "category_accuracy_pct": accuracy,
        "ambiguous_multi_scenario": ambiguous,
        "unlabelled": unlabelled,
        "explanations_with_text": len(with_text),
        "explanations_quoting_label": len(quoting),
        "leak_quotation_rate_pct": (
            round(100.0 * len(quoting) / len(with_text), 2) if with_text else None
        ),
        "quoted_examples": [
            {
                "subcategory": v.get("subcategory"),
                "explanation": (v.get("explanation") or "")[:200],
            }
            for v in quoting[:5]
        ],
        "predicted_distribution": dict(Counter(
            v.get("category") or "(none)" for v in classified
        ).most_common()),
        "per_scenario": {
            k: {
                **val,
                "accuracy_pct": (
                    round(100.0 * val["correct"] / val["graded"], 2) if val["graded"] else None
                ),
            }
            for k, val in sorted(per_scenario.items())
        },
        "confusion": {k: dict(c.most_common()) for k, c in sorted(confusion.items())},
        "misses": misses,
    }


def grounding_pct(batch_id: str) -> float | None:
    """The critic's grade for this batch, as written by explanation_audit."""
    rows = db.run_with_retry(
        lambda: db.get_client().table("run_scores")
        .select("explanation_grounding_pct,run_at").eq("batch_id", batch_id)
        .order("run_at", desc=True).limit(5).execute()
    ).data
    for r in rows:
        if r.get("explanation_grounding_pct") is not None:
            return r["explanation_grounding_pct"]
    return None


def print_report(result: dict) -> None:
    print("\n" + "=" * 78)
    print(f"EXPLAINER CATEGORY ACCURACY — batch {result['batch_id']}")
    print("=" * 78)
    print(f"\n  variances in batch          {result['variances_total']:>10}")
    print(f"  classified by the explainer {result['explainer_classified']:>10}")
    print(f"  graded against the label    {result['graded']:>10}")
    print(f"  correct                     {result['correct']:>10}")
    acc = result["category_accuracy_pct"]
    print(f"  category_accuracy_pct       {acc if acc is not None else 'n/a':>10}")
    print(f"  ambiguous (multi-scenario)  {result['ambiguous_multi_scenario']:>10}")
    print(f"  unlabelled                  {result['unlabelled']:>10}")

    print("\n  --- mapping-independent ---")
    print(f"  explanations with text      {result['explanations_with_text']:>10}")
    print(f"  quoting 'synthetic:'        {result['explanations_quoting_label']:>10}")
    rate = result["leak_quotation_rate_pct"]
    print(f"  leak_quotation_rate_pct     {rate if rate is not None else 'n/a':>10}")
    for ex in result["quoted_examples"]:
        print(f"      subcategory: {ex['subcategory']!r}")
        print(f"      explanation: {ex['explanation']!r}")

    print("\n  --- per scenario ---")
    header = f"  {'scenario':<24}{'graded':>8}{'correct':>9}{'accuracy':>10}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for scenario, s in result["per_scenario"].items():
        a = s["accuracy_pct"]
        print(f"  {scenario:<24}{s['graded']:>8}{s['correct']:>9}"
              f"{(f'{a:.1f}%' if a is not None else 'n/a'):>10}")

    print("\n  --- what it predicted instead ---")
    for scenario, preds in result["confusion"].items():
        acceptable = sorted(ACCEPTABLE.get(scenario, set()))
        print(f"  {scenario}  (acceptable: {', '.join(acceptable) or 'n/a'})")
        for pred, n in preds.items():
            mark = "ok " if pred in ACCEPTABLE.get(scenario, set()) else "MISS"
            print(f"      {mark}  {pred:<24}{n:>5}")

    if result["misses"]:
        print("\n  --- sample misses ---")
        for m in result["misses"][:8]:
            print(f"\n    {m['scenario']} -> predicted {m['predicted']} "
                  f"(confidence {m['confidence']})")
            print(f"      {m['explanation']!r}")

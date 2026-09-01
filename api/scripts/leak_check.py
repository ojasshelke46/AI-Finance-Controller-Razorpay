"""GATE: the ground-truth leak in the explanation path stays closed.

scripts/generate_corpus.py stamps the injected category onto every
synthetic row twice — description "synthetic:<category>" and
raw["category"]. Those are ordinary record fields, not schema
ground-truth columns, so the runtime assertion that keeps truth_group
and is_noise away from the matchers never saw them. The explainer read
them straight out of the record and was then asked to classify the
variance they described.

This script is the standing check that the redaction which closed that
hole is still in force. It runs three things:

  1. fixtures      — _redact strips both fields; assert_no_leak actually
                     raises on a leaked payload (a guard that cannot
                     fail is not a guard)
  2. full batch    — every context the explainer and the critic would
                     build for a real batch, rebuilt and checked
  3. label intact  — the corpus label is STILL in the database, because
                     eval/scorer.py grades against it. The fix has to be
                     at context-build time; a fix in the generator would
                     take the answer key away from the grader too.

Usage:
  python -m scripts.leak_check <batch_id>
"""

import json
import sys

from explain.variance_explainer import (
    _LEAK_MARKERS,
    _TXN_DETAIL_COLUMNS,
    _fetch_by_ids,
    _fetch_group_members,
    _page,
    _redact,
    _txn_detail,
    assert_no_leak,
    build_context,
)
from eval.explanation_audit import _scrub_leak_text, build_audit_contexts

SEPARATOR = "=" * 78


def log(msg: str = "") -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------
# 1. fixtures
# ---------------------------------------------------------------------

def check_fixtures() -> dict[str, bool]:
    checks: dict[str, bool] = {}
    log("\n[1] fixtures")

    leaked_row = {
        "id": "txn_fixture",
        "source_kind": "bank",
        "external_ref": "ref_1",
        "amount_paise": 123456,
        "fee_paise": None,
        "tax_paise": None,
        "net_paise": None,
        "txn_date": "2026-08-01",
        "value_date": None,
        "description": "synthetic:fee_tax_split",
        "counterparty": None,
        "raw": {"synthetic": True, "category": "fee_tax_split", "currency": "INR"},
    }

    redacted = _redact(leaked_row)
    checks["redact_clears_description"] = redacted["description"] == ""
    checks["redact_drops_raw_label_keys"] = (
        "synthetic" not in redacted["raw"] and "category" not in redacted["raw"]
    )
    # Redaction must be surgical: everything that is real record data has
    # to survive, or the model loses information it is entitled to.
    checks["redact_keeps_other_raw_fields"] = redacted["raw"].get("currency") == "INR"
    checks["redact_keeps_amounts"] = redacted["amount_paise"] == 123456
    checks["redact_does_not_mutate_input"] = (
        leaked_row["description"] == "synthetic:fee_tax_split"
        and leaked_row["raw"]["category"] == "fee_tax_split"
    )

    detail = _txn_detail(leaked_row)
    checks["txn_detail_is_redacted"] = (
        detail["description"] == "" and "category" not in (detail["raw"] or {})
    )

    # A guard that never fires is not a guard — prove it raises.
    raised = False
    try:
        assert_no_leak({"records": [{"description": "synthetic:many_to_one"}]}, where="fixture")
    except AssertionError:
        raised = True
    checks["assert_raises_on_description_leak"] = raised

    raised_tg = False
    try:
        assert_no_leak({"records": [{"truth_group": "tg_abc123"}]}, where="fixture")
    except AssertionError:
        raised_tg = True
    checks["assert_raises_on_truth_group_leak"] = raised_tg

    clean = True
    try:
        assert_no_leak({"records": [detail]}, where="fixture")
    except AssertionError:
        clean = False
    checks["assert_passes_on_redacted_record"] = clean

    checks["scrub_removes_label_from_claim_text"] = (
        "synthetic:" not in _scrub_leak_text("tagged synthetic:fee_tax_split in the record")
    )

    for name, ok in checks.items():
        log(f"    {'ok  ' if ok else 'FAIL'}  {name}")
    return checks


# ---------------------------------------------------------------------
# 2. full batch
# ---------------------------------------------------------------------

def check_full_batch(batch_id: str) -> tuple[dict[str, bool], dict]:
    """Rebuild every context this batch would send to a model."""
    checks: dict[str, bool] = {}
    log(f"\n[2] full batch {batch_id}")

    variances = _page(
        "variances",
        "id,match_group_id,txn_id,variance_paise,category,subcategory,"
        "confidence,explanation,suggested_action,status,model_raw",
        batch_id,
    )
    log(f"    variances in batch: {len(variances)}")
    if not variances:
        checks["batch_has_variances"] = False
        return checks, {"variances": 0}
    checks["batch_has_variances"] = True

    txn_ids = {v["txn_id"] for v in variances if v.get("txn_id")}
    group_ids = {v["match_group_id"] for v in variances if v.get("match_group_id")}

    groups_by_id = {
        g["id"]: g for g in _fetch_by_ids(
            "match_groups",
            "id,tier,strategy,confidence,total_variance_paise,variance_components",
            list(group_ids),
        )
    }
    members_by_group = _fetch_group_members(list(group_ids))
    for ids in members_by_group.values():
        txn_ids.update(ids)

    txns = _fetch_by_ids("txns", ",".join(_TXN_DETAIL_COLUMNS), list(txn_ids))
    txns_by_id = {t["id"]: t for t in txns}
    log(f"    txns pulled into those contexts: {len(txns)}")

    # Contexts are built from UNREDACTED rows on purpose here: build_context
    # is what the explainer calls, so this exercises the real path rather
    # than a pre-cleaned copy of it.
    leaks: list[str] = []
    contexts = []
    for v in variances:
        try:
            ctx = build_context(v, txns_by_id, groups_by_id, members_by_group)
        except AssertionError as exc:
            leaks.append(f"variance {v['id']}: {exc}")
            continue
        contexts.append(ctx)

    checks["every_explainer_context_clean"] = not leaks
    log(f"    explainer contexts built: {len(contexts)}  leaking: {len(leaks)}")

    # Belt and braces: scan the serialized corpus of contexts directly,
    # not only via the assertion that just ran inside build_context.
    serialized = json.dumps(contexts, default=str)
    for marker in _LEAK_MARKERS:
        checks[f"serialized_contexts_free_of_{marker.strip(':')}"] = marker not in serialized
    log(f"    serialized context size: {len(serialized):,} chars")

    # Same again for the critic, which sees the record AND the claim.
    explained = [v for v in variances if (v.get("explanation") or "").strip()]
    critic_leaks: list[str] = []
    critic_pairs = []
    if explained:
        try:
            critic_pairs = build_audit_contexts(batch_id, explained)
        except AssertionError as exc:
            critic_leaks.append(str(exc))
    checks["every_critic_context_clean"] = not critic_leaks
    critic_serialized = json.dumps(critic_pairs, default=str)
    for marker in _LEAK_MARKERS:
        checks[f"critic_contexts_free_of_{marker.strip(':')}"] = marker not in critic_serialized
    log(f"    critic contexts built: {len(critic_pairs)} (from {len(explained)} explained rows)")

    for leak in leaks[:5]:
        log(f"    LEAK: {leak}")

    stats = {
        "variances": len(variances),
        "txns": len(txns),
        "contexts": len(contexts),
        "critic_contexts": len(critic_pairs),
        "context_chars": len(serialized),
    }
    for name, ok in checks.items():
        log(f"    {'ok  ' if ok else 'FAIL'}  {name}")
    return checks, stats


# ---------------------------------------------------------------------
# 3. the label is still in the database
# ---------------------------------------------------------------------

def check_label_still_stored(batch_id: str) -> dict[str, bool]:
    """The redaction must NOT have reached the database.

    eval/scorer.py recovers the injected category from description to
    grade against. If this check ever fails, someone 'fixed' the leak in
    the generator and quietly took the answer key away from the grader.
    """
    checks: dict[str, bool] = {}
    log("\n[3] corpus label still present in the database (the grader needs it)")

    rows = _page("txns", "id,description,raw", batch_id)[:500]
    labelled = [r for r in rows if (r.get("description") or "").startswith("synthetic:")]
    with_raw_category = [r for r in rows if "category" in (r.get("raw") or {})]

    log(f"    sampled rows: {len(rows)}")
    log(f"    rows still carrying description 'synthetic:<category>': {len(labelled)}")
    log(f"    rows still carrying raw['category']:                    {len(with_raw_category)}")

    checks["label_survives_in_description"] = bool(labelled)
    checks["label_survives_in_raw"] = bool(with_raw_category)
    for name, ok in checks.items():
        log(f"    {'ok  ' if ok else 'FAIL'}  {name}")
    return checks


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    batch_id = sys.argv[1]

    log(SEPARATOR)
    log("LEAK CHECK — ground truth must not reach any model")
    log(SEPARATOR)

    checks = check_fixtures()
    batch_checks, stats = check_full_batch(batch_id)
    checks.update(batch_checks)
    checks.update(check_label_still_stored(batch_id))

    log("\n" + SEPARATOR)
    failed = [name for name, ok in checks.items() if not ok]
    log(f"stats: {json.dumps(stats)}")
    log(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    log("\n=== GATE ===")
    if failed:
        log("GATE FAILED — leaked or unverified:")
        for name in failed:
            log(f"    FAIL  {name}")
        return 1
    log("GATE PASSED — no context reaching a model carries the corpus label, "
        "and the label is still in the database for the scorer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

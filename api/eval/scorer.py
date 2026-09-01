"""Score produced match_groups against ground truth.

=====================================================================
 THIS IS THE ONE MODULE THAT READS truth_group AND is_noise.
=====================================================================
Every matcher (tiers 1-4) and the variance classifier enforce, at
runtime, that they never select those columns. This module is the
deliberate inverse: it exists to read them, and nothing here ever
writes back to txns or match_groups. That asymmetry is the whole basis
for trusting these numbers — the matchers cannot see what they're
graded on, and the grader cannot change what was produced.

Scoring is over PAIRS, not groups. A group-level score would give a
17-member settlement the same weight as a 2-member pair, and would
score a group that got 16 of 17 members right as a total failure.
Pair-level scoring handles partial credit correctly, which matters
enormously on the many-to-one cases.

  true positive   two txns sharing a truth_group placed in the same
                  match_group
  false positive  two txns in the same match_group with different
                  truth_groups, or either being is_noise
  false negative  two txns sharing a truth_group left in different
                  match_groups (or one/both left unmatched entirely)

Because a noise row has truth_group NULL, it can never share a
truth_group with anything — so "either being is_noise" falls out of
the same rule rather than needing a special case, and every predicted
pair that isn't a true positive is a false positive by definition.
"""

import itertools
import logging
from collections import defaultdict
from datetime import datetime

from lib import db
from lib.config import LLM_RATES_USD_PER_TOKEN

logger = logging.getLogger("eval.scorer")

_PAGE_SIZE = 1000

# Columns this module reads that matchers are forbidden from reading.
# Named here so the asymmetry is visible in code, not just in comments.
GROUND_TRUTH_COLUMNS = ("truth_group", "is_noise")


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


def _fetch_members(group_ids: list[str]) -> dict[str, list[str]]:
    members: dict[str, list[str]] = defaultdict(list)
    for i in range(0, len(group_ids), 100):
        chunk = group_ids[i:i + 100]
        offset = 0
        while True:
            page = db.run_with_retry(
                lambda c=chunk, o=offset: db.get_client().table("match_members")
                .select("match_group_id,txn_id").in_("match_group_id", c).order("id")
                .range(o, o + _PAGE_SIZE - 1).execute()
            ).data
            for r in page:
                members[r["match_group_id"]].append(r["txn_id"])
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
    return members


def _pairs(items: list) -> itertools.combinations:
    return itertools.combinations(sorted(items), 2)


def _is_true_pair(a: dict, b: dict) -> bool:
    """A pair is genuinely the same economic event iff both carry the
    same non-null truth_group and neither is noise."""
    if a["is_noise"] or b["is_noise"]:
        return False
    if a["truth_group"] is None or b["truth_group"] is None:
        return False
    return a["truth_group"] == b["truth_group"]


def _wall_clock_seconds(batch_id: str) -> float:
    """Pipeline duration taken from audit_log — earliest matcher/ingest
    start to latest finish. Measures what actually ran, rather than how
    long the scorer itself took."""
    rows = _page("audit_log", "created_at,step,action", batch_id)
    if not rows:
        return 0.0
    stamps = []
    for r in rows:
        try:
            stamps.append(datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")))
        except (ValueError, AttributeError):
            continue
    if len(stamps) < 2:
        return 0.0
    return round((max(stamps) - min(stamps)).total_seconds(), 3)


def _llm_usage(batch_id: str) -> dict:
    """Count the LLM calls this batch actually made, and price them.

    Everything here is read back out of audit_log, which lib/byteplus.py
    already writes a provider, model id, latency and token count into for
    every served call — so this reports what happened rather than a
    number the scorer was told to believe. It was previously hardcoded to
    0, which contradicted the audit trail sitting right next to it.

    llm_calls counts COMPLETIONS SERVED — calls that came back with
    content. A call that failed over NVIDIA -> BytePlus -> OpenRouter is
    one served completion, not three; the failed hops carry no tokens and
    cost nothing, and they are visible in the same row's `attempts` list.
    Calls where every provider failed produced no completion and are
    counted separately as llm_calls_failed rather than folded in.

    Cost is summed per provider from the rates in lib/config.py. Tokens
    from a provider with no configured rate are reported as
    llm_unpriced_tokens rather than being silently priced at zero — an
    incomplete estimate that says so is worth more than a confident one
    that doesn't.
    """
    rows = _page("audit_log", "step,action,detail", batch_id)

    served = 0
    failed = 0
    cost = 0.0
    unpriced_tokens = 0
    by_provider: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    )

    for row in rows:
        action = row.get("action")
        detail = row.get("detail")
        if not isinstance(detail, dict):
            continue

        if action in ("batch_failed", "critic_batch_failed"):
            failed += 1
            continue
        if action not in ("batch_explained", "critic_batch_graded"):
            continue

        served += 1
        provider = detail.get("provider") or "unknown"
        prompt_tokens = detail.get("prompt_tokens") or 0
        completion_tokens = detail.get("completion_tokens") or 0

        entry = by_provider[provider]
        entry["calls"] += 1
        entry["prompt_tokens"] += prompt_tokens
        entry["completion_tokens"] += completion_tokens

        rate = LLM_RATES_USD_PER_TOKEN.get(provider)
        if rate is None:
            unpriced_tokens += prompt_tokens + completion_tokens
            continue
        call_cost = prompt_tokens * rate["prompt"] + completion_tokens * rate["completion"]
        entry["cost_usd"] = round(entry["cost_usd"] + call_cost, 8)
        cost += call_cost

    return {
        "llm_calls": served,
        "llm_calls_failed": failed,
        "llm_cost_estimate": round(cost, 6),
        "llm_unpriced_tokens": unpriced_tokens,
        "by_provider": {k: dict(v) for k, v in sorted(by_provider.items())},
    }


def score_batch(batch_id: str) -> dict:
    txns = _page("txns", "id,source_kind,external_ref,amount_paise,txn_date,description,truth_group,is_noise", batch_id)
    txn_by_id = {t["id"]: t for t in txns}

    groups = _page("match_groups", "id,tier,strategy,confidence,total_variance_paise,variance_components", batch_id)
    group_by_id = {g["id"]: g for g in groups}
    members_by_group = _fetch_members([g["id"] for g in groups])

    matched_ids = {tid for ids in members_by_group.values() for tid in ids}

    # ---- predicted pairs ----
    tp = 0
    fp = 0
    fp_details: list[dict] = []
    per_tier: dict[int, dict] = defaultdict(lambda: {"pairs": 0, "tp": 0, "fp": 0, "groups": 0, "txns": 0})

    co_grouped: set[tuple[str, str]] = set()

    for gid, member_ids in members_by_group.items():
        tier = group_by_id[gid]["tier"]
        per_tier[tier]["groups"] += 1
        per_tier[tier]["txns"] += len(member_ids)

        present = [tid for tid in member_ids if tid in txn_by_id]
        for a_id, b_id in _pairs(present):
            a, b = txn_by_id[a_id], txn_by_id[b_id]
            per_tier[tier]["pairs"] += 1
            if _is_true_pair(a, b):
                tp += 1
                per_tier[tier]["tp"] += 1
                co_grouped.add((a_id, b_id))
            else:
                fp += 1
                per_tier[tier]["fp"] += 1
                fp_details.append({
                    "group_id": gid,
                    "tier": tier,
                    "strategy": group_by_id[gid]["strategy"],
                    "confidence": group_by_id[gid]["confidence"],
                    "a": a,
                    "b": b,
                    "worst_amount": max(abs(a["amount_paise"] or 0), abs(b["amount_paise"] or 0)),
                })

    # ---- true pairs, to derive false negatives ----
    by_truth: dict[str, list[str]] = defaultdict(list)
    for t in txns:
        if t["is_noise"] or t["truth_group"] is None:
            continue
        by_truth[t["truth_group"]].append(t["id"])

    total_true_pairs = 0
    for truth_group, ids in by_truth.items():
        n = len(ids)
        total_true_pairs += n * (n - 1) // 2

    # Every true pair that wasn't placed together is a false negative.
    fn = total_true_pairs - tp

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    # ---- variance explained ----
    # Of the gross/net gaps the matchers surfaced, what share did fee/tax
    # reconstruction actually account for? explained = |total_variance| - |residual|.
    total_variance_abs = 0
    explained_abs = 0
    for g in groups:
        total_v = abs(g.get("total_variance_paise") or 0)
        vc = g.get("variance_components") or {}
        residual = abs(vc.get("residual_paise") or 0) if vc.get("residual_paise") is not None else total_v
        total_variance_abs += total_v
        explained_abs += max(total_v - residual, 0)
    variance_explained_pct = round(100.0 * explained_abs / total_variance_abs, 4) if total_variance_abs else 0.0

    variance_rows = _page("variances", "variance_paise,status", batch_id)
    unexplained_paise = sum(r["variance_paise"] for r in variance_rows if r["status"] == "open")

    total_txns = len(txns)
    matched_txns = len(matched_ids)

    usage = _llm_usage(batch_id)
    wall_clock_seconds = _wall_clock_seconds(batch_id)
    # Throughput. Guarded rather than assumed non-zero: a batch scored
    # twice in the same second has a zero span, and dividing by it would
    # crash the scorer over a cosmetic number.
    records_per_second = (
        round(total_txns / wall_clock_seconds, 4) if wall_clock_seconds else None
    )

    result = {
        "batch_id": batch_id,
        "total_txns": total_txns,
        "matched_txns": matched_txns,
        "match_rate": round(matched_txns / total_txns, 6) if total_txns else 0.0,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "variance_explained_pct": variance_explained_pct,
        "unexplained_paise": unexplained_paise,
        "wall_clock_seconds": wall_clock_seconds,
        "records_per_second": records_per_second,
        "llm_calls": usage["llm_calls"],
        "llm_cost_estimate": usage["llm_cost_estimate"],
        "_llm_calls_failed": usage["llm_calls_failed"],
        "_llm_unpriced_tokens": usage["llm_unpriced_tokens"],
        "_llm_by_provider": usage["by_provider"],
        "_total_true_pairs": total_true_pairs,
        "_per_tier": dict(per_tier),
        "_fp_details": fp_details,
    }
    return result


def write_run_score(result: dict) -> str:
    payload = {k: v for k, v in result.items() if not k.startswith("_")}
    inserted = db.run_with_retry(
        lambda: db.get_client().table("run_scores").insert(payload).execute()
    ).data[0]
    return inserted["id"]


def _category_of(txn: dict) -> str:
    desc = txn.get("description") or ""
    return desc.split(":", 1)[1] if ":" in desc else "?"


def print_report(result: dict, worst_n: int = 10) -> None:
    print("\n" + "=" * 78)
    print(f"BASELINE SCORE — batch {result['batch_id']}")
    print("=" * 78)

    print(f"\n  total_txns              {result['total_txns']:>12}")
    print(f"  matched_txns            {result['matched_txns']:>12}")
    print(f"  match_rate              {result['match_rate']:>12.4f}")
    print()
    print(f"  true_positives          {result['true_positives']:>12}")
    print(f"  false_positives         {result['false_positives']:>12}")
    print(f"  false_negatives         {result['false_negatives']:>12}")
    print(f"  (total true pairs       {result['_total_true_pairs']:>12})")
    print()
    print(f"  precision               {result['precision']:>12.4f}")
    print(f"  recall                  {result['recall']:>12.4f}")
    print(f"  f1                      {result['f1']:>12.4f}")
    print()
    print(f"  variance_explained_pct  {result['variance_explained_pct']:>12.4f}")
    print(f"  unexplained_paise       {result['unexplained_paise']:>12}")
    print(f"  wall_clock_seconds      {result['wall_clock_seconds']:>12}")
    rps = result.get("records_per_second")
    print(f"  records_per_second      {(f'{rps:.4f}' if rps is not None else 'n/a'):>12}")
    print(f"  llm_calls               {result['llm_calls']:>12}")
    failed = result.get("_llm_calls_failed") or 0
    if failed:
        print(f"  llm_calls_failed        {failed:>12}  (every provider failed; no completion)")
    print(f"  llm_cost_estimate USD   {result['llm_cost_estimate']:>12.6f}")
    unpriced = result.get("_llm_unpriced_tokens") or 0
    if unpriced:
        print(f"  UNPRICED tokens         {unpriced:>12}  (provider missing from LLM_RATES_USD_PER_TOKEN — "
              f"cost above is a lower bound)")
    for provider, stats in (result.get("_llm_by_provider") or {}).items():
        print(f"      {provider:<12} calls={stats['calls']:<5} "
              f"prompt={stats['prompt_tokens']:<8} completion={stats['completion_tokens']:<8} "
              f"${stats['cost_usd']:.6f}")

    # ---- per-tier breakdown ----
    print("\n" + "-" * 78)
    print("PER-TIER BREAKDOWN — which tier is hurting you")
    print("-" * 78)
    header = f"{'tier':>5}{'groups':>9}{'txns':>8}{'pairs':>9}{'TP':>8}{'FP':>7}{'precision':>12}{'FP share':>11}"
    print(header)
    print("-" * len(header))
    total_fp = result["false_positives"] or 1
    for tier in sorted(result["_per_tier"]):
        s = result["_per_tier"][tier]
        prec = s["tp"] / s["pairs"] if s["pairs"] else 0.0
        fp_share = 100.0 * s["fp"] / total_fp
        print(f"{tier:>5}{s['groups']:>9}{s['txns']:>8}{s['pairs']:>9}{s['tp']:>8}{s['fp']:>7}"
              f"{prec:>12.4f}{fp_share:>10.1f}%")

    # ---- worst false positives ----
    fps = sorted(result["_fp_details"], key=lambda d: -d["worst_amount"])[:worst_n]
    print("\n" + "-" * 78)
    print(f"{min(worst_n, len(fps))} WORST FALSE POSITIVES (by amount at stake)")
    print("-" * 78)
    if not fps:
        print("  none")
    for i, d in enumerate(fps, 1):
        a, b = d["a"], d["b"]
        print(f"\n{i:>3}. tier {d['tier']} / {d['strategy']} / confidence={d['confidence']}")
        print(f"     group {d['group_id']}")
        for label, t in (("A", a), ("B", b)):
            print(f"     {label}: {t['source_kind']:<9} ref={str(t['external_ref']):<14} "
                  f"amount={t['amount_paise']:>10}  {t['txn_date']}")
            print(f"        category={_category_of(t):<22} truth_group={t['truth_group']} "
                  f"is_noise={t['is_noise']}")
        if a["is_noise"] or b["is_noise"]:
            why = "noise row pulled into a real group"
        elif a["truth_group"] != b["truth_group"]:
            why = "two genuinely different economic events merged"
        else:
            why = "unclassified"
        print(f"     WHY WRONG: {why}")

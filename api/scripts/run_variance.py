"""Populate the variance queue and verify the reconciliation arithmetic
closes to the paise, independent of what the variances table itself
says (recomputed straight from txns / match_groups / match_members).

Usage:
  python -m scripts.run_variance <batch_id>
"""

import json
import sys

from lib import db
from matching.variance import group_residual, populate_variance_queue


def _page(table: str, columns: str, batch_id: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client().table(table).select(columns)
            .eq("batch_id", batch_id).order("id").range(o, o + 999).execute()
        ).data
        rows.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    return rows


def verify(batch_id: str, summary: dict) -> bool:
    print("\n=== GATE: reconciliation arithmetic ===")

    all_txns = _page("txns", "id,amount_paise", batch_id)
    txn_amount = {t["id"]: t["amount_paise"] for t in all_txns}
    sum_all = sum(txn_amount.values())

    groups = _page("match_groups", "id,total_variance_paise,variance_components", batch_id)
    group_ids = [g["id"] for g in groups]

    members_by_group: dict[str, list[str]] = {}
    for i in range(0, len(group_ids), 100):
        chunk = group_ids[i:i + 100]
        offset = 0
        acc: list[dict] = []
        while True:
            page = db.run_with_retry(
                lambda c=chunk, o=offset: db.get_client().table("match_members")
                .select("match_group_id,txn_id").in_("match_group_id", c).order("id")
                .range(o, o + 999).execute()
            ).data
            acc.extend(page)
            if len(page) < 1000:
                break
            offset += 1000
        for r in acc:
            members_by_group.setdefault(r["match_group_id"], []).append(r["txn_id"])

    matched_ids = {tid for ids in members_by_group.values() for tid in ids}

    sum_unmatched = sum(amt for tid, amt in txn_amount.items() if tid not in matched_ids)

    sum_balanced_members = 0
    sum_unbalanced_members = 0
    sum_unbalanced_residuals = 0
    for g in groups:
        residual = group_residual(g)
        member_ids = members_by_group.get(g["id"], [])
        member_sum = sum(txn_amount.get(tid, 0) for tid in member_ids)
        if residual == 0:
            sum_balanced_members += member_sum
        else:
            sum_unbalanced_members += member_sum
            sum_unbalanced_residuals += residual

    # Recomputed from the variances table itself (what populate_variance_queue wrote,
    # plus whatever tier 4 already logged for unresolved settlement targets).
    variance_rows = _page("variances", "match_group_id,txn_id,variance_paise", batch_id)
    total_unmatched_value = sum(r["variance_paise"] for r in variance_rows if r["match_group_id"] is None)
    total_residual_value = sum(r["variance_paise"] for r in variance_rows if r["match_group_id"] is not None)
    total_unexplained_value = total_unmatched_value + total_residual_value

    # The identity: every txn is unmatched, XOR a member of a balanced
    # group, XOR a member of an unbalanced group (exhaustive partition) —
    # so sum_all - balanced_members - unbalanced_members == sum_unmatched
    # always, algebraically. Rearranged, that's exactly:
    #   total_unexplained == sum_all - sum_balanced_members
    #                         - (sum_unbalanced_members - sum_unbalanced_residuals)
    # i.e. "sum of all txns minus the sum of all balanced groups", where an
    # unbalanced group's own residual counts as its "balanced portion" —
    # the part fee/tax already explained.
    expected_unexplained = sum_all - sum_balanced_members - (sum_unbalanced_members - sum_unbalanced_residuals)

    print(f"sum of all txns                          = {sum_all:>14}")
    print(f"sum of balanced-group members             = {sum_balanced_members:>14}")
    print(f"sum of unbalanced-group members            = {sum_unbalanced_members:>14}")
    print(f"sum of unbalanced-group residuals           = {sum_unbalanced_residuals:>14}")
    print(f"sum of unmatched txns (independent)        = {sum_unmatched:>14}")
    print()
    print(f"total_unmatched_value (from variances)     = {total_unmatched_value:>14}")
    print(f"total_residual_value (from variances)      = {total_residual_value:>14}")
    print(f"total_unexplained_value                    = {total_unexplained_value:>14}")
    print(f"expected (sum_all - balanced - (unbalanced - residuals)) = {expected_unexplained:>14}")

    ok_partition = sum_unmatched == total_unmatched_value
    ok_residuals = sum_unbalanced_residuals == total_residual_value
    ok_identity = expected_unexplained == total_unexplained_value

    print(f"\nsum_unmatched == total_unmatched_value: {ok_partition}")
    print(f"sum_unbalanced_residuals == total_residual_value: {ok_residuals}")
    print(f"expected_unexplained == total_unexplained_value: {ok_identity}")

    ok = ok_partition and ok_residuals and ok_identity
    print(f"\nGATE {'PASSED' if ok else 'FAILED'}")
    return ok


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    batch_id = sys.argv[1]

    print(f"batch_id: {batch_id}")
    summary = populate_variance_queue(batch_id)
    print(json.dumps(summary, indent=2))

    verify(batch_id, summary)


if __name__ == "__main__":
    main()

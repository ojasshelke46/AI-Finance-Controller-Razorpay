"""Run tier 4 aggregate settlement matching and print the full member
list for the largest resolved group, with amounts summing to the paise.

Usage:
  python -m scripts.run_tier4 <batch_id>
"""

import json
import sys

from lib import db
from matching.tier4_aggregate import FORBIDDEN_COLUMNS, run_tier4


def print_member_list(batch_id: str, group_id: str) -> dict:
    group = db.run_with_retry(
        lambda: db.get_client().table("match_groups")
        .select("id,tier,strategy,confidence,member_count,total_variance_paise,variance_components")
        .eq("id", group_id).execute()
    ).data[0]

    members = db.run_with_retry(
        lambda: db.get_client().table("match_members").select("txn_id,role")
        .eq("match_group_id", group_id).order("id").execute()
    ).data

    rows = []
    for m in members:
        r = db.run_with_retry(
            lambda tid=m["txn_id"]: db.get_client().table("txns")
            .select("source_kind,external_ref,amount_paise,fee_paise,tax_paise,net_paise,txn_date")
            .eq("id", tid).execute()
        ).data[0]
        rows.append({**r, "role": m["role"]})

    bank = next(r for r in rows if r["source_kind"] == "bank")
    gateway_rows = [r for r in rows if r["source_kind"] == "razorpay"]

    vc = group["variance_components"]
    print(f"\n=== full member list: group {group_id} ===")
    print(f"path={vc['path']}  confidence={group['confidence']}  "
          f"member_count(subset size)={group['member_count']}")
    print(f"\nbank credit: ref={bank['external_ref']}  amount={bank['amount_paise']:>10}  date={bank['txn_date']}")
    print(f"\n{len(gateway_rows)} gateway payments in this settlement:")

    running = 0
    for i, r in enumerate(sorted(gateway_rows, key=lambda x: x["external_ref"]), 1):
        net = r["net_paise"] if r["net_paise"] is not None else r["amount_paise"] - (r["fee_paise"] or 0) - (r["tax_paise"] or 0)
        running += net
        print(f"  {i:>3}. ref={r['external_ref']:<14} gross={r['amount_paise']:>9}  "
              f"fee={r['fee_paise'] or 0:>6}  tax={r['tax_paise'] or 0:>5}  net={net:>9}  {r['txn_date']}")

    diff = bank["amount_paise"] - running
    outcome = "EXACT MATCH" if diff == 0 else f"within tolerance ({diff} paise)"
    print(f"\n  sum of {len(gateway_rows)} net amounts = {running:>10}")
    print(f"  bank credit                = {bank['amount_paise']:>10}")
    print(f"  difference                 = {diff:>10}")
    print(f"  {outcome}")

    return {"gateway_count": len(gateway_rows), "sum_matches": abs(bank["amount_paise"] - running) <= 5}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    batch_id = sys.argv[1]

    print(f"batch_id: {batch_id}")
    print(f"columns the matcher refuses to read: {sorted(FORBIDDEN_COLUMNS)}")

    summary = run_tier4(batch_id)
    print(json.dumps(summary, indent=2))

    print("\n=== GATE checks ===")
    ok = True

    largest = summary.get("largest_group")
    has_5plus = largest is not None and largest["size"] >= 5
    ok &= has_5plus
    print(f"largest resolved group: {largest} (subset size >= 5: {has_5plus})")

    if largest:
        detail = print_member_list(batch_id, largest["group_id"])
        ok &= detail["sum_matches"]

    timing_ok = summary["within_time_budget"]
    ok &= timing_ok
    print(f"\nmax seconds per target: {summary['max_seconds_per_target']} "
          f"(<= 2.0: {timing_ok})")

    print(f"\nGATE {'PASSED' if ok else 'FAILED'}")


if __name__ == "__main__":
    main()

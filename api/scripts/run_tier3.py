"""Run tier 3 fee-aware matching and print a full arithmetic trail.

Usage:
  python -m scripts.run_tier3 <batch_id>
"""

import json
import sys

from lib import db
from matching.tier3_fee_aware import FORBIDDEN_COLUMNS, run_tier3


def _page(table: str, columns: str, batch_id: str, **filters) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        q = db.get_client().table(table).select(columns).eq("batch_id", batch_id)
        for k, v in filters.items():
            q = q.eq(k, v)
        page = db.run_with_retry(lambda qq=q, o=offset: qq.order("id").range(o, o + 999).execute()).data
        out.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    return out


def arithmetic_trail(batch_id: str, limit: int = 3) -> None:
    """For tier-3 groups, print gross - fee - tax = net = the counterpart
    amount, to the paise, straight from the stored rows."""
    groups = _page("match_groups", "id,tier,strategy,confidence,member_count,"
                                   "total_variance_paise,variance_components",
                   batch_id, tier=3)
    groups = [g for g in groups if g.get("variance_components")
              and not g["variance_components"].get("refund_pair")]

    print(f"\n=== arithmetic trail ({min(limit, len(groups))} of {len(groups)} tier-3 groups) ===")

    for g in groups[:limit]:
        members = db.run_with_retry(
            lambda gid=g["id"]: db.get_client().table("match_members")
            .select("txn_id,role").eq("match_group_id", gid).order("id").execute()
        ).data
        rows = []
        for m in members:
            r = db.run_with_retry(
                lambda tid=m["txn_id"]: db.get_client().table("txns")
                .select("source_kind,external_ref,amount_paise,fee_paise,tax_paise,net_paise,txn_date")
                .eq("id", tid).execute()
            ).data[0]
            rows.append({**r, "role": m["role"]})

        vc = g["variance_components"]
        gw = next((r for r in rows if r["source_kind"] == "razorpay"), None)
        others = [r for r in rows if r is not gw]

        print(f"\n  group {g['id'][:8]}  confidence={g['confidence']}  members={g['member_count']}")
        for r in rows:
            print(f"    {r['source_kind']:<9} ref={str(r['external_ref']):<14} "
                  f"amount={r['amount_paise']:>10}  fee={str(r['fee_paise']):>6} "
                  f"tax={str(r['tax_paise']):>5}  {r['txn_date']}  [{r['role']}]")

        if gw:
            gross = gw["amount_paise"]
            fee = gw["fee_paise"] or 0
            tax = gw["tax_paise"] or 0
            net = gross - fee - tax
            print(f"\n    ARITHMETIC (all integer paise):")
            print(f"      gateway gross            = {gross:>10}")
            print(f"      gateway fee              = {fee:>10}  -")
            print(f"      gateway tax (GST on fee) = {tax:>10}  -")
            print(f"      {'':<25}   {'-'*10}")
            print(f"      computed net             = {net:>10}")
            for o in others:
                mark = "MATCHES" if o["amount_paise"] == net else \
                       f"differs by {o['amount_paise'] - net}"
                print(f"      {o['source_kind']:<12} amount    = {o['amount_paise']:>10}  <- {mark}")
            print(f"      stored total_variance    = {g['total_variance_paise']:>10}"
                  f"   (interpretation: {vc.get('interpretation')})")
            print(f"      components: fee={vc['fee_paise']} + tax={vc['tax_paise']} "
                  f"+ residual={vc['residual_paise']} = "
                  f"{vc['fee_paise'] + vc['tax_paise'] + vc['residual_paise']}")
            consistent = (vc["fee_paise"] + vc["tax_paise"] + vc["residual_paise"]
                          == g["total_variance_paise"])
            print(f"      component split reconciles to total: {consistent}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    batch_id = sys.argv[1]

    print(f"batch_id: {batch_id}")
    print(f"columns the matcher refuses to read: {sorted(FORBIDDEN_COLUMNS)}")

    summary = run_tier3(batch_id)
    print(json.dumps(summary, indent=2))

    arithmetic_trail(batch_id)

    print("\n=== GATE checks ===")
    activity = summary["new_groups"] + summary["groups_enriched"] + summary["refund_pairs_linked"]
    ok = activity > 0
    print(f"tier-3 activity (new + enriched + refunds): {activity} (> 0: {ok})")
    print(f"unmatched {summary['unmatched_before']} -> {summary['unmatched_after']}")
    print(f"\nGATE {'PASSED' if ok else 'FAILED'}")


if __name__ == "__main__":
    main()

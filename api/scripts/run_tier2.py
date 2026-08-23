"""Run tier 2 normalised matching over a batch.

Usage:
  python -m scripts.run_tier2 <batch_id>
"""

import json
import sys

from lib import db
from matching.tier1_exact import FORBIDDEN_COLUMNS
from matching.tier2_normalised import run_tier2


def _count_unmatched(batch_id: str) -> int:
    total = db.run_with_retry(
        lambda: db.get_client().table("txns").select("id", count="exact").eq("batch_id", batch_id).execute()
    ).count

    group_ids: list[str] = []
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client().table("match_groups").select("id").eq("batch_id", batch_id)
            .order("id").range(o, o + 999).execute()
        ).data
        group_ids.extend(g["id"] for g in page)
        if len(page) < 1000:
            break
        offset += 1000
    if not group_ids:
        return total

    matched: set[str] = set()
    for i in range(0, len(group_ids), 100):
        chunk = group_ids[i:i + 100]
        offset = 0
        while True:
            page = db.run_with_retry(
                lambda c=chunk, o=offset: db.get_client().table("match_members").select("txn_id")
                .in_("match_group_id", c).order("id").range(o, o + 999).execute()
            ).data
            matched.update(r["txn_id"] for r in page)
            if len(page) < 1000:
                break
            offset += 1000
    return total - len(matched)


def verify(summary: dict) -> bool:
    print("\n=== GATE checks ===")
    activity = summary["groups_created"] + summary.get("groups_enriched", 0)
    ok = activity > 0
    print(f"groups created: {summary['groups_created']}, groups enriched: "
          f"{summary.get('groups_enriched', 0)} (total activity > 0: {ok})")

    members_ok = summary["match_members_written"] == summary["txns_matched"]
    ok &= members_ok
    print(f"match_members written {summary['match_members_written']} == txns matched "
          f"{summary['txns_matched']}: {members_ok}")

    print(f"\nGATE {'PASSED' if ok else 'FAILED'}")
    return ok


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    batch_id = sys.argv[1]

    before = _count_unmatched(batch_id)
    print(f"batch_id: {batch_id}")
    print(f"columns the matcher refuses to read: {sorted(FORBIDDEN_COLUMNS)}")
    print(f"unmatched before tier 2: {before}")

    summary = run_tier2(batch_id)
    print(json.dumps(summary, indent=2))

    after = _count_unmatched(batch_id)
    print(f"\nunmatched before: {before}")
    print(f"unmatched after:  {after}")
    print(f"newly matched:    {before - after}")

    verify(summary)


if __name__ == "__main__":
    main()

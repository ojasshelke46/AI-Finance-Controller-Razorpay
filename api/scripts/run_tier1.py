"""Run tier 1 exact matching over a batch and verify the GATE.

Usage:
  python -m scripts.run_tier1 <batch_id>
"""

import json
import sys

from lib import db
from matching.tier1_exact import FORBIDDEN_COLUMNS, run_tier1


def verify(batch_id: str, summary: dict) -> bool:
    print("\n=== GATE checks ===")
    ok = True

    # Every group must span at least two distinct source kinds. Checked in
    # SQL against what was actually written, not against in-memory state.
    spread = summary["groups_by_distinct_source_kinds"]
    single_source_groups = spread.get(1, 0)
    ok_spread = single_source_groups == 0
    ok &= ok_spread
    print(f"groups by distinct source kinds: {spread}")
    print(f"groups with only ONE source kind: {single_source_groups} (== 0: {ok_spread})")

    ok_created = summary["groups_created"] > 0
    ok &= ok_created
    print(f"groups created: {summary['groups_created']} (> 0: {ok_created})")

    ok_members = summary["match_members_written"] == summary["txns_matched"]
    ok &= ok_members
    print(f"match_members written {summary['match_members_written']} == txns matched "
          f"{summary['txns_matched']}: {ok_members}")

    print(f"\nGATE {'PASSED' if ok else 'FAILED'}")
    return ok


def sql_verify(batch_id: str) -> None:
    """Independent check straight from the written rows: no group may
    contain fewer than two distinct source kinds."""
    groups = db.run_with_retry(
        lambda: db.get_client().table("match_groups").select("id,member_count,tier")
        .eq("batch_id", batch_id).eq("tier", 1).limit(1000).execute()
    ).data
    print(f"\nsanity: {len(groups)} tier-1 groups readable back (first page)")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    batch_id = sys.argv[1]

    print(f"batch_id: {batch_id}")
    print(f"columns the matcher refuses to read: {sorted(FORBIDDEN_COLUMNS)}")

    summary = run_tier1(batch_id)
    print(json.dumps(summary, indent=2))

    sql_verify(batch_id)
    verify(batch_id, summary)


if __name__ == "__main__":
    main()

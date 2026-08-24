"""Run the LLM variance explainer over a batch's full open queue, then
print explanations for manual GATE review (does each one cite real
amounts, or does it read as generic filler?).

Usage:
  python -m scripts.run_variance_explainer <batch_id> [sample_size]
"""

import json
import sys

from lib import db
from explain.variance_explainer import run_variance_explainer


def print_sample(batch_id: str, n: int) -> None:
    rows = db.run_with_retry(
        lambda: db.get_client().table("variances")
        .select("id,match_group_id,txn_id,variance_paise,category,subcategory,"
                "confidence,explanation,suggested_action,status")
        .eq("batch_id", batch_id)
        .not_.is_("explanation", "null")
        .order("id")
        .limit(n)
        .execute()
    ).data

    print(f"\n=== {len(rows)} explanations for manual GATE review ===")
    cites_digit = 0
    for i, r in enumerate(rows, 1):
        print(f"\n{i:>3}. variance={r['id'][:8]}  variance_paise={r['variance_paise']:>10}  "
              f"category={r['category']:<24} confidence={r['confidence']}  status={r['status']}")
        print(f"     subcategory: {r['subcategory']}")
        print(f"     explanation: {r['explanation']}")
        print(f"     suggested_action: {r['suggested_action']}")
        if any(ch.isdigit() for ch in (r["explanation"] or "")):
            cites_digit += 1

    print(f"\n{cites_digit}/{len(rows)} explanations contain at least one digit "
          f"(a cheap proxy only — read each one to confirm it cites this row's OWN "
          f"amounts, not a generic number).")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    batch_id = sys.argv[1]
    sample_size = int(sys.argv[2]) if len(sys.argv) > 2 else 15

    summary = run_variance_explainer(batch_id)
    print(json.dumps(summary, indent=2))

    print_sample(batch_id, sample_size)

    print("\n=== GATE ===")
    ran_full_queue = summary["variances_considered"] == 0 or summary["batches_sent"] > 0
    print(f"ran over full open queue: {ran_full_queue}")
    print("Manual step (not automatable): read the explanations above and confirm every "
          "one cites this row's own real amounts. Any generic-filler explanation means "
          "the prompt needs tightening before moving on.")
    print(f"GATE {'PASSED (pending manual read)' if ran_full_queue else 'FAILED'}")


if __name__ == "__main__":
    main()

"""Score a batch against ground truth and write a run_scores row.

Usage:
  python -m scripts.run_scorer <batch_id>
"""

import sys

from eval.scorer import print_report, score_batch, write_run_score


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    batch_id = sys.argv[1]

    result = score_batch(batch_id)
    print_report(result)

    run_score_id = write_run_score(result)
    print(f"\nrun_scores row written: {run_score_id}")

    print("\n=== GATE ===")
    ok = result["true_positives"] > 0 and result["_total_true_pairs"] > 0
    print(f"real score produced (TP > 0 and true pairs > 0): {ok}")
    print(f"GATE {'PASSED' if ok else 'FAILED'}")


if __name__ == "__main__":
    main()

"""Grade one batch's explainer categories against the corpus label.

Usage:
  python -m scripts.run_explainer_accuracy <batch_id> [more_batch_ids ...]

Given two batch ids it prints a before/after comparison as well, which
is how the ground-truth leak was quantified (see EVALUATION.md).
"""

import json
import sys

from eval.explainer_accuracy import grounding_pct, print_report, score_batch


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    results = []
    for batch_id in sys.argv[1:]:
        result = score_batch(batch_id)
        result["explanation_grounding_pct"] = grounding_pct(batch_id)
        print_report(result)
        print(f"\n  explanation_grounding_pct   {result['explanation_grounding_pct']}")
        results.append(result)

    if len(results) >= 2:
        before, after = results[0], results[-1]
        print("\n" + "=" * 78)
        print("BEFORE / AFTER")
        print("=" * 78)
        rows = [
            ("category_accuracy_pct", before["category_accuracy_pct"], after["category_accuracy_pct"]),
            ("explanation_grounding_pct", before["explanation_grounding_pct"], after["explanation_grounding_pct"]),
            ("leak_quotation_rate_pct", before["leak_quotation_rate_pct"], after["leak_quotation_rate_pct"]),
            ("graded", before["graded"], after["graded"]),
            ("explainer_classified", before["explainer_classified"], after["explainer_classified"]),
        ]
        print(f"\n  {'metric':<30}{'before':>12}{'after':>12}{'delta':>12}")
        print("  " + "-" * 64)
        for name, b, a in rows:
            if isinstance(b, (int, float)) and isinstance(a, (int, float)):
                delta = f"{a - b:+.2f}"
            else:
                delta = "n/a"
            print(f"  {name:<30}{str(b):>12}{str(a):>12}{delta:>12}")

    print("\n" + json.dumps(
        [{k: v for k, v in r.items() if k not in ("misses", "confusion")} for r in results],
        indent=2, default=str,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())

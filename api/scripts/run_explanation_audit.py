"""Grade the explainer's output and write explanation_grounding_pct.

Usage:
  python -m scripts.run_explanation_audit <batch_id> [sample_size]
"""

import json
import sys

from eval.explanation_audit import DEFAULT_SAMPLE_SIZE, run_explanation_audit

GATE_THRESHOLD = 90.0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    batch_id = sys.argv[1]
    sample_size = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_SAMPLE_SIZE

    result = run_explanation_audit(batch_id, sample_size)
    summary = {k: v for k, v in result.items() if k not in ("failures", "deterministic")}
    print(json.dumps(summary, indent=2))

    det = result.get("deterministic", {})
    if det:
        print("\n=== deterministic amount cross-check (not the graded metric) ===")
        print(f"  explanations citing at least one money figure : {det['cites_any_amount']}/{result['graded']}")
        print(f"  every cited figure found in the record        : {det['all_cited_figures_found_in_record']}/{result['graded']}")
        disagree = det.get("critic_passed_but_figure_not_in_record") or []
        print(f"  critic passed but a figure is not in record   : {len(disagree)}")
        for d in disagree:
            print(f"    - {d['variance_id'][:8]} unmatched={d['unmatched_figures']}")
            print(f"      {d['explanation']}")

    failures = result.get("failures") or []
    if failures:
        print(f"\n=== {len(failures)} FAILED — reset to open / unexplained ===")
        for i, f in enumerate(failures, 1):
            print(f"\n{i:>3}. variance={f['variance_id'][:8]}  was category={f['category']}  "
                  f"action={f['suggested_action']}")
            print(f"     grounded={f['grounded']}  amounts_correct={f['amounts_correct']}  "
                  f"action_appropriate={f['action_appropriate']}")
            print(f"     explanation: {f['explanation']}")
            print(f"     issue: {f['issue']}")
            det_f = f.get("deterministic_amount_check") or {}
            if det_f.get("unmatched_figures"):
                print(f"     figures not found in record: {det_f['unmatched_figures']}")
    else:
        print("\nNo failures — nothing reset to open.")

    pct = result["explanation_grounding_pct"]
    print("\n=== GATE ===")
    print(f"sample size          {result['sampled']}")
    print(f"grounding rate       {pct}%  (threshold >{GATE_THRESHOLD}%)")
    if pct is None:
        print("GATE FAILED — nothing to grade (no explained rows in this batch).")
        raise SystemExit(1)
    if pct > GATE_THRESHOLD:
        print("GATE PASSED")
    else:
        print("GATE FAILED — tighten the explainer system prompt in "
              "explain/variance_explainer.py and rerun. Do not accept this number.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

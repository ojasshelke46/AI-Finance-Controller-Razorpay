"""Run every pipeline stage over one batch, and report what it scored.

The per-stage scripts (run_tier1 ... run_scorer) exist for working on a
single stage in isolation. This one runs the same nine stages through
runtime.pipeline, which is what the scheduler calls — so it exercises
the real resumption logic rather than a hand-ordered reimplementation of
it. Re-running a batch that stopped partway skips the stages that already
recorded a stage_exit and picks up where it left off.

Usage:
  python -m scripts.run_pipeline <batch_id>
  python -m scripts.run_pipeline <batch_id> --force   # re-run every stage
"""

import json
import os
import sys

# This script drives the pipeline directly; the background scheduler
# would otherwise start up alongside it and race for the same batch lock.
os.environ.setdefault("SCHEDULER_ENABLED", "0")

from eval.explainer_accuracy import grounding_pct  # noqa: E402
from lib import db  # noqa: E402
from runtime import pipeline  # noqa: E402


def latest_score(batch_id: str) -> dict | None:
    rows = db.run_with_retry(
        lambda: db.get_client().table("run_scores").select("*")
        .eq("batch_id", batch_id).not_.is_("total_txns", "null")
        .order("run_at", desc=True).limit(1).execute()
    ).data
    return rows[0] if rows else None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    batch_id = args[0]

    batch = pipeline.get_batch(batch_id)
    if batch is None:
        print(f"no such batch: {batch_id}")
        return 1

    print(f"batch_id: {batch_id}")
    print(f"status before: {batch['status']}")
    print(f"stages already complete: {sorted(pipeline.completed_stages(batch_id))}")
    print(f"\nrunning {'every stage (--force)' if force else 'the stages that have not finished'}...\n")

    result = pipeline.run_batch(batch_id, force=force)
    print(json.dumps(result, indent=2, default=str))

    score = latest_score(batch_id)
    print("\n=== run_scores ===")
    if not score:
        print("  no scored row for this batch")
    else:
        for key in ("total_txns", "matched_txns", "match_rate", "precision",
                    "recall", "f1", "variance_explained_pct", "unexplained_paise"):
            print(f"  {key:<26}{score.get(key)}")
        print(f"  {'explanation_grounding_pct':<26}{grounding_pct(batch_id)}")

    print("\n=== GATE ===")
    ok = result.get("outcome") == "complete" and score is not None
    print(f"pipeline reached a terminal 'complete' state: {result.get('outcome') == 'complete'}")
    print(f"a scored run_scores row exists:              {score is not None}")
    print(f"GATE {'PASSED' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""GATE for POST /qna/{batch_id}: three answerable questions, then one
that the data cannot answer.

Goes through the real FastAPI route with TestClient rather than calling
answer_question() directly, so the request model, the router wiring, and
the response shape are all exercised.

Usage:
  python -m scripts.run_qna_demo <batch_id>
"""

import json
import os
import sys

# TestClient runs the app's lifespan, which would otherwise start the
# background scheduler and have it poll Razorpay mid-demo.
os.environ.setdefault("SCHEDULER_ENABLED", "0")

from fastapi.testclient import TestClient  # noqa: E402

from main import app
from routes.qna import build_context, extract_figures

ANSWERABLE = [
    "Which matching tier contributed the most matched transactions, and how many transactions was that?",
    "What was the precision of this run, and how many false positives does that correspond to?",
    "How much value is still sitting open in the variance queue, and across how many variances?",
]

UNANSWERABLE = [
    "What was the total settled value in September 2026?",
    "Which customer accounted for the largest chargeback in this batch?",
]

# Engineered to tempt a figure that is NOT in the context: the average
# is a real, derivable quantity, so the model is pulled toward doing the
# division rather than declining. Either outcome proves something worth
# proving — a clean decline shows the prompt holds, and a computed
# number shows the code guard catching what the prompt did not.
FABRICATION_BAIT = [
    "What is the average value per open variance in this batch?",
    "If the recall improved by ten percent, how much additional value would be matched?",
]


def ask(client: TestClient, batch_id: str, question: str) -> dict:
    resp = client.post(f"/qna/{batch_id}", json={"question": question})
    resp.raise_for_status()
    return resp.json()


def show(i: int, result: dict) -> None:
    print(f"\n{i}. Q: {result['question']}")
    print(f"   verified: {result['verified']}")
    print(f"   A: {result['answer']}")
    for a in result["attempts"]:
        if "error" in a:
            print(f"      attempt {a['attempt']}: call failed — {a['error']}")
        else:
            print(f"      attempt {a['attempt']}: ungrounded_figures={a['ungrounded_figures']} "
                  f"latency={a['latency_ms']}ms tokens={a['total_tokens']}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    batch_id = sys.argv[1]

    context = build_context(batch_id)
    print("=== CONTEXT SUPPLIED TO THE MODEL ===")
    print(context)
    print(f"\ncontext: {len(context)} chars (~{len(context) // 4} tokens), "
          f"{len(extract_figures(context))} distinct figures")

    client = TestClient(app)

    print("\n" + "=" * 70)
    print("ANSWERABLE QUESTIONS")
    print("=" * 70)
    answerable_results = []
    for i, q in enumerate(ANSWERABLE, 1):
        r = ask(client, batch_id, q)
        answerable_results.append(r)
        show(i, r)

    print("\n" + "=" * 70)
    print("QUESTIONS THE DATA CANNOT ANSWER")
    print("=" * 70)
    unanswerable_results = []
    for i, q in enumerate(UNANSWERABLE, 1):
        r = ask(client, batch_id, q)
        unanswerable_results.append(r)
        show(i, r)

    print("\n" + "=" * 70)
    print("FABRICATION BAIT — a derivable figure that is not in the context")
    print("=" * 70)
    bait_results = []
    for i, q in enumerate(FABRICATION_BAIT, 1):
        r = ask(client, batch_id, q)
        bait_results.append(r)
        show(i, r)
        fired = any(a.get("ungrounded_figures") for a in r["attempts"])
        print(f"      guard fired on at least one attempt: {fired}")

    verified_answerable = sum(1 for r in answerable_results if r["verified"])
    clean_declines = sum(1 for r in unanswerable_results if r["verified"])

    print("\n" + "=" * 70)
    print("GATE")
    print("=" * 70)
    print(f"answerable questions verified: {verified_answerable}/{len(ANSWERABLE)}")
    print(f"unanswerable questions returned without an untraceable figure: "
          f"{clean_declines}/{len(UNANSWERABLE)}")
    print("\nThe declines must still be read by a human: 'verified' only means every "
          "figure is traceable. Confirm each decline actually says it cannot answer "
          "rather than quoting a real but irrelevant figure as if it were the answer.")

    guard_fired = sum(1 for r in bait_results
                      if any(a.get("ungrounded_figures") for a in r["attempts"]))
    print(f"\nfabrication bait: guard fired on {guard_fired}/{len(FABRICATION_BAIT)}; "
          f"{sum(1 for r in bait_results if not r['verified'])} refused outright")

    print("\n" + json.dumps({
        "answerable_verified": verified_answerable,
        "answerable_total": len(ANSWERABLE),
        "unanswerable_clean": clean_declines,
        "unanswerable_total": len(UNANSWERABLE),
        "bait_guard_fired": guard_fired,
        "bait_refused": sum(1 for r in bait_results if not r["verified"]),
        "bait_total": len(FABRICATION_BAIT),
    }, indent=2))


if __name__ == "__main__":
    main()

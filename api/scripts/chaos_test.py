"""Five failure scenarios run against a live system.

The point is not that these five things never happen — they all happen
in production. The point is what the system does when they do: keep the
service up, keep the data defensible, and leave a record a human can
read afterwards. Each scenario therefore asserts three things:

  1. the specific expected behaviour (retry, skip, stay open, no dupes)
  2. the process is still alive at the end
  3. the batch is in a state you could defend to an auditor

A scenario "passes" only if all three hold. Anything a scenario cannot
verify honestly is reported as such rather than being asserted loosely
into a green tick.

Usage:
  python -m scripts.chaos_test [scenario_number ...]   # default: all
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("SCHEDULER_ENABLED", "0")  # this script drives things itself

import httpx  # noqa: E402

from ingest import razorpay as razorpay_ingest  # noqa: E402
from ingest.files import ingest_files, parse_bank_csv  # noqa: E402
from lib import byteplus, db  # noqa: E402
from lib.byteplus import ByteplusError, ByteplusParseError  # noqa: E402
from lib import razorpay_client  # noqa: E402
from explain import variance_explainer  # noqa: E402
from runtime import pipeline  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

SEPARATOR = "=" * 78


def log(msg: str = "") -> None:
    print(msg, flush=True)


def header(n: int, title: str) -> None:
    log("\n" + SEPARATOR)
    log(f"SCENARIO {n}: {title}")
    log(SEPARATOR)


def service_alive() -> bool:
    """The process running this test is the service under test for the
    library-level scenarios; for the HTTP surface, hit /health if an API
    is up. Either way: are we still able to do work after the fault?"""
    try:
        db.run_with_retry(
            lambda: db.get_client().table("run_state").select("id").limit(1).execute()
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def api_health() -> str:
    try:
        resp = httpx.get("http://127.0.0.1:8000/health", timeout=5.0)
        return f"HTTP {resp.status_code}"
    except Exception as exc:  # noqa: BLE001
        return f"not reachable ({type(exc).__name__})"


def make_batch(label: str) -> str:
    return pipeline.create_batch(
        label=f"chaos: {label}",
        period_start=date.today() - timedelta(days=1),
        period_end=date.today(),
    )


def audit_rows(batch_id: str, *, limit: int = 40) -> list[dict]:
    return db.run_with_retry(
        lambda: db.get_client().table("audit_log")
        .select("actor,step,action,detail,created_at")
        .eq("batch_id", batch_id).order("created_at").limit(limit).execute()
    ).data


def print_audit(batch_id: str, *, title: str, detail_chars: int = 400) -> None:
    log(f"\n--- audit_log for {batch_id} ({title}) ---")
    for row in audit_rows(batch_id):
        detail = json.dumps(row["detail"], default=str) if row["detail"] else ""
        log(f"{row['created_at'][11:19]}  {row['actor']:<10} {row['step']:<20} "
            f"{row['action']:<22} {detail[:detail_chars]}")


# ---------------------------------------------------------------------
# scenario 1 — BytePlus returns something that is not JSON
# ---------------------------------------------------------------------

def scenario_1_bad_llm_response() -> dict:
    header(1, "BytePlus returns malformed JSON")

    batch_id = make_batch("byteplus malformed json")
    checks: dict[str, bool] = {}

    # Seed one variance so the explainer has real work to do.
    txn = db.run_with_retry(
        lambda: db.get_client().table("txns").insert({
            "batch_id": batch_id, "source_kind": "bank", "external_ref": "chaos_ref_1",
            "amount_paise": 123456, "txn_date": date.today().isoformat(),
            "description": "chaos scenario 1", "raw": {"chaos": True},
        }).execute()
    ).data[0]
    variance = db.run_with_retry(
        lambda: db.get_client().table("variances").insert({
            "batch_id": batch_id, "txn_id": txn["id"], "variance_paise": 123456,
            "category": "orphan_source_missing", "status": "open",
        }).execute()
    ).data[0]
    log(f"seeded variance {variance['id']} (open) on batch {batch_id}")

    # --- 1a: the real fault, forced exactly as specified: a bad model name
    original_model = byteplus.BYTEPLUS_ARK_MODEL
    byteplus.BYTEPLUS_ARK_MODEL = "this-model-does-not-exist-chaos-test"
    try:
        log("\n[1a] pointing BytePlus at a nonexistent model name...")
        summary_bad_model = variance_explainer.run_variance_explainer(batch_id)
        log(f"     explainer returned: {json.dumps(summary_bad_model)}")
        checks["bad_model_did_not_crash"] = True
    except Exception as exc:  # noqa: BLE001
        log(f"     UNCAUGHT {type(exc).__name__}: {exc}")
        checks["bad_model_did_not_crash"] = False
    finally:
        byteplus.BYTEPLUS_ARK_MODEL = original_model

    after_bad_model = db.run_with_retry(
        lambda: db.get_client().table("variances").select("status,category,explanation")
        .eq("id", variance["id"]).execute()
    ).data[0]
    log(f"     variance after bad model: status={after_bad_model['status']}")
    checks["stayed_open_after_bad_model"] = after_bad_model["status"] == "open"

    # --- 1b: a bad model name is an HTTP error, not a parse error. To
    # actually exercise ByteplusParseError the model has to RETURN
    # something that is not JSON, so force exactly that.
    log("\n[1b] forcing BytePlus to return prose instead of JSON...")
    original_request = byteplus._request

    def prose_response(messages, *, timeout=60.0):
        return {
            "choices": [{"message": {"content":
                "Sure! Here's my analysis of the variance: it looks like a fee. "
                "I'm not going to give you JSON today."}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

    byteplus._request = prose_response
    parse_error_raised = False
    try:
        byteplus.complete_json("system", "user", "{}")
    except ByteplusParseError as exc:
        parse_error_raised = True
        log(f"     ByteplusParseError raised as expected: {str(exc)[:120]}")
        log(f"     raw text carried on the exception: {exc.raw_text[:80]!r}")
    except Exception as exc:  # noqa: BLE001
        log(f"     wrong exception type: {type(exc).__name__}: {exc}")
    checks["parse_error_raised"] = parse_error_raised

    # And confirm the explainer CATCHES it rather than dying.
    try:
        summary_prose = variance_explainer.run_variance_explainer(batch_id)
        log(f"     explainer survived prose response: {json.dumps(summary_prose)}")
        checks["explainer_caught_parse_error"] = True
    except Exception as exc:  # noqa: BLE001
        log(f"     UNCAUGHT {type(exc).__name__}: {exc}")
        checks["explainer_caught_parse_error"] = False
    finally:
        byteplus._request = original_request

    after_prose = db.run_with_retry(
        lambda: db.get_client().table("variances").select("status,category,explanation")
        .eq("id", variance["id"]).execute()
    ).data[0]
    log(f"     variance after prose response: status={after_prose['status']}")
    checks["stayed_open_after_parse_error"] = after_prose["status"] == "open"

    # --- 1c: does the batch still reach scoring with the LLM broken?
    log("\n[1c] running the full pipeline with BytePlus still pointed at a bad model...")
    byteplus.BYTEPLUS_ARK_MODEL = "this-model-does-not-exist-chaos-test"
    try:
        result = pipeline.run_batch(batch_id)
        log(f"     pipeline outcome: {result['outcome']}, stages_run={result.get('stages_run')}")
        checks["pipeline_reached_scoring"] = "score" in (result.get("stages_run") or [])
        checks["pipeline_completed"] = result["outcome"] == "complete"
    except Exception as exc:  # noqa: BLE001
        log(f"     UNCAUGHT {type(exc).__name__}: {exc}")
        checks["pipeline_reached_scoring"] = False
        checks["pipeline_completed"] = False
    finally:
        byteplus.BYTEPLUS_ARK_MODEL = original_model

    batch = pipeline.get_batch(batch_id)
    log(f"     batch status: {batch['status']}, error_text: {batch['error_text']}")
    checks["service_alive"] = service_alive()
    checks["batch_defensible"] = batch["status"] in ("complete", "failed")

    print_audit(batch_id, title="SCENARIO 1 — capture this for the demo video")

    return {"scenario": 1, "batch_id": batch_id, "checks": checks,
            "passed": all(checks.values())}


# ---------------------------------------------------------------------
# scenario 2 — Supabase connection drops mid-run
# ---------------------------------------------------------------------

def scenario_2_db_drop() -> dict:
    header(2, "Supabase connection drops mid-run")

    checks: dict[str, bool] = {}

    # Rather than cutting the machine's network (which would also cut
    # this script's ability to report), fail the transport itself for a
    # bounded number of calls — the same exception the driver raises on
    # a dropped connection, injected at the same layer.
    log("[2a] failing the next 2 Supabase calls, then letting them succeed...")
    calls = {"n": 0}
    real_run_with_retry = db.run_with_retry

    def flaky_once(fn, **kwargs):
        def wrapped():
            calls["n"] += 1
            if calls["n"] <= 2:
                raise httpx.ConnectError("chaos: connection reset by peer")
            return fn()
        return real_run_with_retry(wrapped, **kwargs)

    db.run_with_retry = flaky_once
    recovered = False
    try:
        rows = db.run_with_retry(
            lambda: db.get_client().table("run_state").select("id").limit(1).execute()
        )
        recovered = True
        log(f"     recovered after {calls['n']} attempts (retry with backoff worked)")
    except Exception as exc:  # noqa: BLE001
        log(f"     did not recover: {type(exc).__name__}: {exc}")
    finally:
        db.run_with_retry = real_run_with_retry
    checks["retry_recovered_transient_drop"] = recovered

    # Now the unrecoverable case: the outage outlasts the retries. The
    # requirement is not that this succeeds — it is that it fails
    # CLEANLY: batch marked failed, error_text set, and eligible for the
    # resume job.
    log("\n[2b] failing every Supabase call inside one stage (outage outlasts retries)...")
    batch_id = make_batch("supabase outage")
    original_tier1 = pipeline.STAGES[1]

    def exploding_tier1(_batch):
        raise httpx.ConnectError("chaos: connection reset by peer (sustained outage)")

    pipeline.STAGES[1] = ("tier1", pipeline.STATUS_MATCHING, exploding_tier1)
    try:
        result = pipeline.run_batch(batch_id)
        log(f"     pipeline outcome: {result['outcome']}, failed_stage={result.get('failed_stage')}")
        checks["failed_cleanly_not_crashed"] = result["outcome"] == "failed"
    except Exception as exc:  # noqa: BLE001
        log(f"     UNCAUGHT {type(exc).__name__}: {exc}")
        checks["failed_cleanly_not_crashed"] = False
    finally:
        pipeline.STAGES[1] = original_tier1

    batch = pipeline.get_batch(batch_id)
    log(f"     batch status: {batch['status']}")
    log(f"     error_text:   {batch['error_text']}")
    checks["status_failed"] = batch["status"] == "failed"
    checks["error_text_written"] = bool(batch["error_text"])

    tb_rows = [r for r in audit_rows(batch_id) if r["action"] == "stage_failed"]
    has_tb = bool(tb_rows) and "Traceback" in str(tb_rows[0]["detail"].get("traceback", ""))
    log(f"     traceback written to audit_log: {has_tb}")
    checks["traceback_in_audit_log"] = has_tb

    # Eligible for resume? The resume job takes non-terminal batches, so
    # a failed batch is picked up by re-running it, and the completed
    # stages are skipped. Prove the skip rather than asserting it.
    log("\n[2c] resuming the failed batch — completed stages must be skipped, not redone...")
    done_before = pipeline.completed_stages(batch_id)
    log(f"     stages already recorded complete: {sorted(done_before)}")
    resumed = pipeline.run_batch(batch_id)
    log(f"     resume outcome: {resumed['outcome']}")
    log(f"     stages skipped on resume: {resumed.get('stages_skipped')}")
    log(f"     stages run on resume:     {resumed.get('stages_run')}")
    checks["resume_skipped_completed_stages"] = (
        set(resumed.get("stages_skipped") or []) == done_before and bool(done_before)
    )
    checks["resume_reached_terminal_state"] = resumed["outcome"] in ("complete", "failed")

    checks["service_alive"] = service_alive()
    final = pipeline.get_batch(batch_id)
    checks["batch_defensible"] = final["status"] in ("complete", "failed")
    log(f"\n     final batch status: {final['status']}")

    return {"scenario": 2, "batch_id": batch_id, "checks": checks,
            "passed": all(checks.values())}


# ---------------------------------------------------------------------
# scenario 3 — Razorpay returns 429
# ---------------------------------------------------------------------

def scenario_3_rate_limit() -> dict:
    header(3, "Razorpay returns HTTP 429")

    checks: dict[str, bool] = {}
    attempts = {"n": 0}

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict, headers: dict | None = None):
            self.status_code = status_code
            self._payload = payload
            self.headers = headers or {}
            self.text = json.dumps(payload)

        def json(self):
            return self._payload

    payload = {"items": [
        {"id": "pay_chaos_429_a", "amount": 50000, "currency": "INR", "status": "captured",
         "created_at": int(datetime.now(timezone.utc).timestamp()), "fee": 1180, "tax": 180},
        {"id": "pay_chaos_429_b", "amount": 75000, "currency": "INR", "status": "captured",
         "created_at": int(datetime.now(timezone.utc).timestamp()), "fee": 1770, "tax": 270},
    ]}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None):
            attempts["n"] += 1
            # Rate limited twice, then serve the data.
            if attempts["n"] <= 2:
                return FakeResponse(429, {"error": {"description": "Too many requests"}},
                                    headers={"Retry-After": "1"})
            return FakeResponse(200, payload)

    original_client = razorpay_client._client
    razorpay_client._client = lambda: FakeClient()

    log("[3a] Razorpay 429s twice (Retry-After: 1), then succeeds...")
    started = time.monotonic()
    try:
        items = razorpay_client.fetch_payments(0, 9999999999)
        elapsed = time.monotonic() - started
        log(f"     got {len(items)} payments after {attempts['n']} HTTP attempts "
            f"in {elapsed:.1f}s")
        checks["retried_on_429"] = attempts["n"] == 3
        checks["no_data_loss"] = len(items) == len(payload["items"])
        checks["actually_backed_off"] = elapsed >= 1.0
    except Exception as exc:  # noqa: BLE001
        log(f"     FAILED: {type(exc).__name__}: {exc}")
        checks["retried_on_429"] = False
        checks["no_data_loss"] = False
        checks["actually_backed_off"] = False
    finally:
        razorpay_client._client = original_client

    # A non-retryable 4xx must NOT be retried — retrying a bad request
    # just burns quota and hides the real problem.
    log("\n[3b] a 401 must fail fast, not retry...")
    attempts["n"] = 0

    class UnauthorizedClient(FakeClient):
        def get(self, url, params=None):
            attempts["n"] += 1
            return FakeResponse(401, {"error": {"description": "unauthorized"}})

    razorpay_client._client = lambda: UnauthorizedClient()
    try:
        razorpay_client.fetch_payments(0, 9999999999)
        log("     unexpectedly succeeded")
        checks["401_fails_fast"] = False
    except razorpay_client.RazorpayError as exc:
        log(f"     RazorpayError after {attempts['n']} attempt(s): {str(exc)[:90]}")
        checks["401_fails_fast"] = attempts["n"] == 1
    finally:
        razorpay_client._client = original_client

    checks["service_alive"] = service_alive()
    checks["batch_defensible"] = True  # no batch touched in this scenario
    return {"scenario": 3, "batch_id": None, "checks": checks,
            "passed": all(checks.values())}


# ---------------------------------------------------------------------
# scenario 4 — corrupt row in the middle of the source CSV
# ---------------------------------------------------------------------

def scenario_4_corrupt_csv() -> dict:
    header(4, "Corrupt row in the middle of the bank CSV")

    checks: dict[str, bool] = {}
    source = DATA_DIR / "bank_statement.csv"
    if not source.exists():
        log(f"     source file missing: {source}")
        return {"scenario": 4, "batch_id": None, "checks": {"source_file_present": False},
                "passed": False}

    lines = source.read_text(encoding="utf-8").splitlines()
    header_line, body = lines[0], lines[1:]
    keep = body[:20]
    log(f"     using header + {len(keep)} good rows, then injecting corruption")

    # Three different corruptions, mid-file, each a real thing that
    # happens to bank exports.
    corrupt_rows = [
        ',,,,NOT-A-DATE,garbage,,,',                       # structurally broken
        f'{keep[0].split(",")[0]},CORRUPT NARRATION,not_a_number,,',  # unparseable amount
        'x' * 200,                                          # truncated/binary junk line
    ]
    scrambled = [header_line] + keep[:10] + corrupt_rows + keep[10:]

    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "chaos_bank_statement.csv"
    tmp.write_text("\n".join(scrambled) + "\n", encoding="utf-8")
    log(f"     wrote corrupted file to {tmp}")
    log(f"     corrupt rows are at lines {12}, {13}, {14} (1-indexed, header = line 1)")

    batch_id = make_batch("corrupt csv")
    skipped: list[dict] = []
    try:
        rows = parse_bank_csv(tmp, batch_id, skipped=skipped)
        log(f"\n     parsed {len(rows)} good rows, skipped {len(skipped)}")
        checks["parser_did_not_abort"] = True
    except Exception as exc:  # noqa: BLE001
        log(f"     PARSER ABORTED: {type(exc).__name__}: {exc}")
        return {"scenario": 4, "batch_id": batch_id,
                "checks": {"parser_did_not_abort": False}, "passed": False}

    for s in skipped:
        log(f"       skipped line {s['line']}: {s['reason']}")

    checks["good_rows_parsed"] = len(rows) == len(keep)
    checks["bad_rows_skipped"] = len(skipped) >= 1
    checks["skips_carry_line_numbers"] = all(
        isinstance(s.get("line"), int) for s in skipped
    )

    # And end to end through ingest_files, so the skip lands in audit_log.
    ledger = DATA_DIR / "ledger_export.xlsx"
    if ledger.exists():
        log("\n     running full ingest_files so skips reach audit_log...")
        summary = ingest_files(batch_id, tmp, ledger)
        log(f"     ingest summary: bank_parsed={summary['bank_rows_parsed']} "
            f"bank_skipped={summary['bank_rows_skipped']} "
            f"skipped_lines={summary['skipped_lines']}")
        skip_audit = [r for r in audit_rows(batch_id) if r["action"] == "records_skipped"]
        checks["skips_written_to_audit_log"] = bool(skip_audit)
        if skip_audit:
            detail = skip_audit[0]["detail"]
            log(f"     audit_log records_skipped: {json.dumps(detail)[:400]}")
        ingested = db.run_with_retry(
            lambda: db.get_client().table("txns").select("id", count="exact")
            .eq("batch_id", batch_id).eq("source_kind", "bank").execute()
        ).count
        log(f"     bank txns actually in the database: {ingested}")
        checks["good_rows_reached_database"] = ingested == len(keep)
    else:
        checks["skips_written_to_audit_log"] = False
        log("     ledger xlsx missing — cannot run full ingest_files")

    checks["service_alive"] = service_alive()
    batch = pipeline.get_batch(batch_id)
    checks["batch_defensible"] = batch["status"] in (
        "pending", "ingesting", "complete", "failed", "matching", "explaining", "scored"
    )
    return {"scenario": 4, "batch_id": batch_id, "checks": checks,
            "passed": all(checks.values())}


# ---------------------------------------------------------------------
# scenario 5 — duplicate ingestion
# ---------------------------------------------------------------------

def scenario_5_duplicate_ingest() -> dict:
    header(5, "Same range ingested twice")

    checks: dict[str, bool] = {}
    batch_id = make_batch("duplicate ingestion")

    to_date = date.today()
    from_date = to_date - timedelta(days=30)

    log(f"[5a] first ingest of {from_date} .. {to_date}")
    first = razorpay_ingest.ingest_razorpay(batch_id, from_date, to_date)
    log(f"     {json.dumps(first)}")

    count_after_first = db.run_with_retry(
        lambda: db.get_client().table("txns").select("id", count="exact")
        .eq("batch_id", batch_id).execute()
    ).count

    log(f"\n[5b] second ingest of the identical range")
    second = razorpay_ingest.ingest_razorpay(batch_id, from_date, to_date)
    log(f"     {json.dumps(second)}")

    count_after_second = db.run_with_retry(
        lambda: db.get_client().table("txns").select("id", count="exact")
        .eq("batch_id", batch_id).execute()
    ).count

    log(f"\n     txns after first ingest:  {count_after_first}")
    log(f"     txns after second ingest: {count_after_second}")
    checks["no_new_rows_on_reingest"] = count_after_first == count_after_second
    checks["second_run_added_zero"] = second.get("rows_added") == 0

    # Prove it by looking for duplicate refs, not just by trusting counts.
    rows = db.run_with_retry(
        lambda: db.get_client().table("txns").select("source_kind,external_ref")
        .eq("batch_id", batch_id).order("id").range(0, 999).execute()
    ).data
    keys = [(r["source_kind"], r["external_ref"]) for r in rows]
    duplicates = len(keys) - len(set(keys))
    log(f"     duplicate (source_kind, external_ref) pairs: {duplicates}")
    checks["zero_duplicate_refs"] = duplicates == 0

    if count_after_first == 0:
        log("\n     NOTE: this batch ingested 0 rows, so the check is vacuous.")
        checks["ingest_was_non_empty"] = False
    else:
        checks["ingest_was_non_empty"] = True

    checks["service_alive"] = service_alive()
    batch = pipeline.get_batch(batch_id)
    checks["batch_defensible"] = batch["status"] in (
        "pending", "ingesting", "complete", "failed"
    )
    return {"scenario": 5, "batch_id": batch_id, "checks": checks,
            "passed": all(checks.values())}


# ---------------------------------------------------------------------

SCENARIOS = {
    1: scenario_1_bad_llm_response,
    2: scenario_2_db_drop,
    3: scenario_3_rate_limit,
    4: scenario_4_corrupt_csv,
    5: scenario_5_duplicate_ingest,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenarios", nargs="*", type=int, choices=list(SCENARIOS),
                        help="scenario numbers to run (default: all)")
    args = parser.parse_args()
    chosen = args.scenarios or sorted(SCENARIOS)

    log(f"API /health before chaos: {api_health()}")

    results = []
    for n in chosen:
        try:
            results.append(SCENARIOS[n]())
        except Exception as exc:  # noqa: BLE001 — a crashed scenario is a failed scenario
            log(f"\nSCENARIO {n} CRASHED: {type(exc).__name__}: {exc}")
            log(traceback.format_exc())
            results.append({"scenario": n, "checks": {"scenario_itself_ran": False},
                            "passed": False})

    log("\n" + SEPARATOR)
    log("RESULTS")
    log(SEPARATOR)
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        log(f"\nscenario {r['scenario']}: {mark}")
        for name, ok in r["checks"].items():
            log(f"    {'ok  ' if ok else 'FAIL'}  {name}")
        if r.get("batch_id"):
            log(f"    batch: {r['batch_id']}")

    log(f"\nAPI /health after chaos: {api_health()}")
    passed = sum(1 for r in results if r["passed"])
    log(f"\n{passed}/{len(results)} scenarios passed")

    log("\n=== GATE ===")
    if passed == len(results):
        log("GATE PASSED — every scenario ended with the service alive and the "
            "batch in a defensible state.")
        return 0
    log("GATE FAILED — see the failing checks above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

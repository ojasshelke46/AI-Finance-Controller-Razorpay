"""The whole reconciliation run, end to end, as one resumable function.

Nine stages in fixed order: ingest, tiers 1-4, variance queue, LLM
explainer, explanation audit, scorer. Every stage bookends itself with
an audit_log row, and those rows ARE the resumption state — there is no
separate progress table to drift out of sync with what actually ran.
Re-running a batch that died at stage 7 reads its own audit trail,
skips the six stages that recorded a stage_exit, and picks up where it
stopped. That matters here because stages 7 and 8 cost real money in
LLM calls; redoing them because stage 9 threw would be paying twice for
work already done.

Failure is contained to one batch. A stage that raises marks its batch
failed, writes the full traceback, and returns — it does not propagate,
because the scheduler that calls this is processing other batches that
have nothing to do with the one that broke.

Concurrency: a lock row in run_state, held per batch. Two scheduler
ticks that both decide a batch needs work cannot both run it — the
second sees the lock and leaves. The lock carries a timestamp and can
be stolen once stale, so a process that dies mid-run does not wedge a
batch forever.

This is honest about its limits: the lock is advisory and the steal is
a compare-and-set on the lock's own timestamp, which is sufficient for
the single scheduler process this system runs. It is not a distributed
lock and should not be treated as one if this ever runs on more than
one node.
"""

import logging
import os
import socket
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from eval.explanation_audit import run_explanation_audit
from eval.scorer import score_batch, write_run_score
from explain.variance_explainer import run_variance_explainer
from ingest.razorpay import ingest_razorpay
from lib import db
from matching.tier1_exact import run_tier1
from matching.tier2_normalised import run_tier2
from matching.tier3_fee_aware import run_tier3
from matching.tier4_aggregate import run_tier4
from matching.variance import populate_variance_queue

logger = logging.getLogger("runtime.pipeline")

ACTOR = "scheduler"
STEP = "pipeline"

LOCK_TTL_MINUTES = 45  # longer than a healthy run; only stale locks get stolen
AUDIT_SAMPLE_SIZE = 30
INGEST_LOOKBACK_DAYS = 30

# batches.status is a CHECK-constrained enum; these are the only legal
# values, so each stage maps onto one rather than inventing its own.
STATUS_INGESTING = "ingesting"
STATUS_MATCHING = "matching"
STATUS_EXPLAINING = "explaining"
STATUS_SCORED = "scored"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"
TERMINAL_STATUSES = frozenset({STATUS_COMPLETE, STATUS_FAILED})


# ---------------------------------------------------------------------
# audit trail
# ---------------------------------------------------------------------

def write_audit(batch_id: str | None, action: str, detail: dict, *, step: str = STEP) -> None:
    db.run_with_retry(
        lambda: db.get_client().table("audit_log").insert({
            "batch_id": batch_id, "actor": ACTOR, "step": step,
            "action": action, "detail": detail,
        }).execute()
    )


def _page_audit(batch_id: str, action: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client().table("audit_log")
            .select("id,action,detail,created_at")
            .eq("batch_id", batch_id).eq("step", STEP).eq("action", action)
            .order("id").range(o, o + 999).execute()
        ).data
        rows.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    return rows


def completed_stages(batch_id: str) -> set[str]:
    """Which stages have already finished, read back from the batch's own
    audit trail. A stage counts as done only if it wrote a stage_exit —
    a stage_enter with no matching exit means it died partway and must
    run again."""
    return {
        row["detail"].get("stage")
        for row in _page_audit(batch_id, "stage_exit")
        if isinstance(row.get("detail"), dict) and row["detail"].get("stage")
    }


# ---------------------------------------------------------------------
# lock
# ---------------------------------------------------------------------

def _holder_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _lock_key(batch_id: str) -> str:
    return f"batch_lock:{batch_id}"


def acquire_named_lock(key: str, *, ttl_minutes: int = LOCK_TTL_MINUTES) -> bool:
    """True if this process now holds `key`. Insert wins the lock
    outright (the key is unique); if a row already exists, the lock is
    only stolen when it is older than the TTL, and the steal is
    conditional on the timestamp it was read at — so two processes
    racing to steal the same stale lock cannot both succeed."""
    now = datetime.now(timezone.utc)
    payload = {"holder": _holder_id(), "acquired_at": now.isoformat()}

    try:
        db.get_client().table("run_state").insert({"key": key, "value": payload}).execute()
        return True
    except Exception:  # noqa: BLE001 — unique violation is the expected path
        pass

    rows = db.run_with_retry(
        lambda: db.get_client().table("run_state").select("id,key,value")
        .eq("key", key).limit(1).execute()
    ).data
    if not rows:
        return False

    existing = rows[0].get("value") or {}
    acquired_at = existing.get("acquired_at")
    if not acquired_at:
        return False
    try:
        held_since = datetime.fromisoformat(acquired_at)
    except ValueError:
        return False
    if held_since.tzinfo is None:
        held_since = held_since.replace(tzinfo=timezone.utc)

    if now - held_since < timedelta(minutes=ttl_minutes):
        return False

    # Compare-and-set on the timestamp we just read.
    stolen = db.run_with_retry(
        lambda: db.get_client().table("run_state")
        .update({"value": payload})
        .eq("key", key).eq("value->>acquired_at", acquired_at).execute()
    ).data
    if stolen:
        logger.warning("stole stale lock %s (held since %s)", key, acquired_at)
        return True
    return False


def release_named_lock(key: str) -> None:
    db.run_with_retry(
        lambda: db.get_client().table("run_state").delete().eq("key", key).execute()
    )


def acquire_lock(batch_id: str, *, ttl_minutes: int = LOCK_TTL_MINUTES) -> bool:
    return acquire_named_lock(_lock_key(batch_id), ttl_minutes=ttl_minutes)


def release_lock(batch_id: str) -> None:
    release_named_lock(_lock_key(batch_id))


def is_locked(batch_id: str) -> bool:
    rows = db.run_with_retry(
        lambda: db.get_client().table("run_state").select("id")
        .eq("key", _lock_key(batch_id)).limit(1).execute()
    ).data
    return bool(rows)


# ---------------------------------------------------------------------
# batch helpers
# ---------------------------------------------------------------------

def get_batch(batch_id: str) -> dict | None:
    rows = db.run_with_retry(
        lambda: db.get_client().table("batches").select("*").eq("id", batch_id).limit(1).execute()
    ).data
    return rows[0] if rows else None


def set_status(batch_id: str, status: str, *, error_text: str | None = None,
               completed: bool = False, clear_error: bool = False) -> None:
    """Writes the batch's current state.

    clear_error exists because error_text describes the batch NOW, not
    every bad thing that ever happened to it. A batch that failed at a
    stage, got resumed, and then ran all nine stages to completion is
    complete — but it used to keep the old error_text forever, so the
    console showed a green COMPLETE badge and a red "this run failed"
    banner on the same screen, which is worse than either alone. The
    failure is not being erased: stage_failed and batch_failed rows,
    with the full traceback, stay in audit_log where the history
    belongs.
    """
    patch: dict = {"status": status}
    if error_text is not None:
        patch["error_text"] = error_text[:4000]
    elif clear_error:
        patch["error_text"] = None
    if completed:
        patch["completed_at"] = datetime.now(timezone.utc).isoformat()
    db.run_with_retry(
        lambda: db.get_client().table("batches").update(patch).eq("id", batch_id).execute()
    )


def create_batch(label: str, period_start: date, period_end: date) -> str:
    row = db.run_with_retry(
        lambda: db.get_client().table("batches").insert({
            "label": label,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "status": "pending",
        }).execute()
    ).data[0]
    return row["id"]


# ---------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------

def _stage_ingest(batch: dict) -> dict:
    """Razorpay is the pipeline's own source. File ingestion is a
    separate, operator-driven path (scripts/run_file_ingest.py): the
    exported CSV/XLSX belong to a specific batch, so pulling them into
    every scheduled batch would duplicate rows that were never part of
    that period's activity."""
    period_end = (
        date.fromisoformat(batch["period_end"]) if batch.get("period_end") else date.today()
    )
    period_start = (
        date.fromisoformat(batch["period_start"]) if batch.get("period_start")
        else period_end - timedelta(days=INGEST_LOOKBACK_DAYS)
    )
    return ingest_razorpay(batch["id"], period_start, period_end)


def _merge_grounding_stub(batch_id: str, run_score_id: str) -> float | None:
    """Fold any metric-only run_scores row into the row the scorer just
    wrote, and delete the stub.

    Why this is needed: the audit stage runs BEFORE the scorer (that is
    the specified order), so when the audit goes to record its grounding
    percentage there is no run_scores row for the batch yet and it
    inserts a row carrying only that one metric. The scorer then inserts
    the real row, leaving the batch with two partial rows instead of one
    complete one. Rather than reorder the stages or make the audit
    silently drop its number, the scorer adopts the orphan.
    """
    stubs = db.run_with_retry(
        lambda: db.get_client().table("run_scores")
        .select("id,explanation_grounding_pct")
        .eq("batch_id", batch_id).is_("total_txns", "null")
        .not_.is_("explanation_grounding_pct", "null")
        .order("run_at").execute()
    ).data
    if not stubs:
        return None

    pct = stubs[-1]["explanation_grounding_pct"]
    db.run_with_retry(
        lambda: db.get_client().table("run_scores")
        .update({"explanation_grounding_pct": pct}).eq("id", run_score_id).execute()
    )
    for stub in stubs:
        db.run_with_retry(
            lambda s=stub: db.get_client().table("run_scores").delete().eq("id", s["id"]).execute()
        )
    logger.info("merged grounding pct %s from %d stub row(s) into run_score %s",
                pct, len(stubs), run_score_id)
    return pct


def _stage_score(batch: dict) -> dict:
    result = score_batch(batch["id"])
    run_score_id = write_run_score(result)
    grounding_pct = _merge_grounding_stub(batch["id"], run_score_id)
    result["explanation_grounding_pct"] = grounding_pct
    return {
        "explanation_grounding_pct": grounding_pct,
        "run_score_id": run_score_id,
        "total_txns": result.get("total_txns"),
        "matched_txns": result.get("matched_txns"),
        "precision": result.get("precision"),
        "recall": result.get("recall"),
        "f1": result.get("f1"),
        "unexplained_paise": result.get("unexplained_paise"),
    }


Stage = tuple[str, str, Callable[[dict], dict]]

STAGES: list[Stage] = [
    ("ingest", STATUS_INGESTING, _stage_ingest),
    ("tier1", STATUS_MATCHING, lambda b: run_tier1(b["id"])),
    ("tier2", STATUS_MATCHING, lambda b: run_tier2(b["id"])),
    ("tier3", STATUS_MATCHING, lambda b: run_tier3(b["id"])),
    ("tier4", STATUS_MATCHING, lambda b: run_tier4(b["id"])),
    ("variance", STATUS_MATCHING, lambda b: populate_variance_queue(b["id"])),
    ("explain", STATUS_EXPLAINING, lambda b: run_variance_explainer(b["id"])),
    ("audit", STATUS_EXPLAINING, lambda b: run_explanation_audit(b["id"], AUDIT_SAMPLE_SIZE)),
    ("score", STATUS_SCORED, _stage_score),
]

STAGE_NAMES = [name for name, _, _ in STAGES]


def _summarise(result) -> dict:
    """Stage summaries go into audit_log detail. Keep them small — the
    audit trail is read constantly for resumption and must not turn into
    a dumping ground for whole result payloads."""
    if not isinstance(result, dict):
        return {"result": str(result)[:500]}
    out = {}
    for k, v in result.items():
        if isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, str):
            out[k] = v[:200]
        elif isinstance(v, (list, tuple)):
            out[k] = f"<{len(v)} items>"
        else:
            out[k] = f"<{type(v).__name__}>"
    return out


# ---------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------

def run_batch(batch_id: str, *, force: bool = False) -> dict:
    """Executes every stage not already recorded as complete.

    Never raises for a stage failure — the batch is marked failed and the
    outcome is returned, so a caller looping over batches keeps going.
    """
    batch = get_batch(batch_id)
    if batch is None:
        return {"batch_id": batch_id, "outcome": "not_found"}

    if not acquire_lock(batch_id):
        logger.info("batch %s is locked by another worker — skipping", batch_id)
        return {"batch_id": batch_id, "outcome": "locked"}

    already = set() if force else completed_stages(batch_id)
    started = time.monotonic()
    write_audit(batch_id, "batch_started", {
        "already_complete": sorted(already),
        "to_run": [s for s in STAGE_NAMES if s not in already],
        "force": force,
        "holder": _holder_id(),
    })

    ran: list[str] = []
    skipped: list[str] = []

    try:
        for name, status, fn in STAGES:
            if name in already:
                skipped.append(name)
                write_audit(batch_id, "stage_skipped", {
                    "stage": name, "reason": "already recorded a stage_exit for this batch",
                })
                continue

            set_status(batch_id, status)
            write_audit(batch_id, "stage_enter", {"stage": name, "batch_status": status})
            stage_started = time.monotonic()

            try:
                result = fn(batch)
            except Exception as exc:  # noqa: BLE001 — deliberately broad, see docstring
                tb = traceback.format_exc()
                elapsed = round(time.monotonic() - stage_started, 2)
                logger.exception("batch %s failed in stage %s", batch_id, name)
                set_status(batch_id, STATUS_FAILED, error_text=f"stage {name}: {exc}")
                write_audit(batch_id, "stage_failed", {
                    "stage": name,
                    "error": str(exc)[:1000],
                    "error_type": type(exc).__name__,
                    "traceback": tb[:8000],
                    "elapsed_seconds": elapsed,
                })
                write_audit(batch_id, "batch_failed", {
                    "failed_stage": name,
                    "stages_run": ran,
                    "stages_skipped": skipped,
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                })
                return {
                    "batch_id": batch_id, "outcome": "failed", "failed_stage": name,
                    "error": str(exc), "stages_run": ran, "stages_skipped": skipped,
                }

            elapsed = round(time.monotonic() - stage_started, 2)
            ran.append(name)
            write_audit(batch_id, "stage_exit", {
                "stage": name, "elapsed_seconds": elapsed, "summary": _summarise(result),
            })

        set_status(batch_id, STATUS_COMPLETE, completed=True, clear_error=True)
        total = round(time.monotonic() - started, 2)
        write_audit(batch_id, "batch_complete", {
            "stages_run": ran, "stages_skipped": skipped, "elapsed_seconds": total,
        })
        return {
            "batch_id": batch_id, "outcome": "complete",
            "stages_run": ran, "stages_skipped": skipped, "elapsed_seconds": total,
        }
    finally:
        release_lock(batch_id)

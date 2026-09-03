"""The part that runs without anybody asking it to.

Five jobs, started from the FastAPI lifespan handler:

  every 15 min   poll Razorpay for activity newer than the cursor in
                 run_state; if there is any, open a batch and run the
                 whole pipeline over it
  every 15 min   find batches stuck in a non-terminal state for more
                 than 30 minutes and resume them (the pipeline is
                 resumable, so this costs only the stages that did not
                 finish)
  every 6 hours  re-run the explainer over variances still sitting open
                 as 'unexplained' — the counterpart record may have
                 arrived since
  daily 02:00    write a rollup of the previous day into audit_log
  irregularly    seed a little synthetic Razorpay test activity, so the
                 poll job has something organic to discover. OFF unless
                 AUTO_SEED_ENABLED says otherwise — see auto_seed_enabled()

APScheduler's BackgroundScheduler is used deliberately over the async
variant: every stage in this system is blocking (HTTP to Razorpay,
Postgres round-trips, LLM calls that take minutes). Running those on
the event loop would stall every HTTP request the API is serving, so
they run on scheduler threads instead.

Two independent guards stop the same work being done twice:
  - max_instances=1 per job, so a tick that overruns its interval does
    not stack up behind itself in this process
  - a lock row in run_state per batch (and per job), so a tick in
    ANOTHER process still cannot pick up a batch this one is running.
The second is what actually matters — the first only knows about this
process.
"""

import logging
import os
import random
import traceback
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from eval.explanation_audit import run_explanation_audit
from explain.variance_explainer import run_variance_explainer
from lib import db
from lib.razorpay_client import (
    RazorpayError,
    fetch_payments,
    fetch_settlements,
    refund_payment,
)
from runtime.pipeline import (
    AUDIT_SAMPLE_SIZE,
    TERMINAL_STATUSES,
    acquire_lock,
    acquire_named_lock,
    create_batch,
    is_locked,
    release_lock,
    release_named_lock,
    run_batch,
    write_audit,
)

logger = logging.getLogger("runtime.scheduler")

STEP = "scheduler"

POLL_MINUTES = 15
RESUME_MINUTES = 15
RETRY_UNEXPLAINED_HOURS = 6
ROLLUP_HOUR = 2

STUCK_AFTER_MINUTES = 30
POLL_LOOKBACK_DAYS = 30
CURSOR_KEY = "razorpay_cursor"
MAX_BATCHES_PER_RETRY_TICK = 3

# Auto-seed (job 5). The gap between runs is a floor plus a fresh random
# offset, not a period. APScheduler's jitter is ONE-sided — it adds
# random.uniform(0, jitter) to every next_run_time it computes — so a
# 20-minute interval with 70 minutes of jitter puts consecutive gaps
# uniformly across 20..90 minutes, redrawn each time. That is the whole
# point: a fixed tick reads as a cron job on any graph of it, and this is
# meant to read as a merchant taking payments.
AUTO_SEED_BASE_MINUTES = 20
AUTO_SEED_JITTER_MINUTES = 70
# Must stay under the 20-minute floor above, so a lock orphaned by a
# killed process cannot still be blocking the next run.
AUTO_SEED_LOCK_MINUTES = 15
AUTO_SEED_QUIET_CHANCE = 0.35
AUTO_SEED_MIN_PAYMENTS = 1
AUTO_SEED_MAX_PAYMENTS = 4
AUTO_SEED_MIN_PAISE = 30_000    # Rs 300
AUTO_SEED_MAX_PAISE = 500_000   # Rs 5,000
AUTO_SEED_REFUND_CHANCE = 0.2   # roughly one run in five

_scheduler: BackgroundScheduler | None = None


def _audit(action: str, detail: dict, batch_id: str | None = None) -> None:
    write_audit(batch_id, action, detail, step=STEP)


# ---------------------------------------------------------------------
# cursor
# ---------------------------------------------------------------------

def get_cursor() -> int | None:
    rows = db.run_with_retry(
        lambda: db.get_client().table("run_state").select("value")
        .eq("key", CURSOR_KEY).limit(1).execute()
    ).data
    if not rows:
        return None
    value = rows[0].get("value") or {}
    ts = value.get("last_seen_created_at")
    return int(ts) if ts is not None else None


def set_cursor(ts: int) -> None:
    payload = {
        "key": CURSOR_KEY,
        "value": {
            "last_seen_created_at": int(ts),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    db.run_with_retry(
        lambda: db.get_client().table("run_state").upsert(payload, on_conflict="key").execute()
    )


# ---------------------------------------------------------------------
# job 1 — poll for new activity
# ---------------------------------------------------------------------

def poll_razorpay_activity() -> dict:
    """Settlements are the ideal trigger, but a Razorpay TEST account
    never produces them — test payments are captured and never settle.
    So the poller treats settlements as the primary signal and payments
    as the fallback: a payment is the activity that will eventually
    settle, and it is what actually exists to be detected here. Both are
    tracked on one cursor of max created_at, so nothing is processed
    twice and nothing between ticks is missed."""
    lock = "job_lock:poll_razorpay"
    if not acquire_named_lock(lock, ttl_minutes=POLL_MINUTES * 2):
        logger.info("poll tick skipped — another worker holds the poll lock")
        return {"outcome": "locked"}

    try:
        cursor = get_cursor()
        now_ts = int(datetime.now(timezone.utc).timestamp())
        from_ts = cursor + 1 if cursor else int(
            (datetime.now(timezone.utc) - timedelta(days=POLL_LOOKBACK_DAYS)).timestamp()
        )

        if from_ts > now_ts:
            _audit("poll_no_activity", {"reason": "cursor is ahead of now", "cursor": cursor})
            return {"outcome": "no_activity"}

        try:
            settlements = fetch_settlements(from_ts, now_ts)
            payments = fetch_payments(from_ts, now_ts)
        except RazorpayError as exc:
            logger.error("razorpay poll failed: %s", exc)
            _audit("poll_failed", {"error": str(exc)[:1000], "from_ts": from_ts, "to_ts": now_ts})
            return {"outcome": "poll_failed", "error": str(exc)}

        fresh_settlements = [s for s in settlements
                             if cursor is None or (s.get("created_at") or 0) > cursor]
        fresh_payments = [p for p in payments
                          if cursor is None or (p.get("created_at") or 0) > cursor]

        if not fresh_settlements and not fresh_payments:
            _audit("poll_no_activity", {
                "cursor": cursor, "from_ts": from_ts, "to_ts": now_ts,
                "settlements_seen": len(settlements), "payments_seen": len(payments),
            })
            return {"outcome": "no_activity"}

        stamps = [x.get("created_at") for x in fresh_settlements + fresh_payments
                  if x.get("created_at")]
        max_ts = max(stamps)
        min_ts = min(stamps)
        period_start = datetime.fromtimestamp(min_ts, tz=timezone.utc).date()
        period_end = datetime.fromtimestamp(max_ts, tz=timezone.utc).date()

        batch_id = create_batch(
            label=f"auto {period_start} to {period_end}",
            period_start=period_start,
            period_end=period_end,
        )
        _audit("poll_detected_activity", {
            "new_settlements": len(fresh_settlements),
            "new_payments": len(fresh_payments),
            "cursor_before": cursor,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "batch_created": batch_id,
        }, batch_id=batch_id)

        # Advance the cursor as soon as the batch exists. The work is now
        # captured by that batch — if the pipeline dies, the resume job
        # finishes it. Leaving the cursor behind would instead make the
        # next tick open a SECOND batch for the same activity.
        set_cursor(max_ts)

        result = run_batch(batch_id)
        _audit("poll_pipeline_finished", {"batch_id": batch_id, **result}, batch_id=batch_id)
        return {"outcome": "ran", "batch_id": batch_id, "pipeline": result}
    except Exception as exc:  # noqa: BLE001 — a scheduler job must never die silently
        logger.exception("poll job crashed")
        _audit("job_crashed", {
            "job": "poll_razorpay_activity",
            "error": str(exc)[:1000],
            "traceback": traceback.format_exc()[:8000],
        })
        return {"outcome": "crashed", "error": str(exc)}
    finally:
        release_named_lock(lock)


# ---------------------------------------------------------------------
# job 2 — resume stuck batches
# ---------------------------------------------------------------------

def _last_activity_at(batch_id: str, fallback: str | None) -> datetime | None:
    rows = db.run_with_retry(
        lambda: db.get_client().table("audit_log").select("created_at")
        .eq("batch_id", batch_id).order("created_at", desc=True).limit(1).execute()
    ).data
    stamp = rows[0]["created_at"] if rows else fallback
    if not stamp:
        return None
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def resume_stuck_batches() -> dict:
    """A batch is stuck if it is not in a terminal state and nothing has
    been written about it for STUCK_AFTER_MINUTES. Resuming is cheap
    because run_batch skips every stage that already recorded an exit —
    so this re-runs the stage that died, not the whole run."""
    try:
        rows = db.run_with_retry(
            lambda: db.get_client().table("batches").select("id,status,created_at")
            .not_.in_("status", list(TERMINAL_STATUSES)).order("created_at").execute()
        ).data
    except Exception as exc:  # noqa: BLE001
        logger.exception("resume job could not list batches")
        _audit("job_crashed", {"job": "resume_stuck_batches", "error": str(exc)[:1000],
                               "traceback": traceback.format_exc()[:8000]})
        return {"outcome": "crashed", "error": str(exc)}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=STUCK_AFTER_MINUTES)
    resumed: list[dict] = []
    considered = 0

    for row in rows:
        considered += 1
        batch_id = row["id"]
        last = _last_activity_at(batch_id, row.get("created_at"))
        if last is None or last > cutoff:
            continue
        if is_locked(batch_id):
            continue

        _audit("resuming_stuck_batch", {
            "batch_id": batch_id, "status": row["status"],
            "idle_minutes": round((now - last).total_seconds() / 60, 1),
        }, batch_id=batch_id)
        result = run_batch(batch_id)
        _audit("resume_finished", {"batch_id": batch_id, **result}, batch_id=batch_id)
        resumed.append({"batch_id": batch_id, **result})

    if not resumed:
        _audit("resume_nothing_stuck", {"non_terminal_batches": considered})
    return {"outcome": "ok", "considered": considered, "resumed": resumed}


# ---------------------------------------------------------------------
# job 3 — retry still-unexplained variances
# ---------------------------------------------------------------------

def retry_unexplained_variances() -> dict:
    """Rows the model honestly refused to classify are not permanently
    dead: the missing counterpart record may have been ingested since.
    Re-running the explainer over them is the cheap way to find out, and
    anything it now explains is re-audited before it counts as settled."""
    try:
        rows: list[dict] = []
        offset = 0
        while True:
            page = db.run_with_retry(
                lambda o=offset: db.get_client().table("variances").select("batch_id")
                .eq("status", "open").eq("category", "unexplained")
                .order("id").range(o, o + 999).execute()
            ).data
            rows.extend(page)
            if len(page) < 1000:
                break
            offset += 1000
    except Exception as exc:  # noqa: BLE001
        logger.exception("retry job could not list variances")
        _audit("job_crashed", {"job": "retry_unexplained_variances", "error": str(exc)[:1000],
                               "traceback": traceback.format_exc()[:8000]})
        return {"outcome": "crashed", "error": str(exc)}

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["batch_id"]] = counts.get(r["batch_id"], 0) + 1

    if not counts:
        _audit("retry_nothing_unexplained", {})
        return {"outcome": "ok", "batches": []}

    ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:MAX_BATCHES_PER_RETRY_TICK]
    results = []
    for batch_id, count in ordered:
        if not acquire_lock(batch_id):
            continue
        try:
            _audit("retry_unexplained_start", {"batch_id": batch_id, "open_unexplained": count},
                   batch_id=batch_id)
            explained = run_variance_explainer(batch_id)
            audited = run_explanation_audit(batch_id, AUDIT_SAMPLE_SIZE)
            detail = {
                "batch_id": batch_id,
                "open_unexplained_before": count,
                "newly_explained": explained.get("explained"),
                "still_open": explained.get("still_open_unexplained"),
                "grounding_pct": audited.get("explanation_grounding_pct"),
                "audit_failed": audited.get("failed"),
            }
            _audit("retry_unexplained_finished", detail, batch_id=batch_id)
            results.append(detail)
        except Exception as exc:  # noqa: BLE001 — one batch failing must not stop the rest
            logger.exception("retry failed for batch %s", batch_id)
            _audit("retry_unexplained_failed", {
                "batch_id": batch_id, "error": str(exc)[:1000],
                "traceback": traceback.format_exc()[:8000],
            }, batch_id=batch_id)
        finally:
            release_lock(batch_id)

    return {"outcome": "ok", "batches": results}


# ---------------------------------------------------------------------
# job 4 — daily rollup
# ---------------------------------------------------------------------

def _count(table: str, column: str, start: str, end: str, **filters) -> int:
    q = db.get_client().table(table).select("id", count="exact") \
        .gte(column, start).lt(column, end)
    for k, v in filters.items():
        q = q.eq(k, v)
    return db.run_with_retry(lambda: q.execute()).count or 0


def daily_rollup(day: date | None = None) -> dict:
    """One row summarising yesterday. Written into audit_log rather than
    a separate table on purpose: the audit trail is already the record
    of what this system did, and a rollup is a claim about that trail,
    so it belongs beside the events it summarises."""
    try:
        target = day or (datetime.now(timezone.utc).date() - timedelta(days=1))
        start = datetime.combine(target, datetime.min.time(), tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        s, e = start.isoformat(), end.isoformat()

        batches_created = _count("batches", "created_at", s, e)
        batches_completed = _count("batches", "completed_at", s, e)
        batches_failed = _count("batches", "created_at", s, e, status="failed")
        variances_opened = _count("variances", "created_at", s, e)
        groups_created = _count("match_groups", "created_at", s, e)
        scores_written = _count("run_scores", "run_at", s, e)

        score_rows = db.run_with_retry(
            lambda: db.get_client().table("run_scores")
            .select("precision,recall,f1,unexplained_paise,explanation_grounding_pct")
            .gte("run_at", s).lt("run_at", e).order("run_at").execute()
        ).data

        unexplained_paise = sum(int(r.get("unexplained_paise") or 0) for r in score_rows)
        graded = [r["explanation_grounding_pct"] for r in score_rows
                  if r.get("explanation_grounding_pct") is not None]

        detail = {
            "date": target.isoformat(),
            "batches_created": batches_created,
            "batches_completed": batches_completed,
            "batches_failed": batches_failed,
            "match_groups_created": groups_created,
            "variances_opened": variances_opened,
            "run_scores_written": scores_written,
            "unexplained_paise_total": unexplained_paise,
            "mean_explanation_grounding_pct": (
                round(sum(graded) / len(graded), 2) if graded else None
            ),
        }
        write_audit(None, "daily_rollup", detail, step="rollup")
        logger.info("daily rollup for %s: %s", target, detail)
        return detail
    except Exception as exc:  # noqa: BLE001
        logger.exception("rollup job crashed")
        _audit("job_crashed", {"job": "daily_rollup", "error": str(exc)[:1000],
                               "traceback": traceback.format_exc()[:8000]})
        return {"outcome": "crashed", "error": str(exc)}


# ---------------------------------------------------------------------
# job 5 — seed synthetic activity (opt in)
# ---------------------------------------------------------------------

def auto_seed_enabled() -> bool:
    """Opt in, and deliberately the inverse of scheduler_enabled(): off
    unless someone explicitly turns it on. Every payment this creates is
    found by the poll job on its next tick and flows through the entire
    pipeline, which spends real LLM budget on whichever provider is
    primary at the time — so an accidental 'on' is not free."""
    return os.getenv("AUTO_SEED_ENABLED", "0").lower() in ("1", "true", "yes")


def auto_seed_activity() -> dict:
    """Drip a small amount of synthetic merchant activity into the
    connected Razorpay TEST account, so the poll job has something
    organic to discover instead of somebody running scripts.seed_razorpay
    by hand before every demo.

    Nothing here is special-cased downstream: the payments it creates are
    ordinary Razorpay test records, indistinguishable from manually
    seeded ones once ingested. The audit_log entry this job writes is the
    only thing that tells the two apart later, which is why it is written
    on every run — including the runs that deliberately do nothing.

    seed_card_payment is imported inside the function rather than at
    module scope, unlike the other four jobs' shared logic: it pulls in
    playwright, which is a local-only dependency and is not in
    requirements.txt, so a top-level import would break the deployed API
    for the sake of a job that is off by default there anyway.
    """
    from scripts.seed_razorpay import seed_card_payment

    lock = "job_lock:auto_seed"
    if not acquire_named_lock(lock, ttl_minutes=AUTO_SEED_LOCK_MINUTES):
        logger.info("auto-seed tick skipped — another worker holds the seed lock")
        return {"outcome": "locked"}

    try:
        # Real merchant activity has gaps in it. A tick that fires is not
        # a tick that has to produce something, or the "organic" activity
        # is just a slower, wobblier drip.
        if random.random() < AUTO_SEED_QUIET_CHANCE:
            _audit("auto_seeded_activity", {
                "payments_seeded": 0, "total_paise": 0, "refunds_issued": 0,
                "outcome": "quiet_tick",
            })
            logger.info("auto-seed tick was a deliberate no-op")
            return {"outcome": "quiet", "payments_seeded": 0}

        wanted = random.randint(AUTO_SEED_MIN_PAYMENTS, AUTO_SEED_MAX_PAYMENTS)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        seeded: list[dict] = []
        failures: list[str] = []

        for i in range(wanted):
            # Whole rupees, in the range the rest of this corpus lives in.
            amount = random.randrange(AUTO_SEED_MIN_PAISE, AUTO_SEED_MAX_PAISE + 1, 100)
            try:
                payment_id = seed_card_payment(amount, f"auto seed {stamp} #{i + 1}")
            except Exception as exc:  # noqa: BLE001 — one flaky checkout must not lose the rest
                logger.warning("auto-seed could not create a payment: %s", exc)
                failures.append(str(exc)[:300])
                continue
            seeded.append({"payment_id": payment_id, "amount_paise": amount})

        refunds: list[dict] = []
        if seeded and random.random() < AUTO_SEED_REFUND_CHANCE:
            target = random.choice(seeded)
            partial = target["amount_paise"] // 3 if random.random() < 0.5 else None
            try:
                refund_payment(target["payment_id"], amount_paise=partial)
                refunds.append({
                    "payment_id": target["payment_id"],
                    "amount_paise": partial if partial is not None else target["amount_paise"],
                    "kind": "partial" if partial is not None else "full",
                })
            except RazorpayError as exc:
                logger.warning("auto-seed refund failed: %s", exc)
                failures.append(str(exc)[:300])

        detail = {
            "payments_seeded": len(seeded),
            "total_paise": sum(s["amount_paise"] for s in seeded),
            "refunds_issued": len(refunds),
            "refunded_paise": sum(r["amount_paise"] for r in refunds),
            "payment_ids": [s["payment_id"] for s in seeded],
            "refunds": refunds,
            "attempted": wanted,
            "failures": failures,
            "outcome": "seeded",
        }
        _audit("auto_seeded_activity", detail)
        logger.info("auto-seeded %s payment(s) worth %s paise", len(seeded), detail["total_paise"])
        return {"outcome": "seeded", **detail}
    except Exception as exc:  # noqa: BLE001 — a scheduler job must never die silently
        logger.exception("auto-seed job crashed")
        _audit("job_crashed", {
            "job": "auto_seed_activity",
            "error": str(exc)[:1000],
            "traceback": traceback.format_exc()[:8000],
        })
        return {"outcome": "crashed", "error": str(exc)}
    finally:
        release_named_lock(lock)


# ---------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------

def scheduler_enabled() -> bool:
    """Off switch for contexts that import the app without wanting a
    live scheduler — test clients, CLI scripts, one-off imports. On by
    default, because the scheduler running unattended is the point."""
    return os.getenv("SCHEDULER_ENABLED", "1").lower() not in ("0", "false", "no")


def build_scheduler(*, run_poll_at_startup: bool = True) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    common = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 300}

    # Fire the first poll immediately rather than 15 minutes after boot:
    # a system restarted after downtime should find the work waiting for
    # it now, not a quarter of an hour later.
    first_poll = datetime.now(timezone.utc) if run_poll_at_startup else None

    scheduler.add_job(poll_razorpay_activity, IntervalTrigger(minutes=POLL_MINUTES),
                      id="poll_razorpay_activity", next_run_time=first_poll,
                      name="poll Razorpay for new activity", **common)
    scheduler.add_job(resume_stuck_batches, IntervalTrigger(minutes=RESUME_MINUTES),
                      id="resume_stuck_batches", name="resume stuck batches", **common)
    scheduler.add_job(retry_unexplained_variances,
                      IntervalTrigger(hours=RETRY_UNEXPLAINED_HOURS),
                      id="retry_unexplained_variances",
                      name="retry unexplained variances", **common)
    scheduler.add_job(daily_rollup, CronTrigger(hour=ROLLUP_HOUR, minute=0),
                      id="daily_rollup", name="daily rollup", **common)

    if auto_seed_enabled():
        logger.warning(
            "AUTO_SEED_ENABLED is on: this process will CREATE synthetic Razorpay "
            "test payments and refunds on its own, at irregular %s-%s minute "
            "intervals. Every one of them is picked up by the poll job and run "
            "through the full pipeline, spending real LLM budget. Turn this off "
            "outside of an active demo or recording session.",
            AUTO_SEED_BASE_MINUTES,
            AUTO_SEED_BASE_MINUTES + AUTO_SEED_JITTER_MINUTES,
        )
        scheduler.add_job(
            auto_seed_activity,
            IntervalTrigger(minutes=AUTO_SEED_BASE_MINUTES,
                            jitter=AUTO_SEED_JITTER_MINUTES * 60),
            id="auto_seed_activity", name="auto-seed synthetic activity", **common)
    return scheduler


def start() -> BackgroundScheduler | None:
    global _scheduler
    if not scheduler_enabled():
        logger.info("scheduler disabled by SCHEDULER_ENABLED")
        return None
    if _scheduler is not None:
        return _scheduler
    _scheduler = build_scheduler()
    _scheduler.start()
    jobs = [{"id": j.id, "next_run": str(j.next_run_time)} for j in _scheduler.get_jobs()]
    logger.info("scheduler started with jobs: %s", jobs)
    _audit("scheduler_started", {"jobs": jobs})
    return _scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _audit("scheduler_stopping", {})
    _scheduler.shutdown(wait=False)
    _scheduler = None

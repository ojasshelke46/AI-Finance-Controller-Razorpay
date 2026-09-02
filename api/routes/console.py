"""Read/write endpoints backing the operations console.

Money crosses this boundary as integer paise and nothing else. No
endpoint here returns a formatted rupee string or a float — the client
formats for display, the server stays exact. A float in a reconciliation
API is how you end up explaining a one-paise discrepancy to an auditor.

Every list endpoint paginates with an explicit .order("id") before
.range(), because PostgREST caps a response at 1000 rows and does not
guarantee stable ordering across pages without it.
"""

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from eval.explanation_audit import deterministic_amount_check
from explain.variance_explainer import _TXN_DETAIL_COLUMNS, _txn_detail
from lib import db

logger = logging.getLogger("routes.console")

router = APIRouter(prefix="/console", tags=["console"])

_PAGE = 1000

# scripts/chaos_test.py names every batch it creates "chaos: <scenario>".
# That prefix is the only marker distinguishing a deliberately broken
# batch from a real run, so it is named here rather than being spelled
# out inline at each use.
CHAOS_LABEL_PREFIX = "chaos:"
MAX_BATCHES = 100


def _page_all(table: str, columns: str, *, batch_id: str | None = None, **filters) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        q = db.get_client().table(table).select(columns)
        if batch_id:
            q = q.eq("batch_id", batch_id)
        for k, v in filters.items():
            q = q.eq(k, v)

        page = db.run_with_retry(
            lambda qq=q, o=offset: qq.order("id").range(o, o + _PAGE - 1).execute()
        ).data
        rows.extend(page)
        if len(page) < _PAGE:
            break
        offset += _PAGE
    return rows


def _count(table: str, **filters) -> int:
    q = db.get_client().table(table).select("id", count="exact")
    for k, v in filters.items():
        q = q.eq(k, v)
    return db.run_with_retry(lambda: q.execute()).count or 0


def _members_for_groups(group_ids: list[str]) -> dict[str, list[str]]:
    """Members of the given groups, fetched BY GROUP ID.

    match_members has no batch_id column, so the obvious "page the table
    and filter in Python" reads every membership row in the database —
    fine on the first batch, thirty seconds once a dozen batches exist.
    Chunked id filters keep it proportional to the batch being viewed
    rather than to the history of the whole system.
    """
    members: dict[str, list[str]] = defaultdict(list)
    for i in range(0, len(group_ids), 100):
        chunk = group_ids[i:i + 100]
        offset = 0
        while True:
            page = db.run_with_retry(
                lambda c=chunk, o=offset: db.get_client().table("match_members")
                .select("id,match_group_id,txn_id").in_("match_group_id", c)
                .order("id").range(o, o + _PAGE - 1).execute()
            ).data
            for row in page:
                members[row["match_group_id"]].append(row["txn_id"])
            if len(page) < _PAGE:
                break
            offset += _PAGE
    return members


def _latest_run_score(batch_id: str) -> dict | None:
    rows = db.run_with_retry(
        lambda: db.get_client().table("run_scores").select("*")
        .eq("batch_id", batch_id).order("run_at", desc=True).limit(1).execute()
    ).data
    return rows[0] if rows else None


# ---------------------------------------------------------------------
# live status
# ---------------------------------------------------------------------

@router.get("/status")
def status():
    """Everything the landing page needs to prove the system runs itself."""
    from runtime import scheduler as sched

    running = sched._scheduler is not None and sched._scheduler.running
    jobs = []
    if running:
        for job in sched._scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_at": job.next_run_time.isoformat() if job.next_run_time else None,
            })

    next_run_at = min(
        (j["next_run_at"] for j in jobs if j["next_run_at"]), default=None
    )

    last_pipeline = db.run_with_retry(
        lambda: db.get_client().table("audit_log")
        .select("batch_id,action,created_at,detail")
        .eq("step", "pipeline").in_("action", ["batch_complete", "batch_failed"])
        .order("created_at", desc=True).limit(1).execute()
    ).data
    last_run = last_pipeline[0] if last_pipeline else None

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    batches_today = db.run_with_retry(
        lambda: db.get_client().table("batches").select("id", count="exact")
        .gte("created_at", today.isoformat()).execute()
    ).count or 0
    completed_today = db.run_with_retry(
        lambda: db.get_client().table("batches").select("id", count="exact")
        .gte("completed_at", today.isoformat()).execute()
    ).count or 0

    # Chaos-test batches are excluded from the headline score, and the
    # label is carried through so the card can name the batch it is
    # quoting instead of showing a bare uuid.
    #
    # scripts/chaos_test.py deliberately corrupts its batches — a CSV with
    # junk rows mid-file, an LLM pointed at a dead model, an injected
    # database outage. They score near zero BECAUSE the test worked. This
    # page exists to answer "is the system working", and a batch built to
    # be broken is not evidence either way; left in, the most recent one
    # headlined the whole system at 3.66% match / 0.00% precision with
    # nothing on the card to say it was a fault injection.
    #
    # Filtered in the query via an inner join on batches rather than in
    # Python, so "most recent non-chaos score" stays one round trip.
    latest_score = db.run_with_retry(
        lambda: db.get_client().table("run_scores")
        .select("batch_id,run_at,match_rate,precision,recall,f1,total_txns,"
                "explanation_grounding_pct,batches!inner(label)")
        .not_.like("batches.label", f"{CHAOS_LABEL_PREFIX}%")
        .order("run_at", desc=True).limit(1).execute()
    ).data
    score = latest_score[0] if latest_score else None
    if score:
        # Flatten the embedded row: the client wants a label, not a nested
        # resource it has to know the shape of.
        score["label"] = (score.pop("batches", None) or {}).get("label")

    # Total open variance value across every batch — the number an
    # operations lead actually cares about at a glance.
    #
    # Filtered in the query, not in Python: pulling every variance ever
    # written and discarding the closed ones cost seconds on the landing
    # page, which is the one page that has to feel instant.
    open_variances = _page_all("variances", "id,variance_paise,batch_id", status="open")
    unexplained_paise = sum(abs(int(v["variance_paise"] or 0)) for v in open_variances)
    open_count = len(open_variances)

    recent_events = db.run_with_retry(
        lambda: db.get_client().table("audit_log")
        .select("batch_id,actor,step,action,created_at")
        .order("created_at", desc=True).limit(12).execute()
    ).data

    return {
        "scheduler_running": running,
        "jobs": jobs,
        "next_run_at": next_run_at,
        "last_run": {
            "batch_id": last_run["batch_id"],
            "action": last_run["action"],
            "at": last_run["created_at"],
            "elapsed_seconds": (last_run.get("detail") or {}).get("elapsed_seconds"),
            "stages_run": (last_run.get("detail") or {}).get("stages_run"),
        } if last_run else None,
        "batches_created_today": batches_today,
        "batches_completed_today": completed_today,
        "latest_score": score,
        "unexplained_paise": unexplained_paise,
        "open_variance_count": open_count,
        "recent_events": recent_events,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------
# batches
# ---------------------------------------------------------------------

@router.get("/batches")
def list_batches(limit: int = Query(MAX_BATCHES, ge=1, le=MAX_BATCHES)):
    batches = db.run_with_retry(
        lambda: db.get_client().table("batches")
        .select("id,label,status,period_start,period_end,created_at,completed_at,error_text")
        .order("created_at", desc=True).limit(limit).execute()
    ).data
    if not batches:
        return {"batches": []}

    ids = [b["id"] for b in batches]

    scores = db.run_with_retry(
        lambda: db.get_client().table("run_scores")
        .select("batch_id,run_at,match_rate,precision,recall,f1,total_txns,matched_txns,"
                "unexplained_paise,explanation_grounding_pct")
        .in_("batch_id", ids).order("run_at", desc=True).execute()
    ).data
    score_by_batch: dict[str, dict] = {}
    for s in scores:  # ordered newest first, so first wins
        score_by_batch.setdefault(s["batch_id"], s)

    # Open variances for EVERY listed batch in one paginated read rather
    # than one read per batch. The per-batch version issued two round
    # trips per row of the table; at twenty batches that was twenty
    # seconds of blank screen.
    open_by_batch: dict[str, list[int]] = defaultdict(list)
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client().table("variances")
            .select("id,batch_id,variance_paise").in_("batch_id", ids).eq("status", "open")
            .order("id").range(o, o + _PAGE - 1).execute()
        ).data
        for row in page:
            open_by_batch[row["batch_id"]].append(abs(int(row["variance_paise"] or 0)))
        if len(page) < _PAGE:
            break
        offset += _PAGE

    # Row counts stay one query per batch (PostgREST has no GROUP BY),
    # but they run concurrently instead of in series.
    with ThreadPoolExecutor(max_workers=8) as pool:
        txn_counts = dict(
            zip(ids, pool.map(lambda batch_id: _count("txns", batch_id=batch_id), ids))
        )

    out = []
    for b in batches:
        score = score_by_batch.get(b["id"])
        txn_count = txn_counts.get(b["id"], 0)
        open_rows = open_by_batch.get(b["id"], [])
        out.append({
            **b,
            "txn_count": txn_count,
            "match_rate": score.get("match_rate") if score else None,
            "precision": score.get("precision") if score else None,
            "recall": score.get("recall") if score else None,
            "f1": score.get("f1") if score else None,
            "explanation_grounding_pct": score.get("explanation_grounding_pct") if score else None,
            "open_variance_count": len(open_rows),
            "unexplained_paise": sum(open_rows),
        })
    return {"batches": out}


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: str):
    rows = db.run_with_retry(
        lambda: db.get_client().table("batches").select("*").eq("id", batch_id).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="batch not found")
    batch = rows[0]

    txns = _page_all("txns", "id,source_kind,amount_paise", batch_id=batch_id)
    groups = _page_all("match_groups", "id,tier,strategy,member_count,total_variance_paise",
                       batch_id=batch_id)

    # Count real members rather than trusting match_groups.member_count,
    # which goes stale when tier 4 absorbs an existing group.
    members_by_group = _members_for_groups([g["id"] for g in groups])

    tiers: dict[int, dict] = defaultdict(
        lambda: {"groups": 0, "txns": 0, "strategy": "", "residual_paise": 0}
    )
    for g in groups:
        t = tiers[g["tier"]]
        t["groups"] += 1
        t["txns"] += len(members_by_group.get(g["id"], []))
        t["strategy"] = g.get("strategy") or ""
        t["residual_paise"] += int(g.get("total_variance_paise") or 0)

    variances = _page_all("variances", "id,variance_paise,status,category", batch_id=batch_id)
    by_status: dict[str, dict] = defaultdict(lambda: {"count": 0, "paise": 0})
    by_category: dict[str, dict] = defaultdict(lambda: {"count": 0, "paise": 0})
    for v in variances:
        amount = abs(int(v["variance_paise"] or 0))
        s = by_status[v["status"] or "unknown"]
        s["count"] += 1
        s["paise"] += amount
        c = by_category[v["category"] or "uncategorised"]
        c["count"] += 1
        c["paise"] += amount

    matched_txn_ids = {tid for ids in members_by_group.values() for tid in ids}

    funnel = [{
        "label": "Records ingested",
        "kind": "total",
        "txns": len(txns),
        "groups": None,
        "strategy": "razorpay + bank + ledger",
        "residual_paise": 0,
    }]
    for tier in sorted(tiers):
        t = tiers[tier]
        funnel.append({
            "label": f"Tier {tier}",
            "kind": "tier",
            "tier": tier,
            "txns": t["txns"],
            "groups": t["groups"],
            "strategy": t["strategy"],
            "residual_paise": t["residual_paise"],
        })
    funnel.append({
        "label": "Variance queue",
        "kind": "variance",
        "txns": len(txns) - len(matched_txn_ids),
        "groups": len(variances),
        "strategy": "unmatched records + unbalanced groups",
        "residual_paise": sum(abs(int(v["variance_paise"] or 0)) for v in variances),
    })

    return {
        "batch": batch,
        "score": _latest_run_score(batch_id),
        "funnel": funnel,
        "totals": {
            "txns": len(txns),
            "matched_txns": len(matched_txn_ids),
            "match_groups": len(groups),
            "variances": len(variances),
            "by_source": {
                kind: sum(1 for t in txns if t["source_kind"] == kind)
                for kind in sorted({t["source_kind"] for t in txns})
            },
        },
        "variances_by_status": dict(by_status),
        "variances_by_category": dict(by_category),
    }


# ---------------------------------------------------------------------
# variance queue — the actual product
# ---------------------------------------------------------------------

@router.get("/batches/{batch_id}/variances")
def list_variances(
    batch_id: str,
    category: str | None = None,
    status: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
):
    rows = _page_all(
        "variances",
        "id,batch_id,match_group_id,txn_id,variance_paise,category,subcategory,"
        "confidence,explanation,suggested_action,status,model_raw,created_at",
        batch_id=batch_id,
    )
    # Filter options come from the UNFILTERED queue. Deriving them from
    # the filtered rows would make selecting one category hide every
    # other category, leaving the operator stuck inside their own filter.
    all_categories = sorted({(r.get("category") or "uncategorised") for r in rows})

    if category:
        rows = [r for r in rows if (r.get("category") or "") == category]
    if status:
        rows = [r for r in rows if (r.get("status") or "") == status]

    rows.sort(key=lambda r: abs(int(r["variance_paise"] or 0)), reverse=True)
    rows = rows[:limit]

    txn_ids = {r["txn_id"] for r in rows if r.get("txn_id")}
    group_ids = {r["match_group_id"] for r in rows if r.get("match_group_id")}

    members_by_group: dict[str, list[str]] = defaultdict(list)
    if group_ids:
        members_by_group = _members_for_groups(list(group_ids))
        for ids_in_group in members_by_group.values():
            txn_ids.update(ids_in_group)

    txns_by_id: dict[str, dict] = {}
    if txn_ids:
        ids = list(txn_ids)
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            fetched = db.run_with_retry(
                lambda c=chunk: db.get_client().table("txns")
                .select(",".join(_TXN_DETAIL_COLUMNS)).in_("id", c).order("id").execute()
            ).data
            for t in fetched:
                txns_by_id[t["id"]] = t

    groups_by_id: dict[str, dict] = {}
    if group_ids:
        ids = list(group_ids)
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            fetched = db.run_with_retry(
                lambda c=chunk: db.get_client().table("match_groups")
                .select("id,tier,strategy,confidence,member_count,total_variance_paise,"
                        "variance_components").in_("id", c).order("id").execute()
            ).data
            for g in fetched:
                groups_by_id[g["id"]] = g

    out = []
    for r in rows:
        records = []
        if r.get("txn_id") and r["txn_id"] in txns_by_id:
            records.append(_txn_detail(txns_by_id[r["txn_id"]]))
        group = None
        if r.get("match_group_id"):
            group = groups_by_id.get(r["match_group_id"])
            for tid in members_by_group.get(r["match_group_id"], []):
                if tid in txns_by_id:
                    records.append(_txn_detail(txns_by_id[tid]))

        # Which figures in the explanation can be traced back to the
        # records? The console shows this per row, so an operator can see
        # at a glance whether the model's numbers are its own invention.
        context = {
            "variance_paise": r["variance_paise"],
            "match_group": group,
            "records": records,
        }
        traced = deterministic_amount_check(context, r.get("explanation") or "")

        out.append({
            **r,
            "records": records,
            "match_group": group,
            "cited_figures": traced["cited_figures"],
            "untraceable_figures": traced["unmatched_figures"],
            "all_figures_traceable": traced["all_cited_found"],
        })

    return {"variances": out, "categories": all_categories, "total": len(out)}


class VarianceAction(BaseModel):
    action: Literal["accept", "write_off", "reopen"]
    note: str | None = Field(default=None, max_length=1000)
    operator: str = Field(default="console", max_length=120)


_ACTION_STATUS = {"accept": "accepted", "write_off": "written_off", "reopen": "open"}


@router.post("/variances/{variance_id}/action")
def act_on_variance(variance_id: str, body: VarianceAction):
    """Operator decision on one variance. Writes the new status AND an
    audit_log row — a status change with no record of who changed it or
    what it looked like beforehand is not an auditable ledger."""
    rows = db.run_with_retry(
        lambda: db.get_client().table("variances").select("*")
        .eq("id", variance_id).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="variance not found")
    variance = rows[0]

    new_status = _ACTION_STATUS[body.action]
    db.run_with_retry(
        lambda: db.get_client().table("variances")
        .update({"status": new_status}).eq("id", variance_id).execute()
    )
    db.run_with_retry(
        lambda: db.get_client().table("audit_log").insert({
            "batch_id": variance["batch_id"],
            "actor": "human",
            "step": "console",
            "action": f"variance_{body.action}",
            "detail": {
                "variance_id": variance_id,
                "operator": body.operator,
                "note": body.note,
                "status_before": variance["status"],
                "status_after": new_status,
                "variance_paise": variance["variance_paise"],
                "category": variance["category"],
                "suggested_action": variance["suggested_action"],
                "followed_suggestion": (
                    body.action == "write_off" and variance["suggested_action"] == "write_off"
                ) or (
                    body.action == "accept" and variance["suggested_action"] == "auto_accept"
                ),
            },
        }).execute()
    )
    return {"variance_id": variance_id, "status": new_status, "action": body.action}


# ---------------------------------------------------------------------
# audit trail
# ---------------------------------------------------------------------

@router.get("/batches/{batch_id}/audit")
def batch_audit(
    batch_id: str,
    actor: str | None = None,
    step: str | None = None,
    limit: int = Query(500, ge=1, le=2000),
):
    q = db.get_client().table("audit_log") \
        .select("id,batch_id,actor,step,action,detail,created_at").eq("batch_id", batch_id)
    if actor:
        q = q.eq("actor", actor)
    if step:
        q = q.eq("step", step)
    rows = db.run_with_retry(
        lambda: q.order("created_at").limit(limit).execute()
    ).data

    all_rows = db.run_with_retry(
        lambda: db.get_client().table("audit_log").select("actor,step")
        .eq("batch_id", batch_id).limit(2000).execute()
    ).data
    return {
        "events": rows,
        "actors": sorted({r["actor"] for r in all_rows if r["actor"]}),
        "steps": sorted({r["step"] for r in all_rows if r["step"]}),
        "total": len(rows),
    }

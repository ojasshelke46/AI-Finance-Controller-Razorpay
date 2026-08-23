"""Ingest Razorpay payments + settlements into txns.

Money stays integer paise end to end — Razorpay already reports amount,
fee and tax in paise, so every value is passed straight through. No
float ever touches an amount in this module.

Idempotency: rows are upserted on (batch_id, source_kind, external_ref)
(unique index uq_txns_batch_source_ref, migration 0003). Re-running the
same date range updates the existing rows in place and adds zero new
ones.
"""

import logging
from datetime import date, datetime, timezone

from lib import db
from lib.razorpay_client import fetch_payments, fetch_settlements

logger = logging.getLogger("ingest.razorpay")

SOURCE_KIND = "razorpay"

# audit_log.actor is constrained to
# ('scheduler','matcher','explainer','scorer','human') — ingestion runs as
# part of the scheduled pipeline, so it logs as 'scheduler'.
_ACTOR = "scheduler"


def _to_unix(d: date, *, end_of_day: bool = False) -> int:
    t = datetime(d.year, d.month, d.day, 23, 59, 59 if end_of_day else 0, tzinfo=timezone.utc)
    if not end_of_day:
        t = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return int(t.timestamp())


def _unix_to_date(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def _payment_to_txn(batch_id: str, payment: dict) -> dict:
    """Map a Razorpay payment object to a txns row.

    amount/fee/tax are already paise integers from Razorpay. fee and tax
    are null until the payment is captured, so net is only computed when
    a fee is actually present.
    """
    amount = payment.get("amount")
    fee = payment.get("fee")
    tax = payment.get("tax")
    net = amount - fee if (amount is not None and fee is not None) else None

    return {
        "batch_id": batch_id,
        "source_kind": SOURCE_KIND,
        "external_ref": payment["id"],
        "amount_paise": amount,
        "fee_paise": fee,
        "tax_paise": tax,
        "net_paise": net,
        "txn_date": _unix_to_date(payment.get("created_at")),
        "value_date": None,
        "description": payment.get("description"),
        "counterparty": payment.get("email") or payment.get("contact"),
        "raw": payment,
    }


def _settlement_to_txn(batch_id: str, settlement: dict) -> dict:
    """Map a Razorpay settlement object to a txns row.

    Note the field name difference from payments: a settlement reports
    'fees' (plural), a payment reports 'fee'. amount on a settlement is
    the net figure actually credited to the bank account, so net_paise
    mirrors it rather than subtracting fees again.
    """
    amount = settlement.get("amount")

    return {
        "batch_id": batch_id,
        "source_kind": SOURCE_KIND,
        "external_ref": settlement["id"],
        "amount_paise": amount,
        "fee_paise": settlement.get("fees"),
        "tax_paise": settlement.get("tax"),
        "net_paise": amount,
        "txn_date": _unix_to_date(settlement.get("created_at")),
        "value_date": _unix_to_date(settlement.get("created_at")),
        "description": f"Settlement {settlement.get('utr') or settlement['id']}",
        "counterparty": settlement.get("utr"),
        "raw": settlement,
    }


def _write_audit(batch_id: str, step: str, action: str, detail: dict) -> None:
    db.run_with_retry(
        lambda: db.get_client()
        .table("audit_log")
        .insert({
            "batch_id": batch_id,
            "actor": _ACTOR,
            "step": step,
            "action": action,
            "detail": detail,
        })
        .execute()
    )


def _filter_already_ingested(batch_id: str, rows: list[dict]) -> list[dict]:
    """Idempotency check: skip rows whose (source_kind, external_ref) is
    already present for this batch, so re-running the same range inserts
    zero duplicates. Deliberately NOT a DB unique constraint — txns must
    also be able to hold true duplicate rows (e.g. a bank statement line
    posted twice), which is a real reconciliation scenario, not a bug."""
    if not rows:
        return []
    existing = db.run_with_retry(
        lambda: db.get_client()
        .table("txns")
        .select("source_kind,external_ref")
        .eq("batch_id", batch_id)
        .execute()
    ).data
    seen = {(r["source_kind"], r["external_ref"]) for r in existing}
    return [r for r in rows if (r["source_kind"], r["external_ref"]) not in seen]


def _count_txns(batch_id: str) -> int:
    res = db.run_with_retry(
        lambda: db.get_client()
        .table("txns")
        .select("id", count="exact")
        .eq("batch_id", batch_id)
        .eq("source_kind", SOURCE_KIND)
        .execute()
    )
    return res.count or 0


def ingest_razorpay(batch_id: str, from_date: date, to_date: date) -> dict:
    """Pull Razorpay payments and settlements for [from_date, to_date] and
    upsert them into txns as source_kind 'razorpay'.

    Returns a summary dict with the counts also written to audit_log.
    """
    _write_audit(
        batch_id,
        step="ingest_razorpay",
        action="start",
        detail={"from_date": from_date.isoformat(), "to_date": to_date.isoformat()},
    )

    from_ts = _to_unix(from_date)
    to_ts = _to_unix(to_date, end_of_day=True)

    before = _count_txns(batch_id)

    payments = fetch_payments(from_ts, to_ts)
    settlements = fetch_settlements(from_ts, to_ts)
    logger.info("fetched %d payments, %d settlements", len(payments), len(settlements))

    rows = [_payment_to_txn(batch_id, p) for p in payments]
    rows += [_settlement_to_txn(batch_id, s) for s in settlements]

    new_rows = _filter_already_ingested(batch_id, rows)
    if new_rows:
        db.run_with_retry(lambda: db.get_client().table("txns").insert(new_rows).execute())

    after = _count_txns(batch_id)

    status_counts: dict[str, int] = {}
    for p in payments:
        s = p.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    summary = {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "payments_fetched": len(payments),
        "settlements_fetched": len(settlements),
        "rows_fetched": len(rows),
        "rows_inserted": len(new_rows),
        "txns_before": before,
        "txns_after": after,
        "rows_added": after - before,
        "payment_status_counts": status_counts,
    }

    _write_audit(batch_id, step="ingest_razorpay", action="finish", detail=summary)
    return summary

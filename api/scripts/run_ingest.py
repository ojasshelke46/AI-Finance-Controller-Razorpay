"""Run Razorpay ingestion for a date range into a batch.

Usage:
  python -m scripts.run_ingest                      # today, new batch
  python -m scripts.run_ingest 2026-08-01 2026-08-31
  python -m scripts.run_ingest 2026-08-01 2026-08-31 <existing_batch_id>
"""

import json
import sys
from datetime import date, timedelta

from ingest.razorpay import ingest_razorpay
from lib import db


def get_or_create_batch(batch_id: str | None, from_date: date, to_date: date) -> str:
    if batch_id:
        return batch_id
    res = db.run_with_retry(
        lambda: db.get_client()
        .table("batches")
        .insert({
            "label": f"razorpay ingest {from_date} to {to_date}",
            "period_start": from_date.isoformat(),
            "period_end": to_date.isoformat(),
            "status": "ingesting",
        })
        .execute()
    )
    return res.data[0]["id"]


def main():
    args = sys.argv[1:]
    if len(args) >= 2:
        from_date = date.fromisoformat(args[0])
        to_date = date.fromisoformat(args[1])
    else:
        to_date = date.today()
        from_date = to_date - timedelta(days=30)

    batch_id = args[2] if len(args) >= 3 else None
    batch_id = get_or_create_batch(batch_id, from_date, to_date)

    print(f"batch_id: {batch_id}")
    summary = ingest_razorpay(batch_id, from_date, to_date)
    print(json.dumps(summary, indent=2))
    return batch_id


if __name__ == "__main__":
    main()

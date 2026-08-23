"""Parse the exported source files back into a fresh batch and verify the
round-trip against the corpus batch they were generated from.

Usage:
  python -m scripts.run_file_ingest <source_batch_id> [data_dir]
"""

import json
import sys
from datetime import date
from pathlib import Path

from ingest.files import ingest_files
from lib import db

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _page_all(batch_id: str, source_kind: str, columns: str) -> list[dict]:
    out: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client()
            .table("txns")
            .select(columns)
            .eq("batch_id", batch_id)
            .eq("source_kind", source_kind)
            .order("id")
            .range(o, o + page_size - 1)
            .execute()
        ).data
        out.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return out


def create_batch(label: str) -> str:
    res = db.run_with_retry(
        lambda: db.get_client()
        .table("batches")
        .insert({
            "label": label,
            "period_start": date.today().isoformat(),
            "period_end": date.today().isoformat(),
            "status": "ingesting",
        })
        .execute()
    )
    return res.data[0]["id"]


def verify(source_batch_id: str, parsed_batch_id: str, summary: dict) -> bool:
    print("\n=== GATE checks ===")
    ok = True

    for kind, parsed_key in (("bank", "bank_rows_parsed"), ("ledger", "ledger_rows_parsed")):
        source = _page_all(source_batch_id, kind, "external_ref,amount_paise,txn_date")
        parsed = _page_all(parsed_batch_id, kind, "external_ref,amount_paise,txn_date")

        count_ok = len(source) == len(parsed) == summary[parsed_key]
        ok &= count_ok
        print(f"{kind:>7} count: generator={len(source)} parsed={len(parsed)} (match: {count_ok})")

        # Compare as multisets so genuine duplicate rows still have to line up.
        def key(rows):
            return sorted((r["external_ref"], r["amount_paise"], r["txn_date"]) for r in rows)

        content_ok = key(source) == key(parsed)
        ok &= content_ok
        print(f"{kind:>7} content round-trip exact (ref+paise+date): {content_ok}")
        if not content_ok:
            s, p = key(source), key(parsed)
            diff = [x for x in s if x not in set(p)][:5]
            print(f"        first mismatches: {diff}")

    print(f"\nrows with unrecoverable reference: bank={summary['bank_missing_ref']} "
          f"ledger={summary['ledger_missing_ref']}")
    ok &= summary["bank_missing_ref"] == 0 and summary["ledger_missing_ref"] == 0

    print(f"\nGATE {'PASSED' if ok else 'FAILED'}")
    return ok


def spot_check(parsed_batch_id: str, n: int = 5) -> None:
    """Show the ugliest raw formatting alongside the parsed paise value."""
    rows = _page_all(parsed_batch_id, "bank", "external_ref,amount_paise,description,raw")
    rows += _page_all(parsed_batch_id, "ledger", "external_ref,amount_paise,description,raw")

    def ugliness(r):
        raw = r["raw"] or {}
        text = (raw.get("debit") or "") + (raw.get("credit") or "") + (raw.get("amount") or "")
        return (text.count(",") * 10) + len(text) + len(r.get("description") or "") // 20

    worst = sorted(rows, key=ugliness, reverse=True)[:n]

    print(f"\n=== spot check: {n} ugliest rows ===")
    for r in worst:
        raw = r["raw"] or {}
        raw_amount = raw.get("debit") or raw.get("credit") or raw.get("amount") or ""
        col = "debit" if raw.get("debit") else ("credit" if raw.get("credit") else "amount")
        print(f"  raw {col:>6}={raw_amount!r:>20}  ref={r['external_ref']!r:>16}  "
              f"-> {r['amount_paise']:>12} paise")
        print(f"      narration/particulars: {r['description']!r}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    source_batch_id = sys.argv[1]
    data_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DATA_DIR

    parsed_batch_id = create_batch(f"parsed from files (source {source_batch_id[:8]})")
    print(f"source batch: {source_batch_id}")
    print(f"parsed batch: {parsed_batch_id}")

    summary = ingest_files(
        parsed_batch_id,
        data_dir / "bank_statement.csv",
        data_dir / "ledger_export.xlsx",
    )
    print(json.dumps(summary, indent=2))

    spot_check(parsed_batch_id)
    verify(source_batch_id, parsed_batch_id, summary)
    return parsed_batch_id


if __name__ == "__main__":
    main()

"""Generate a synthetic reconciliation corpus with a known answer key.

Creates NUM_EVENTS underlying economic events and projects each into up
to three txns rows (source_kind razorpay / bank / ledger). Every row
from the same real event carries the same truth_group — that's the
ground truth a matcher's output gets scored against. Noise rows carry
truth_group = NULL, is_noise = true.

Run: cd api && source .venv/bin/activate && python -m scripts.generate_corpus
"""

import math
import os
import random
import string
import uuid
from collections import Counter
from datetime import date, timedelta

from lib import db

# ---------------------------------------------------------------------
# Configurable constants
# ---------------------------------------------------------------------

NUM_EVENTS = 1000

# Category distribution — must sum to 1.0.
PCT_CLEAN_3WAY = 0.55
PCT_FEE_TAX_SPLIT = 0.15
PCT_VALUE_DATE_DRIFT = 0.08
PCT_REF_FORMAT_DRIFT = 0.06
PCT_MANY_TO_ONE = 0.06
PCT_REFUND_CHARGEBACK = 0.03
PCT_MISSING_ONE_SOURCE = 0.03
PCT_DUPLICATE_ONE_SOURCE = 0.02
PCT_GENUINE_NOISE = 0.02

_PCTS = {
    "clean_3way": PCT_CLEAN_3WAY,
    "fee_tax_split": PCT_FEE_TAX_SPLIT,
    "value_date_drift": PCT_VALUE_DATE_DRIFT,
    "ref_format_drift": PCT_REF_FORMAT_DRIFT,
    "many_to_one": PCT_MANY_TO_ONE,
    "refund_chargeback": PCT_REFUND_CHARGEBACK,
    "missing_one_source": PCT_MISSING_ONE_SOURCE,
    "duplicate_one_source": PCT_DUPLICATE_ONE_SOURCE,
    "genuine_noise": PCT_GENUINE_NOISE,
}
assert abs(sum(_PCTS.values()) - 1.0) < 1e-9, f"category percentages must sum to 1.0, got {sum(_PCTS.values())}"

# Real Razorpay fee structure observed in Phase 0: a flat percentage fee
# plus 18% GST charged on that fee.
FEE_RATE = 0.02
GST_RATE = 0.18

MANY_TO_ONE_GROUP_MIN = 5
MANY_TO_ONE_GROUP_MAX = 40

# Long-tail amount distribution: lognormal, clipped, rounded to whole paise.
AMOUNT_MIN_PAISE = 100          # INR 1
AMOUNT_MAX_PAISE = 5_000_000    # INR 50,000
_AMOUNT_MU = math.log(5_000)    # median around INR 50
_AMOUNT_SIGMA = 1.2

DATE_SPREAD_DAYS = 45
_BASE_DATE = date.today() - timedelta(days=DATE_SPREAD_DAYS)

_INSERT_CHUNK_SIZE = 500

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

# Fixed by default so runs are reproducible; override with CORPUS_SEED to
# generate an independent corpus. Scores that only hold on one seed are
# overfitting, so the matcher is checked against several.
_SEED = int(os.environ.get("CORPUS_SEED", "20260823"))
_rng = random.Random(_SEED)


def random_amount_paise() -> int:
    amount = _rng.lognormvariate(_AMOUNT_MU, _AMOUNT_SIGMA)
    amount = max(AMOUNT_MIN_PAISE, min(AMOUNT_MAX_PAISE, amount))
    return round(amount)


def fee_and_tax(gross_paise: int) -> tuple[int, int, int]:
    fee = round(gross_paise * FEE_RATE)
    tax = round(fee * GST_RATE)
    net = gross_paise - fee - tax
    return fee, tax, net


def random_date(base: date = _BASE_DATE, spread_days: int = DATE_SPREAD_DAYS) -> date:
    return base + timedelta(days=_rng.randint(0, spread_days))


def gen_token(length: int = 6) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(_rng.choices(alphabet, k=length))


def new_truth_group() -> str:
    return f"tg_{uuid.uuid4().hex[:12]}"


def make_row(
    batch_id: str,
    source_kind: str,
    external_ref: str,
    amount_paise: int,
    *,
    fee_paise: int | None = None,
    tax_paise: int | None = None,
    net_paise: int | None = None,
    txn_date: date | None = None,
    value_date: date | None = None,
    truth_group: str | None = None,
    is_noise: bool = False,
    category: str = "",
) -> dict:
    if net_paise is None:
        net_paise = amount_paise - (fee_paise or 0) - (tax_paise or 0) if fee_paise else None
    return {
        "batch_id": batch_id,
        "source_kind": source_kind,
        "external_ref": external_ref,
        "amount_paise": amount_paise,
        "fee_paise": fee_paise,
        "tax_paise": tax_paise,
        "net_paise": net_paise,
        "txn_date": txn_date.isoformat() if txn_date else None,
        "value_date": value_date.isoformat() if value_date else None,
        "description": f"synthetic:{category}",
        "counterparty": None,
        "raw": {"synthetic": True, "category": category},
        "truth_group": truth_group,
        "is_noise": is_noise,
    }


# ---------------------------------------------------------------------
# Category generators — each returns (rows, truth_group_count)
# ---------------------------------------------------------------------

def gen_clean_3way(batch_id: str) -> list[dict]:
    tg = new_truth_group()
    gross = random_amount_paise()
    d = random_date()
    ref = gen_token()
    rows = []
    for source in ("razorpay", "bank", "ledger"):
        rows.append(make_row(batch_id, source, ref, gross, txn_date=d, truth_group=tg, category="clean_3way"))
    return rows


def gen_fee_tax_split(batch_id: str) -> list[dict]:
    tg = new_truth_group()
    gross = random_amount_paise()
    fee, tax, net = fee_and_tax(gross)
    d = random_date()
    ref = gen_token()
    return [
        make_row(batch_id, "razorpay", ref, gross, fee_paise=fee, tax_paise=tax, net_paise=net,
                 txn_date=d, truth_group=tg, category="fee_tax_split"),
        make_row(batch_id, "bank", ref, net, txn_date=d, truth_group=tg, category="fee_tax_split"),
        make_row(batch_id, "ledger", ref, gross, txn_date=d, truth_group=tg, category="fee_tax_split"),
    ]


def gen_value_date_drift(batch_id: str) -> list[dict]:
    tg = new_truth_group()
    gross = random_amount_paise()
    d = random_date()
    drift = _rng.randint(1, 3)
    ref = gen_token()
    return [
        make_row(batch_id, "razorpay", ref, gross, txn_date=d, truth_group=tg, category="value_date_drift"),
        make_row(batch_id, "ledger", ref, gross, txn_date=d, truth_group=tg, category="value_date_drift"),
        make_row(batch_id, "bank", ref, gross, txn_date=d + timedelta(days=drift), value_date=d,
                  truth_group=tg, category="value_date_drift"),
    ]


def gen_ref_format_drift(batch_id: str) -> list[dict]:
    tg = new_truth_group()
    gross = random_amount_paise()
    d = random_date()
    token = gen_token(5)
    razorpay_ref = f"pay_{token}"
    bank_ref = f"PAY{token.upper()}"
    ledger_ref = token[-3:]
    return [
        make_row(batch_id, "razorpay", razorpay_ref, gross, txn_date=d, truth_group=tg, category="ref_format_drift"),
        make_row(batch_id, "bank", bank_ref, gross, txn_date=d, truth_group=tg, category="ref_format_drift"),
        make_row(batch_id, "ledger", ledger_ref, gross, txn_date=d, truth_group=tg, category="ref_format_drift"),
    ]


def gen_many_to_one(batch_id: str, group_size: int, *, explicit_settlement_id: bool) -> list[dict]:
    """explicit_settlement_id mirrors what Razorpay's settlement recon API
    actually provides (payment_id <-> settlement_id): when True, every
    razorpay row and the bank row carry a shared raw['settlement_id'], so
    a matcher can resolve the group by that link alone rather than by
    searching. Half the groups get it, half don't — tier 4 needs both
    paths to be real, not just one of them."""
    tg = new_truth_group()
    rows = []
    total_net = 0
    max_event_date = _BASE_DATE
    settlement_id = f"setl_{gen_token()}" if explicit_settlement_id else None

    for _ in range(group_size):
        gross = random_amount_paise()
        fee, tax, net = fee_and_tax(gross)
        d = random_date()
        max_event_date = max(max_event_date, d)
        token = gen_token()
        rz_row = make_row(batch_id, "razorpay", f"pay_{token}", gross, fee_paise=fee, tax_paise=tax,
                           net_paise=net, txn_date=d, truth_group=tg, category="many_to_one")
        rz_row["raw"]["currency"] = "INR"
        if settlement_id:
            rz_row["raw"]["settlement_id"] = settlement_id
        rows.append(rz_row)
        rows.append(make_row(batch_id, "ledger", f"led_{token}", gross, txn_date=d, truth_group=tg,
                              category="many_to_one"))
        total_net += net

    settlement_date = max_event_date + timedelta(days=1)
    bank_row = make_row(batch_id, "bank", settlement_id or f"setl_{gen_token()}", total_net,
                         txn_date=settlement_date, truth_group=tg, category="many_to_one")
    bank_row["raw"]["currency"] = "INR"
    if settlement_id:
        bank_row["raw"]["settlement_id"] = settlement_id
    rows.append(bank_row)
    return rows


def gen_refund_chargeback(batch_id: str) -> list[dict]:
    tg = new_truth_group()
    gross = random_amount_paise()
    d = random_date()
    ref = gen_token()
    rows = [
        make_row(batch_id, "razorpay", ref, gross, txn_date=d, truth_group=tg, category="refund_chargeback"),
        make_row(batch_id, "bank", ref, gross, txn_date=d, truth_group=tg, category="refund_chargeback"),
        make_row(batch_id, "ledger", ref, gross, txn_date=d, truth_group=tg, category="refund_chargeback"),
    ]
    is_full = _rng.random() < 0.5
    refund_amount = gross if is_full else round(gross * _rng.uniform(0.2, 0.8))
    refund_date = d + timedelta(days=_rng.randint(1, 10))
    refund_ref = f"rfnd_{ref}"
    for source in ("razorpay", "bank", "ledger"):
        rows.append(make_row(batch_id, source, refund_ref, -refund_amount, txn_date=refund_date,
                              truth_group=tg, category="refund_chargeback"))
    return rows


def gen_missing_one_source(batch_id: str) -> list[dict]:
    tg = new_truth_group()
    gross = random_amount_paise()
    d = random_date()
    ref = gen_token()
    sources = ["razorpay", "bank", "ledger"]
    sources.remove(_rng.choice(sources))
    return [make_row(batch_id, s, ref, gross, txn_date=d, truth_group=tg, category="missing_one_source")
            for s in sources]


def gen_duplicate_one_source(batch_id: str) -> list[dict]:
    tg = new_truth_group()
    gross = random_amount_paise()
    d = random_date()
    ref = gen_token()
    rows = [make_row(batch_id, s, ref, gross, txn_date=d, truth_group=tg, category="duplicate_one_source")
            for s in ("razorpay", "bank", "ledger")]
    dup_source = _rng.choice(("razorpay", "bank", "ledger"))
    rows.append(make_row(batch_id, dup_source, ref, gross, txn_date=d, truth_group=tg,
                          category="duplicate_one_source"))
    return rows


def gen_genuine_noise(batch_id: str) -> list[dict]:
    source = _rng.choice(("razorpay", "bank", "ledger"))
    gross = random_amount_paise()
    d = random_date()
    ref = gen_token()
    return [make_row(batch_id, source, ref, gross, txn_date=d, truth_group=None, is_noise=True,
                      category="genuine_noise")]


# ---------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------

def _event_counts(num_events: int) -> dict[str, int]:
    counts = {cat: round(num_events * pct) for cat, pct in _PCTS.items()}
    drift = num_events - sum(counts.values())
    counts["clean_3way"] += drift
    return counts


def _many_to_one_groups(event_count: int) -> list[int]:
    groups = []
    remaining = event_count
    while remaining > 0:
        size = min(remaining, _rng.randint(MANY_TO_ONE_GROUP_MIN, MANY_TO_ONE_GROUP_MAX))
        if remaining - size < MANY_TO_ONE_GROUP_MIN and remaining - size > 0:
            size = remaining
        groups.append(size)
        remaining -= size
    return groups


def create_batch() -> str:
    res = db.run_with_retry(
        lambda: db.get_client()
        .table("batches")
        .insert({
            "label": "synthetic corpus",
            "period_start": _BASE_DATE.isoformat(),
            "period_end": date.today().isoformat(),
            "status": "complete",
        })
        .execute()
    )
    return res.data[0]["id"]


def insert_rows(rows: list[dict]) -> None:
    for i in range(0, len(rows), _INSERT_CHUNK_SIZE):
        chunk = rows[i:i + _INSERT_CHUNK_SIZE]
        db.run_with_retry(lambda c=chunk: db.get_client().table("txns").insert(c).execute())


def generate(batch_id: str) -> dict:
    counts = _event_counts(NUM_EVENTS)
    all_rows: list[dict] = []
    row_counts: Counter = Counter()
    group_counts: Counter = Counter()

    for _ in range(counts["clean_3way"]):
        all_rows += gen_clean_3way(batch_id)
    row_counts["clean_3way"] = counts["clean_3way"] * 3
    group_counts["clean_3way"] = counts["clean_3way"]

    for _ in range(counts["fee_tax_split"]):
        all_rows += gen_fee_tax_split(batch_id)
    row_counts["fee_tax_split"] = counts["fee_tax_split"] * 3
    group_counts["fee_tax_split"] = counts["fee_tax_split"]

    for _ in range(counts["value_date_drift"]):
        all_rows += gen_value_date_drift(batch_id)
    row_counts["value_date_drift"] = counts["value_date_drift"] * 3
    group_counts["value_date_drift"] = counts["value_date_drift"]

    for _ in range(counts["ref_format_drift"]):
        all_rows += gen_ref_format_drift(batch_id)
    row_counts["ref_format_drift"] = counts["ref_format_drift"] * 3
    group_counts["ref_format_drift"] = counts["ref_format_drift"]

    m2o_groups = _many_to_one_groups(counts["many_to_one"])
    for idx, size in enumerate(m2o_groups):
        group_rows = gen_many_to_one(batch_id, size, explicit_settlement_id=(idx % 2 == 0))
        all_rows += group_rows
        row_counts["many_to_one"] += len(group_rows)
    group_counts["many_to_one"] = len(m2o_groups)

    for _ in range(counts["refund_chargeback"]):
        all_rows += gen_refund_chargeback(batch_id)
    row_counts["refund_chargeback"] = counts["refund_chargeback"] * 6
    group_counts["refund_chargeback"] = counts["refund_chargeback"]

    for _ in range(counts["missing_one_source"]):
        all_rows += gen_missing_one_source(batch_id)
    row_counts["missing_one_source"] = counts["missing_one_source"] * 2
    group_counts["missing_one_source"] = counts["missing_one_source"]

    for _ in range(counts["duplicate_one_source"]):
        all_rows += gen_duplicate_one_source(batch_id)
    row_counts["duplicate_one_source"] = counts["duplicate_one_source"] * 4
    group_counts["duplicate_one_source"] = counts["duplicate_one_source"]

    for _ in range(counts["genuine_noise"]):
        all_rows += gen_genuine_noise(batch_id)
    row_counts["genuine_noise"] = counts["genuine_noise"]
    group_counts["genuine_noise"] = 0

    _rng.shuffle(all_rows)
    insert_rows(all_rows)

    expected_groups = sum(group_counts.values())
    return {
        "event_counts": counts,
        "row_counts": dict(row_counts),
        "group_counts": dict(group_counts),
        "many_to_one_group_sizes": m2o_groups,
        "total_rows": len(all_rows),
        "expected_groups": expected_groups,
    }


def print_summary(result: dict) -> None:
    counts = result["event_counts"]
    rows = result["row_counts"]
    groups = result["group_counts"]
    total_events = sum(counts.values())

    print("\n=== ground truth summary ===")
    header = f"{'category':<24}{'events':>8}{'% actual':>10}{'% target':>10}{'rows':>8}{'groups':>8}"
    print(header)
    print("-" * len(header))
    for cat, pct in _PCTS.items():
        n = counts[cat]
        actual_pct = 100 * n / total_events
        print(f"{cat:<24}{n:>8}{actual_pct:>9.1f}%{100 * pct:>9.1f}%{rows[cat]:>8}{groups[cat]:>8}")
    print("-" * len(header))
    print(f"{'TOTAL':<24}{total_events:>8}{'':>10}{'':>10}{result['total_rows']:>8}{result['expected_groups']:>8}")
    print(f"\nmany_to_one group sizes: {result['many_to_one_group_sizes']}")
    print(f"total rows written: {result['total_rows']}")
    print(f"expected distinct truth_group count: {result['expected_groups']}")


def verify(batch_id: str, result: dict) -> bool:
    total = db.run_with_retry(
        lambda: db.get_client().table("txns").select("id", count="exact").eq("batch_id", batch_id).execute()
    ).count

    non_noise_missing_tg = db.run_with_retry(
        lambda: db.get_client()
        .table("txns")
        .select("id", count="exact")
        .eq("batch_id", batch_id)
        .eq("is_noise", False)
        .is_("truth_group", "null")
        .execute()
    ).count

    # PostgREST caps a single response at 1000 rows, so page through when
    # the batch is larger than that.
    all_truth_groups: set[str] = set()
    page_size = 1000
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client()
            .table("txns")
            .select("truth_group")
            .eq("batch_id", batch_id)
            .order("id")
            .range(o, o + page_size - 1)
            .execute()
        ).data
        all_truth_groups.update(r["truth_group"] for r in page if r["truth_group"] is not None)
        if len(page) < page_size:
            break
        offset += page_size
    distinct_groups = len(all_truth_groups)

    print("\n=== GATE checks ===")
    ok_rowcount = total >= 1000
    print(f"rows in txns for batch: {total} (>= 1000: {ok_rowcount})")

    ok_no_missing_tg = non_noise_missing_tg == 0
    print(f"non-noise rows missing truth_group: {non_noise_missing_tg} (== 0: {ok_no_missing_tg})")

    ok_groups = distinct_groups == result["expected_groups"]
    print(f"distinct truth_group count: {distinct_groups} vs expected {result['expected_groups']} "
          f"(match: {ok_groups})")

    passed = ok_rowcount and ok_no_missing_tg and ok_groups
    print(f"\nGATE {'PASSED' if passed else 'FAILED'}")
    return passed


def main():
    batch_id = create_batch()
    print(f"batch_id: {batch_id}")
    result = generate(batch_id)
    print_summary(result)
    verify(batch_id, result)
    return batch_id


if __name__ == "__main__":
    main()

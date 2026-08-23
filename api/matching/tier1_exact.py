"""Tier 1 matcher: exact reference + amount + date.

Groups unmatched txns by identical (external_ref, amount_paise,
txn_date). Any group spanning two or more distinct source kinds becomes
a match_group at tier 1, strategy 'exact_ref_amount_date',
confidence 1.0.

=====================================================================
 THE MATCHER MUST NEVER READ truth_group OR is_noise.
=====================================================================
Those two columns are the answer key. If a matcher reads them — even
incidentally, even without using them — every precision/recall number
this project produces becomes meaningless, because the matcher would be
scored against data it was allowed to see.

This is enforced, not just documented: _MATCH_COLUMNS below is the
only column list this module ever selects, and _assert_no_truth_columns
fails loudly if a forbidden column ever appears in it or in a fetched
row. Keep it that way.
"""

import logging

from lib import db

logger = logging.getLogger("matching.tier1_exact")

TIER = 1
STRATEGY = "exact_ref_amount_date"
CONFIDENCE = 1.0

# Ground-truth columns. Never selected, never read, never referenced by
# any matcher.
FORBIDDEN_COLUMNS = frozenset({"truth_group", "is_noise"})

# The only columns tier 1 is allowed to see.
_MATCH_COLUMNS = ("id", "source_kind", "external_ref", "amount_paise", "txn_date")

_PAGE_SIZE = 1000
_INSERT_CHUNK_SIZE = 500

# Preferred primary role: the gateway is the system of record for a
# payment, so a razorpay row anchors the group when one is present.
_PRIMARY_PREFERENCE = ("razorpay", "bank", "ledger")


def _assert_no_truth_columns(columns) -> None:
    """Hard guard on evaluation integrity. Raises rather than warns."""
    leaked = FORBIDDEN_COLUMNS & set(columns)
    if leaked:
        raise AssertionError(
            f"matcher attempted to read ground-truth column(s): {sorted(leaked)}. "
            "A matcher that sees truth_group invalidates every score derived from it."
        )


_assert_no_truth_columns(_MATCH_COLUMNS)


def _page_txns(batch_id: str) -> list[dict]:
    """Fetch this batch's txns, selecting only _MATCH_COLUMNS."""
    select = ",".join(_MATCH_COLUMNS)
    rows: list[dict] = []
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client()
            .table("txns")
            .select(select)
            .eq("batch_id", batch_id)
            .order("id")
            .range(o, o + _PAGE_SIZE - 1)
            .execute()
        ).data
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    # Belt and braces: if the schema ever changes shape, catch a leak here
    # rather than silently scoring against contaminated results.
    if rows:
        _assert_no_truth_columns(rows[0].keys())
    return rows


def _already_matched_txn_ids(batch_id: str) -> set[str]:
    """txn ids already claimed by a match_group in this batch, so re-runs
    and later tiers only consider what is still unmatched."""
    group_ids: list[str] = []
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client()
            .table("match_groups")
            .select("id")
            .eq("batch_id", batch_id)
            .order("id")
            .range(o, o + _PAGE_SIZE - 1)
            .execute()
        ).data
        group_ids.extend(r["id"] for r in page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    if not group_ids:
        return set()

    matched: set[str] = set()
    for i in range(0, len(group_ids), 100):
        chunk = group_ids[i:i + 100]
        offset = 0
        while True:
            page = db.run_with_retry(
                lambda c=chunk, o=offset: db.get_client()
                .table("match_members")
                .select("txn_id")
                .in_("match_group_id", c)
                .order("id")
                .range(o, o + _PAGE_SIZE - 1)
                .execute()
            ).data
            matched.update(r["txn_id"] for r in page)
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
    return matched


def _group_key(row: dict) -> tuple:
    return (row["external_ref"], row["amount_paise"], row["txn_date"])


def _order_members(rows: list[dict]) -> list[dict]:
    """Deterministic ordering so the primary role is stable across runs."""
    def sort_key(r):
        try:
            rank = _PRIMARY_PREFERENCE.index(r["source_kind"])
        except ValueError:
            rank = len(_PRIMARY_PREFERENCE)
        return (rank, str(r["id"]))
    return sorted(rows, key=sort_key)


def _write_audit(batch_id: str, action: str, detail: dict) -> None:
    db.run_with_retry(
        lambda: db.get_client()
        .table("audit_log")
        .insert({
            "batch_id": batch_id,
            "actor": "matcher",
            "step": "tier1_exact",
            "action": action,
            "detail": detail,
        })
        .execute()
    )


def run_tier1(batch_id: str) -> dict:
    """Run tier 1 exact matching over a batch. Returns a summary dict,
    also written to audit_log."""
    _write_audit(batch_id, "start", {"tier": TIER, "strategy": STRATEGY})

    all_rows = _page_txns(batch_id)
    already_matched = _already_matched_txn_ids(batch_id)
    unmatched = [r for r in all_rows if r["id"] not in already_matched]

    logger.info("batch %s: %d txns, %d unmatched", batch_id, len(all_rows), len(unmatched))

    # Bucket by (ref, amount, date). Rows with no reference can't be
    # matched by this strategy at all.
    buckets: dict[tuple, list[dict]] = {}
    no_ref = 0
    for row in unmatched:
        if not row["external_ref"]:
            no_ref += 1
            continue
        buckets.setdefault(_group_key(row), []).append(row)

    # A group qualifies only if it spans 2+ distinct source kinds.
    qualifying = [
        rows for rows in buckets.values()
        if len({r["source_kind"] for r in rows}) >= 2
    ]

    group_payloads = [
        {
            "batch_id": batch_id,
            "tier": TIER,
            "strategy": STRATEGY,
            "confidence": CONFIDENCE,
            "member_count": len(rows),
            # Exact match: every member's amount is identical by
            # construction, so there is no variance to record.
            "total_variance_paise": 0,
        }
        for rows in qualifying
    ]

    members_written = 0
    for i in range(0, len(group_payloads), _INSERT_CHUNK_SIZE):
        payload_chunk = group_payloads[i:i + _INSERT_CHUNK_SIZE]
        rows_chunk = qualifying[i:i + _INSERT_CHUNK_SIZE]

        inserted = db.run_with_retry(
            lambda c=payload_chunk: db.get_client().table("match_groups").insert(c).execute()
        ).data
        if len(inserted) != len(rows_chunk):
            raise RuntimeError(f"inserted {len(inserted)} match_groups for {len(rows_chunk)} groups")

        member_payload = []
        for group, rows in zip(inserted, rows_chunk):
            for position, member in enumerate(_order_members(rows)):
                member_payload.append({
                    "match_group_id": group["id"],
                    "txn_id": member["id"],
                    "role": "primary" if position == 0 else "counterpart",
                })

        for j in range(0, len(member_payload), _INSERT_CHUNK_SIZE):
            db.run_with_retry(
                lambda c=member_payload[j:j + _INSERT_CHUNK_SIZE]:
                db.get_client().table("match_members").insert(c).execute()
            )
        members_written += len(member_payload)

    matched_txn_count = sum(len(rows) for rows in qualifying)
    source_kind_spread: dict[int, int] = {}
    for rows in qualifying:
        n = len({r["source_kind"] for r in rows})
        source_kind_spread[n] = source_kind_spread.get(n, 0) + 1

    summary = {
        "tier": TIER,
        "strategy": STRATEGY,
        "confidence": CONFIDENCE,
        "txns_total": len(all_rows),
        "txns_considered": len(unmatched),
        "txns_without_reference": no_ref,
        "groups_created": len(qualifying),
        "txns_matched": matched_txn_count,
        "txns_remaining": len(unmatched) - matched_txn_count,
        "match_members_written": members_written,
        "groups_by_distinct_source_kinds": source_kind_spread,
    }

    _write_audit(batch_id, "finish", summary)
    return summary

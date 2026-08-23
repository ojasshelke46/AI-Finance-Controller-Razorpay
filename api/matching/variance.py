"""Populate the variance queue after all four matching tiers have run.

Two kinds of variance row:

  1. Unmatched txns — every txn not claimed by any match_group. One row
     each: txn_id set, match_group_id null, variance_paise equal to the
     txn's full (signed) amount_paise.

  2. Unbalanced matched groups — a group whose members do not net to
     zero once known fee/tax are accounted for. One row each:
     match_group_id set, txn_id null, variance_paise equal to that
     residual.

     "Do not net to zero after accounting for known fee and tax" is
     exactly what tier 3/4 already compute as
     variance_components['residual_paise'] — the leftover AFTER fee and
     tax explain the gross/net gap, not the raw gap itself (a tier-3
     group with fee=238, tax=43 and a perfectly-explained net has
     total_variance_paise=281 but residual_paise=0 — it's fully
     explained, so it gets no row). Tiers 1/2 never set
     variance_components at all; their total_variance_paise is always
     0 (they only ever link identical amounts), so they never
     contribute a row here either. A group is "balanced" iff this
     residual is 0.

Tier 4 already writes its own txn-level variance rows for bank credits
it couldn't resolve (category 'many_to_one_unresolved') — those are
kind-1 rows in every respect (txn_id set, match_group_id null, full
amount), just with a more specific category than this module's generic
classifier would produce. This module skips txns that already have an
open variance row rather than duplicating them, but still counts them
toward the reconciliation total below — the money's accounted for
exactly once regardless of which step logged it.

Categories are assigned from cheap, deterministic signals only —
no model involvement:
  duplicate_suspected    another txn shares (source_kind, external_ref,
                         amount_paise) — a literal duplicate key exists
                         somewhere in the batch.
  orphan_source_missing  no txn from ANY other source_kind in the whole
                         batch shares even a fragment of this reference
                         — the counterpart source doesn't just fail to
                         match, it isn't there at all.
  residual_rounding      |variance_paise| < ROUNDING_THRESHOLD_PAISE.
  timing_open            the relevant date is within TIMING_RECENT_DAYS
                         of today — plausibly just not settled yet.
  unclassified           none of the above.

Checked in that order (most specific/certain signal first). Every row
starts status='open'.

=====================================================================
 THIS MODULE MUST NEVER READ truth_group OR is_noise.
=====================================================================
Same rule as every matching tier — a variance classifier that can see
the answer key is exactly as compromised as a matcher that can.
"""

import logging
from collections import defaultdict
from datetime import date

from lib import db
from matching.tier2_normalised import normalize_ref

logger = logging.getLogger("matching.variance")

CAT_DUPLICATE = "duplicate_suspected"
CAT_ORPHAN = "orphan_source_missing"
CAT_ROUNDING = "residual_rounding"
CAT_TIMING = "timing_open"
CAT_UNCLASSIFIED = "unclassified"

ROUNDING_THRESHOLD_PAISE = 100
TIMING_RECENT_DAYS = 5

FORBIDDEN_COLUMNS = frozenset({"truth_group", "is_noise"})
_TXN_COLUMNS = ("id", "source_kind", "external_ref", "amount_paise", "txn_date")
_PAGE_SIZE = 1000
_INSERT_CHUNK_SIZE = 500


def _assert_no_truth_columns(columns) -> None:
    leaked = FORBIDDEN_COLUMNS & set(columns)
    if leaked:
        raise AssertionError(
            f"variance classifier attempted to read ground-truth column(s): {sorted(leaked)}. "
            "This invalidates every score derived from it, same as a matcher reading them."
        )


_assert_no_truth_columns(_TXN_COLUMNS)


def group_residual(group: dict) -> int:
    """The amount left over after known fee/tax explain what they can.
    0 for tiers 1/2 (identical-amount matches, nothing to explain) and
    for any tier-3/4 group whose fee+tax fully accounts for the gap."""
    vc = group.get("variance_components")
    if vc and vc.get("residual_paise") is not None:
        return vc["residual_paise"]
    return group.get("total_variance_paise") or 0


def _page(table: str, columns: str, batch_id: str, **filters) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        q = db.get_client().table(table).select(columns).eq("batch_id", batch_id)
        for k, v in filters.items():
            q = q.eq(k, v)

        def _exec(qq=q, o=offset):
            return qq.order("id").range(o, o + _PAGE_SIZE - 1).execute()

        page = db.run_with_retry(_exec).data
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return rows


def _fetch_all_txns(batch_id: str) -> list[dict]:
    rows = _page("txns", ",".join(_TXN_COLUMNS), batch_id)
    if rows:
        _assert_no_truth_columns(rows[0].keys())
    return rows


def _fetch_groups(batch_id: str) -> list[dict]:
    return _page("match_groups", "id,tier,total_variance_paise,variance_components,member_count", batch_id)


def _fetch_group_members(batch_id: str, group_ids: list[str]) -> dict[str, list[str]]:
    """group_id -> [txn_id, ...]"""
    members: dict[str, list[str]] = defaultdict(list)
    for i in range(0, len(group_ids), 100):
        chunk = group_ids[i:i + 100]
        offset = 0
        while True:
            page = db.run_with_retry(
                lambda c=chunk, o=offset: db.get_client().table("match_members")
                .select("match_group_id,txn_id").in_("match_group_id", c).order("id")
                .range(o, o + _PAGE_SIZE - 1).execute()
            ).data
            for r in page:
                members[r["match_group_id"]].append(r["txn_id"])
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
    return members


def _existing_variance_txn_ids(batch_id: str) -> set[str]:
    rows = _page("variances", "txn_id", batch_id)
    return {r["txn_id"] for r in rows if r["txn_id"]}


def _build_ref_index(txns: list[dict]) -> dict[tuple, list[dict]]:
    """(source_kind, external_ref) -> rows sharing it, for duplicate
    detection. Every row in the batch, regardless of match status —
    a duplicate posting is a duplicate whether or not it happened to
    end up matched."""
    idx: dict[tuple, list[dict]] = defaultdict(list)
    for t in txns:
        if t["external_ref"]:
            idx[(t["source_kind"], t["external_ref"])].append(t)
    return idx


def _build_sibling_index(txns: list[dict]) -> dict[str, set[str]]:
    """normalised-ref-key -> set of source_kinds that have ANY txn
    carrying it, across the whole batch. Used for the orphan check: if
    no OTHER source ever produced anything resembling this reference,
    the counterpart wasn't just missed by matching — it doesn't exist."""
    idx: dict[str, set[str]] = defaultdict(set)
    for t in txns:
        if not t["external_ref"]:
            continue
        full, last8 = normalize_ref(t["external_ref"])
        idx[full].add(t["source_kind"])
        idx[last8].add(t["source_kind"])
    return idx


def classify_unmatched(txn: dict, ref_index: dict, sibling_index: dict, today: date) -> str:
    key = (txn["source_kind"], txn["external_ref"])
    twins = ref_index.get(key, [])
    if any(t["id"] != txn["id"] and t["amount_paise"] == txn["amount_paise"] for t in twins):
        return CAT_DUPLICATE

    if txn["external_ref"]:
        full, last8 = normalize_ref(txn["external_ref"])
        other_sources = (sibling_index.get(full, set()) | sibling_index.get(last8, set())) - {txn["source_kind"]}
        if not other_sources:
            return CAT_ORPHAN

    if abs(txn["amount_paise"]) < ROUNDING_THRESHOLD_PAISE:
        return CAT_ROUNDING

    if txn["txn_date"] and (today - date.fromisoformat(txn["txn_date"])).days <= TIMING_RECENT_DAYS:
        return CAT_TIMING

    return CAT_UNCLASSIFIED


def classify_group(residual: int, member_rows: list[dict], today: date) -> str:
    if abs(residual) < ROUNDING_THRESHOLD_PAISE:
        return CAT_ROUNDING

    dates = [r["txn_date"] for r in member_rows if r.get("txn_date")]
    if dates:
        most_recent = max(date.fromisoformat(d) for d in dates)
        if (today - most_recent).days <= TIMING_RECENT_DAYS:
            return CAT_TIMING

    return CAT_UNCLASSIFIED


def _write_audit(batch_id: str, action: str, detail: dict) -> None:
    db.run_with_retry(
        lambda: db.get_client().table("audit_log").insert({
            "batch_id": batch_id, "actor": "scorer", "step": "variance_queue",
            "action": action, "detail": detail,
        }).execute()
    )


def _insert_variances(rows: list[dict]) -> None:
    for i in range(0, len(rows), _INSERT_CHUNK_SIZE):
        chunk = rows[i:i + _INSERT_CHUNK_SIZE]
        db.run_with_retry(lambda c=chunk: db.get_client().table("variances").insert(c).execute())


def populate_variance_queue(batch_id: str) -> dict:
    """Runs after all four matching tiers. Idempotent with respect to
    txns tier 4 already logged (skips, doesn't duplicate); re-running
    against groups will duplicate group-residual rows, so this is meant
    to run once per batch after matching completes."""
    _write_audit(batch_id, "start", {})
    today = date.today()

    all_txns = _fetch_all_txns(batch_id)
    txn_by_id = {t["id"]: t for t in all_txns}

    groups = _fetch_groups(batch_id)
    group_ids = [g["id"] for g in groups]
    members_by_group = _fetch_group_members(batch_id, group_ids)

    matched_txn_ids: set[str] = set()
    for ids in members_by_group.values():
        matched_txn_ids.update(ids)

    already_queued = _existing_variance_txn_ids(batch_id)

    ref_index = _build_ref_index(all_txns)
    sibling_index = _build_sibling_index(all_txns)

    # ---- kind 1: unmatched txns ----
    unmatched_rows = []
    skipped_already_queued = 0
    for t in all_txns:
        if t["id"] in matched_txn_ids:
            continue
        if t["id"] in already_queued:
            skipped_already_queued += 1
            continue
        category = classify_unmatched(t, ref_index, sibling_index, today)
        unmatched_rows.append({
            "batch_id": batch_id,
            "match_group_id": None,
            "txn_id": t["id"],
            "variance_paise": t["amount_paise"],
            "category": category,
            "status": "open",
            "explanation": f"unmatched {t['source_kind']} txn, no match_group",
        })

    # ---- kind 2: unbalanced groups ----
    group_rows = []
    for g in groups:
        residual = group_residual(g)
        if residual == 0:
            continue
        member_ids = members_by_group.get(g["id"], [])
        member_rows = [txn_by_id[tid] for tid in member_ids if tid in txn_by_id]
        category = classify_group(residual, member_rows, today)
        group_rows.append({
            "batch_id": batch_id,
            "match_group_id": g["id"],
            "txn_id": None,
            "variance_paise": residual,
            "category": category,
            "status": "open",
            "explanation": f"tier {g['tier']} group, {g['member_count']} members, residual after fee/tax",
        })

    _insert_variances(unmatched_rows)
    _insert_variances(group_rows)

    category_counts: dict[str, int] = defaultdict(int)
    for r in unmatched_rows + group_rows:
        category_counts[r["category"]] += 1

    summary = {
        "unmatched_rows_written": len(unmatched_rows),
        "unmatched_rows_already_queued_by_tier4": skipped_already_queued,
        "unbalanced_group_rows_written": len(group_rows),
        "total_unmatched_value_paise": sum(r["variance_paise"] for r in unmatched_rows),
        "total_residual_value_paise": sum(r["variance_paise"] for r in group_rows),
        "category_counts": dict(category_counts),
    }
    _write_audit(batch_id, "finish", summary)
    return summary

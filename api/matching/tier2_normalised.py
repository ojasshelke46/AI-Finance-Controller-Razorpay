"""Tier 2 matcher: normalised reference + windowed amount/date.

Runs only on txns not already claimed by a match_group (any tier).
References are normalised before comparison (case, punctuation, common
prefixes, leading zeros) and additionally indexed by their last 8
characters, since bank narrations frequently truncate a longer
reference down to a tail fragment.

Two rows from different source kinds are linked when their normalised
references agree (full match, or last-8 fallback) AND their amounts are
within 1 paise AND their dates are within a 3-day window. Linked rows
are clustered by connected components (a link is not necessarily
transitive-by-construction otherwise), and any resulting cluster
spanning 2+ source kinds becomes a tier-2 match_group.

Confidence starts at 0.95 and drops 0.05 for each dimension a group
actually needed loosening on:
  - reference: linked via last-8 fallback rather than an identical
    normalised reference
  - amount:    members disagree by 1 paise rather than being identical
  - date:      members disagree by 1-3 days rather than being identical

=====================================================================
 THE MATCHER MUST NEVER READ truth_group OR is_noise.
=====================================================================
Same rule as tier 1 — those columns are the answer key, and evaluation
is meaningless the moment a matcher can see it, even in passing. Enforced
the same way: _MATCH_COLUMNS is the only column list ever selected, and
_assert_no_truth_columns raises if a forbidden column shows up in it or
in a fetched row.
"""

import logging
from collections import defaultdict
from datetime import date

from lib import db

logger = logging.getLogger("matching.tier2_normalised")

TIER = 2
STRATEGY = "normalised_ref_windowed"
BASE_CONFIDENCE = 0.95
CONFIDENCE_STEP = 0.05

AMOUNT_TOLERANCE_PAISE = 1
DATE_WINDOW_DAYS = 3
LAST_N_CHARS = 8

# Stripped from the start of a normalised reference, longest first so
# "PAYMENT" isn't chewed down to "PAY" + leftover.
#
# LED / VCH / JV are ledger-side voucher prefixes. Without them a ledger
# row's "led_Nx8Kd" normalises to LEDNX8KD while the gateway's
# "pay_Nx8Kd" normalises to NX8KD, so the two sides of the *same*
# payment never land in the same bucket — measured as a large recall
# loss on every multi-source event whose ledger leg carries a voucher
# prefix.
_PREFIXES = sorted(
    ["PAYMENT", "NEFT", "IMPS", "TXN", "REF", "PAY", "LED", "VCH", "JV"],
    key=len,
    reverse=True,
)

# A bank narration or ledger voucher often truncates a reference to a
# short tail ("8Kd" for "pay_Nx8Kd"). LAST_N_CHARS can't bridge that: a
# 3-char ref and a 5-char ref have different last-8 keys. So refs at or
# below this length additionally bucket on their last SHORT_REF_CHARS.
# Deliberately narrow — it only widens matching for refs that are
# already too short to key on normally, and the amount/date checks still
# have to pass on top.
SHORT_REF_MAX_LEN = 4
SHORT_REF_CHARS = 3

# Ground-truth columns. Never selected, never read, never referenced by
# any matcher.
FORBIDDEN_COLUMNS = frozenset({"truth_group", "is_noise"})

_MATCH_COLUMNS = ("id", "source_kind", "external_ref", "amount_paise", "txn_date")

_PAGE_SIZE = 1000
_INSERT_CHUNK_SIZE = 500

_PRIMARY_PREFERENCE = ("razorpay", "bank", "ledger")


def _assert_no_truth_columns(columns) -> None:
    leaked = FORBIDDEN_COLUMNS & set(columns)
    if leaked:
        raise AssertionError(
            f"matcher attempted to read ground-truth column(s): {sorted(leaked)}. "
            "A matcher that sees truth_group invalidates every score derived from it."
        )


_assert_no_truth_columns(_MATCH_COLUMNS)


def normalize_ref(raw: str) -> tuple[str, str]:
    """Returns (full_normalized, last8_key).

    Uppercase -> strip non-alphanumeric -> strip a leading common prefix
    (repeatedly, in case more than one is stacked) -> strip leading
    zeros. last8_key is the trailing LAST_N_CHARS of the result (the
    whole string if shorter), used as a fallback index for truncated
    bank narrations.
    """
    s = "".join(ch for ch in raw.upper() if ch.isalnum())

    changed = True
    while changed:
        changed = False
        for prefix in _PREFIXES:
            if s.startswith(prefix) and len(s) > len(prefix):
                s = s[len(prefix):]
                changed = True
                break

    stripped = s.lstrip("0")
    s = stripped if stripped else s

    return s, s[-LAST_N_CHARS:]


def _page_txns(batch_id: str) -> list[dict]:
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
    if rows:
        _assert_no_truth_columns(rows[0].keys())
    return rows


def _already_matched_txn_ids(batch_id: str) -> set[str]:
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


class _UnionFind:
    def __init__(self, ids):
        self.parent = {i: i for i in ids}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _annotate(row: dict) -> None:
    """Sets row['_full'] / row['_last8'], or None/None if there's no
    reference to normalise. Called once per row for the whole batch, so
    both the clustering pass and the existing-group attach pass (which
    needs normalised refs on rows tier1 already claimed) see the same
    values without recomputing."""
    if row["external_ref"]:
        row["_full"], row["_last8"] = normalize_ref(row["external_ref"])
    else:
        row["_full"], row["_last8"] = None, None


def _refs_link(a: dict, b: dict) -> bool:
    """Whether two normalised references may be linked at all.

    Shared buckets are a cheap prefilter, not the decision — the "short"
    bucket deliberately over-collects, so this is where an actual rule is
    applied:

      - identical normalised refs, or identical last-8 tails: link.
      - otherwise, allow a short-tail link ONLY when at least one ref is
        short enough that it plausibly IS a truncation, and the shorter
        ref is a genuine suffix of the longer one. "8KD" vs "NX8KD"
        links; "8KD" vs "QQ8KD" also links (both are suffixes), but two
        unrelated long refs that merely happen to share three trailing
        characters do not.
    """
    full_a, full_b = a["_full"], b["_full"]
    if full_a is None or full_b is None:
        return False
    if full_a == full_b or a["_last8"] == b["_last8"]:
        return True

    short, long = (full_a, full_b) if len(full_a) <= len(full_b) else (full_b, full_a)
    if len(short) > SHORT_REF_MAX_LEN:
        return False
    return len(short) >= SHORT_REF_CHARS and long.endswith(short)


def _cluster(rows: list[dict]) -> list[list[dict]]:
    """Bucket rows by normalised-ref (full and last8), check amount/date
    windows within each bucket, and union linked rows into clusters.
    Assumes _annotate() has already run on every row."""
    by_id = {r["id"]: r for r in rows}
    uf = _UnionFind(by_id.keys())

    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        if row["_full"] is None:
            continue
        full, last8 = row["_full"], row["_last8"]
        buckets[("full", full)].append(row)
        if last8 != full:
            buckets[("last8", last8)].append(row)
        # Short refs additionally bucket on a shorter tail, so a
        # truncated ledger/bank reference can still meet its full-length
        # counterpart. Every other row joins this bucket too (it costs
        # nothing but a lookup), but only pairs where at least one side
        # is genuinely short are allowed to link — see _short_ref_pair.
        if len(full) >= SHORT_REF_CHARS:
            buckets[("short", full[-SHORT_REF_CHARS:])].append(row)

    considered_edges: set[tuple] = set()
    for bucket_rows in buckets.values():
        if len(bucket_rows) < 2:
            continue
        for i in range(len(bucket_rows)):
            for j in range(i + 1, len(bucket_rows)):
                a, b = bucket_rows[i], bucket_rows[j]
                if a["id"] == b["id"] or a["source_kind"] == b["source_kind"]:
                    continue
                edge = tuple(sorted((a["id"], b["id"])))
                if edge in considered_edges:
                    continue
                considered_edges.add(edge)

                if not _refs_link(a, b):
                    continue
                if abs(a["amount_paise"] - b["amount_paise"]) > AMOUNT_TOLERANCE_PAISE:
                    continue
                if not a["txn_date"] or not b["txn_date"]:
                    continue
                d1, d2 = date.fromisoformat(a["txn_date"]), date.fromisoformat(b["txn_date"])
                if abs((d1 - d2).days) > DATE_WINDOW_DAYS:
                    continue

                uf.union(a["id"], b["id"])

    clusters: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["_full"] is None:  # no external_ref, never entered a bucket
            continue
        clusters[uf.find(row["id"])].append(row)

    return [members for members in clusters.values() if len(members) >= 2]


def _group_confidence(members: list[dict]) -> tuple[float, int]:
    """0.95 minus 0.05 per dimension the group needed loosening on.
    Also returns total_variance_paise (max - min amount in the group)."""
    fulls = {m["_full"] for m in members}
    amounts = {m["amount_paise"] for m in members}
    dates = {m["txn_date"] for m in members}

    loosened = sum([len(fulls) > 1, len(amounts) > 1, len(dates) > 1])
    confidence = round(BASE_CONFIDENCE - CONFIDENCE_STEP * loosened, 2)
    variance = max(amounts) - min(amounts)
    return confidence, variance


def _order_members(rows: list[dict]) -> list[dict]:
    def sort_key(r):
        try:
            rank = _PRIMARY_PREFERENCE.index(r["source_kind"])
        except ValueError:
            rank = len(_PRIMARY_PREFERENCE)
        return (rank, str(r["id"]))
    return sorted(rows, key=sort_key)


def _fetch_groups_with_members(batch_id: str, by_id: dict[str, dict]) -> list[dict]:
    """Every match_group for this batch (any tier), each carrying its
    resolved member rows (already-annotated with _full/_last8)."""
    group_rows: list[dict] = []
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client().table("match_groups")
            .select("id,tier,confidence,member_count")
            .eq("batch_id", batch_id)
            .order("id")
            .range(o, o + _PAGE_SIZE - 1).execute()
        ).data
        group_rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    if not group_rows:
        return []

    group_ids = [g["id"] for g in group_rows]
    members_by_group: dict[str, list[str]] = defaultdict(list)
    for i in range(0, len(group_ids), 100):
        chunk = group_ids[i:i + 100]
        offset = 0
        while True:
            page = db.run_with_retry(
                lambda c=chunk, o=offset: db.get_client().table("match_members")
                .select("match_group_id,txn_id")
                .in_("match_group_id", c)
                .order("id")
                .range(o, o + _PAGE_SIZE - 1).execute()
            ).data
            for r in page:
                members_by_group[r["match_group_id"]].append(r["txn_id"])
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

    groups = []
    for g in group_rows:
        member_rows = [by_id[tid] for tid in members_by_group.get(g["id"], []) if tid in by_id]
        if member_rows:
            groups.append({**g, "members": member_rows})
    return groups


def _matches_group(row: dict, group_members: list[dict]) -> bool:
    """Same ref/amount/date rule as clustering, checked against a
    group's existing members instead of another loose row."""
    if row["_full"] is None or not row["txn_date"]:
        return False
    if row["source_kind"] in {m["source_kind"] for m in group_members}:
        return False
    row_date = date.fromisoformat(row["txn_date"])
    for m in group_members:
        if m["_full"] is None or not m["txn_date"]:
            continue
        if not _refs_link(row, m):
            continue
        if abs(row["amount_paise"] - m["amount_paise"]) > AMOUNT_TOLERANCE_PAISE:
            continue
        if abs((row_date - date.fromisoformat(m["txn_date"])).days) > DATE_WINDOW_DAYS:
            continue
        return True
    return False


def _attach_to_existing_groups(remaining: list[dict], groups: list[dict]) -> dict:
    """For each still-unmatched row, attach it to the one existing
    match_group (any tier) it fits — if exactly one such group exists.
    A row fitting 2+ groups is left unmatched rather than guessed at; a
    wrong attach would corrupt an otherwise-clean group.

    This is what closes cases like value_date_drift: tier1 already
    grouped two sources on an exact date match, leaving the drifted
    third source with no unmatched partner to link against unless
    something is allowed to extend existing groups, not just form new
    ones. Attaching recomputes that group's confidence over its full
    (now larger) membership — a tier-1 group that gains a date-drifted
    member honestly drops from 1.0, it doesn't stay there."""
    attached_txn_ids: set[str] = set()
    ambiguous = 0
    groups_touched: dict[str, dict] = {}

    for row in remaining:
        candidates = [g for g in groups if _matches_group(row, g["members"])]
        if len(candidates) == 0:
            continue
        if len(candidates) > 1:
            ambiguous += 1
            continue

        group = candidates[0]
        db.run_with_retry(
            lambda gid=group["id"], tid=row["id"]: db.get_client().table("match_members")
            .insert({"match_group_id": gid, "txn_id": tid, "role": "counterpart"}).execute()
        )
        attached_txn_ids.add(row["id"])
        group["members"].append(row)
        groups_touched[group["id"]] = group

    for group in groups_touched.values():
        confidence, variance = _group_confidence(group["members"])
        db.run_with_retry(
            lambda gid=group["id"], conf=confidence, mc=len(group["members"]), var=variance:
            db.get_client().table("match_groups").update({
                "confidence": conf, "member_count": mc, "total_variance_paise": var,
            }).eq("id", gid).execute()
        )

    return {
        "txns_attached": len(attached_txn_ids),
        "groups_enriched": len(groups_touched),
        "ambiguous_skipped": ambiguous,
        "attached_txn_ids": attached_txn_ids,
    }


def _write_audit(batch_id: str, action: str, detail: dict) -> None:
    db.run_with_retry(
        lambda: db.get_client()
        .table("audit_log")
        .insert({
            "batch_id": batch_id,
            "actor": "matcher",
            "step": "tier2_normalised",
            "action": action,
            "detail": detail,
        })
        .execute()
    )


def run_tier2(batch_id: str) -> dict:
    _write_audit(batch_id, "start", {"tier": TIER, "strategy": STRATEGY})

    all_rows = _page_txns(batch_id)
    for row in all_rows:
        _annotate(row)
    by_id = {r["id"]: r for r in all_rows}

    already_matched = _already_matched_txn_ids(batch_id)
    unmatched = [r for r in all_rows if r["id"] not in already_matched]
    unmatched_before = len(unmatched)

    no_ref = sum(1 for r in unmatched if not r["external_ref"])

    clusters = _cluster(unmatched)
    qualifying = [c for c in clusters if len({m["source_kind"] for m in c}) >= 2]

    group_payloads = []
    for members in qualifying:
        confidence, variance = _group_confidence(members)
        group_payloads.append({
            "batch_id": batch_id,
            "tier": TIER,
            "strategy": STRATEGY,
            "confidence": confidence,
            "member_count": len(members),
            "total_variance_paise": variance,
        })

    members_written = 0
    confidence_histogram: dict[float, int] = {}
    for i in range(0, len(group_payloads), _INSERT_CHUNK_SIZE):
        payload_chunk = group_payloads[i:i + _INSERT_CHUNK_SIZE]
        rows_chunk = qualifying[i:i + _INSERT_CHUNK_SIZE]

        inserted = db.run_with_retry(
            lambda c=payload_chunk: db.get_client().table("match_groups").insert(c).execute()
        ).data
        if len(inserted) != len(rows_chunk):
            raise RuntimeError(f"inserted {len(inserted)} match_groups for {len(rows_chunk)} groups")

        member_payload = []
        for group, members in zip(inserted, rows_chunk):
            confidence_histogram[group["confidence"]] = confidence_histogram.get(group["confidence"], 0) + 1
            for position, member in enumerate(_order_members(members)):
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

    matched_txn_count = sum(len(c) for c in qualifying)
    newly_matched_ids = {row["id"] for members in qualifying for row in members}
    remaining = [r for r in unmatched if r["id"] not in newly_matched_ids]

    # Phase 2: attach whatever's still unmatched to an existing group
    # (any tier) it fits, rather than only forming brand-new groups.
    existing_groups = _fetch_groups_with_members(batch_id, by_id)
    attach_result = _attach_to_existing_groups(remaining, existing_groups)

    matched_txn_count += attach_result["txns_attached"]
    members_written += attach_result["txns_attached"]

    summary = {
        "tier": TIER,
        "strategy": STRATEGY,
        "unmatched_before": unmatched_before,
        "txns_without_reference": no_ref,
        "groups_created": len(qualifying),
        "groups_enriched": attach_result["groups_enriched"],
        "txns_attached_to_existing_groups": attach_result["txns_attached"],
        "ambiguous_skipped": attach_result["ambiguous_skipped"],
        "txns_matched": matched_txn_count,
        "unmatched_after": unmatched_before - matched_txn_count,
        "match_members_written": members_written,
        "confidence_histogram": confidence_histogram,
    }

    _write_audit(batch_id, "finish", summary)
    return summary

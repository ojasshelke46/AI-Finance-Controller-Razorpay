"""Tier 4 matcher: aggregate settlement matching (many-to-one).

Runs on whatever tiers 1-3 left unmatched.

The problem: one bank credit is a Razorpay settlement covering N
individual gateway payments net of fees. Brute-force subset-sum over N
unmatched payments is combinatorial and will hang, so this tier never
does that. Two paths instead:

  1. Explicit settlement_id linkage (the correct primary path). If a
     gateway row's raw payload carries a settlement_id that also
     appears on an unmatched bank row, trust it — group by that id
     directly, no search. This is what Razorpay's settlement recon API
     (payment_id <-> settlement_id) actually gives you when ingested;
     it should resolve most real cases outright.

  2. For whatever has no explicit link: constrain hard before
     searching. Candidates must fall inside the settlement's date
     window, share currency, and carry fee data (a row that was never
     captured/settled can't be part of any settlement). Truncate to
     MAX_CANDIDATES_PER_TARGET, then run an exact bounded subset-sum
     (see greedy_subset_sum) — bounded not by an iteration cap but by
     the DP's bitset width (MAX_DP_TARGET_PAISE), so it can't blow up
     combinatorially the way brute-force enumeration would. If no exact
     or unambiguous near-tolerance sum exists, abandon that target and
     write it to the variances table (status='open') instead of
     guessing.

A subset's contribution is its NET amount (gross - fee - tax) — what
actually gets credited to the bank — never gross. All arithmetic is
integer paise.

=====================================================================
 THE MATCHER MUST NEVER READ truth_group OR is_noise.
=====================================================================
Same rule and enforcement as tiers 1-3.
"""

import logging
import time
from collections import defaultdict
from datetime import date, timedelta

from lib import db

logger = logging.getLogger("matching.tier4_aggregate")

TIER = 4
STRATEGY = "aggregate_settlement"

CONFIDENCE_SETTLEMENT_ID = 0.9
CONFIDENCE_SEARCH = 0.75

SUM_TOLERANCE_PAISE = 5
# A genuine settlement sum is exact integer arithmetic (net = gross -
# fee - tax, no rounding loss) — so a real match should land on residual
# 0. The +-5 paise tolerance exists for real-world rounding drift, but
# combined with free subset choice over dozens of candidates it's also a
# door for coincidental near-misses: observed in practice landing
# spurious 3-5 item combinations on random noise bank rows, every one of
# them sitting at the tolerance boundary while genuine matches landed at
# exactly 0. So: try exact first, and only accept the wider tolerance
# for a large-enough subset that a few paise of drift is plausible
# rounding rather than luck.
MIN_SUBSET_SIZE_FOR_TOLERANCE_MATCH = 5
SETTLEMENT_WINDOW_DAYS = 60
MAX_CANDIDATES_PER_TARGET = 60
MAX_ITERATIONS_PER_TARGET = 200
# Safety cap on the DP's bitset width (target + tolerance, in paise).
# ~INR 5 lakh — comfortably above any realistic settlement in this
# corpus, keeps each bitset snapshot in the low tens of MB.
MAX_DP_TARGET_PAISE = 50_000_000
MAX_SECONDS_PER_TARGET = 2.0  # the GATE's timing bound; checked, not relied on

GATEWAY_SOURCE = "razorpay"
BANK_SOURCE = "bank"

FORBIDDEN_COLUMNS = frozenset({"truth_group", "is_noise"})

# 'raw' is fair game here — it's the original source payload (a real
# settlement recon ingestion puts settlement_id there), not the answer key.
_MATCH_COLUMNS = (
    "id", "source_kind", "external_ref", "amount_paise",
    "fee_paise", "tax_paise", "net_paise", "txn_date", "raw",
)

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


def net_of(row: dict) -> int:
    """The amount actually credited for a gateway row: net_paise if
    populated, else gross - fee - tax, else raw amount as a last resort.
    Integer paise throughout."""
    if row.get("net_paise") is not None:
        return row["net_paise"]
    gross = row["amount_paise"]
    if row.get("fee_paise") is not None:
        return gross - (row["fee_paise"] or 0) - (row.get("tax_paise") or 0)
    return gross


def _settlement_id_of(row: dict) -> str | None:
    return (row.get("raw") or {}).get("settlement_id")


def _currency_of(row: dict) -> str | None:
    return (row.get("raw") or {}).get("currency")


def find_by_settlement_id(bank_targets: list[dict], gateway_pool: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Path 1. Groups gateway rows by an explicit settlement_id found in
    their raw payload, then matches each unmatched bank row carrying the
    same id to its constituents. No arithmetic search involved — the
    link is treated as ground truth from the source system."""
    by_sid: dict[str, list[dict]] = defaultdict(list)
    for g in gateway_pool:
        sid = _settlement_id_of(g)
        if sid:
            by_sid[sid].append(g)

    resolved = []
    for bank in bank_targets:
        sid = _settlement_id_of(bank)
        if sid and by_sid.get(sid):
            resolved.append((bank, by_sid[sid]))
    return resolved


def candidates_for(bank: dict, pool: list[dict]) -> list[dict]:
    """Hard constraints applied BEFORE any search: same settlement date
    window (payment precedes the credit, within SETTLEMENT_WINDOW_DAYS),
    same currency when both sides declare one, and fee data present.

    The fee_paise check is not a synthetic-data workaround: a real
    Razorpay payment only carries fee/tax once it's captured and goes
    through settlement, so a row with no fee data literally cannot be a
    settlement constituent. Without it, amount-only subset-sum search
    can glue together a bank credit and an arbitrary combination of
    rows that happen to sum correctly by coincidence — observed in
    practice pulling in two unrelated rows plus one real payment from a
    different settlement entirely.
    """
    if not bank.get("txn_date"):
        return []
    bank_date = date.fromisoformat(bank["txn_date"])
    window_start = bank_date - timedelta(days=SETTLEMENT_WINDOW_DAYS)
    bank_currency = _currency_of(bank)

    out = []
    for g in pool:
        if g.get("fee_paise") is None:
            continue
        if not g.get("txn_date"):
            continue
        g_date = date.fromisoformat(g["txn_date"])
        if not (window_start <= g_date <= bank_date):
            continue
        g_currency = _currency_of(g)
        if bank_currency and g_currency and bank_currency != g_currency:
            continue
        out.append(g)
    return out


def _dp_forward(nets: list[int], max_sum: int) -> list[int]:
    """dp[i] = bitset of every sum achievable using nets[0..i-1], each
    masked to max_sum+1 bits. Nonnegative weights only: once a partial
    sum exceeds max_sum it can never come back down, so truncating it
    away is exact, not an approximation — it just prunes sums we could
    never accept anyway. This bounds every snapshot to a fixed bit
    width regardless of how large individual candidate amounts are."""
    mask = (1 << (max_sum + 1)) - 1
    dp = [1]
    for v in nets:
        prev = dp[-1]
        dp.append((prev | (prev << v)) & mask)
    return dp


def _dp_reconstruct(nets: list[int], dp: list[int], achieved: int) -> list[int]:
    chosen = []
    remaining = achieved
    for i in range(len(nets), 0, -1):
        without = (dp[i - 1] >> remaining) & 1
        if not without:
            chosen.append(i - 1)
            remaining -= nets[i - 1]
    chosen.reverse()
    return chosen


def _multiplicity_ge2(nets: list[int], max_sum: int) -> int:
    """Bitset where bit s is set iff at least TWO distinct subsets of
    `nets` sum to s.

    Tracks two parallel bitsets: `ones` (s reachable at all) and `twos`
    (s reachable 2+ ways). Adding item v, a sum s is reachable twice if
    it already was, or if s-v was, or if s and s-v were each reachable
    once — those two witnesses combine into distinct subsets:

        twos' = twos | (twos << v) | (ones & (ones << v))
        ones' = ones | (ones << v)

    This is the check that actually matters. An earlier version only
    asked whether a fully DISJOINT alternative existed, which is
    strictly weaker and let real false merges through: once path 1 had
    consumed the explicit-settlement_id payments, the leftover pool no
    longer admitted a disjoint alternative, so a 16-member subset
    blending two unrelated settlements passed the check and was
    committed. Uniqueness is the honest question — not "is there
    another answer that shares nothing with this one", but "is this
    answer the only one at all".
    """
    mask = (1 << (max_sum + 1)) - 1
    ones = 1
    twos = 0
    for v in nets:
        shifted_ones = (ones << v) & mask
        twos = (twos | ((twos << v) & mask) | (ones & shifted_ones)) & mask
        ones = (ones | shifted_ones) & mask
    return twos


def greedy_subset_sum(
    candidates: list[dict],
    target: int,
    *,
    tolerance: int = SUM_TOLERANCE_PAISE,
    max_candidates: int = MAX_CANDIDATES_PER_TARGET,
    max_iterations: int = MAX_ITERATIONS_PER_TARGET,
) -> tuple[list[dict] | None, int | None, int]:
    """Exact bounded subset-sum via bitset DP, sorted descending first so
    a truncated candidate pool keeps the largest (most consequential)
    amounts. This replaced an earlier greedy-plus-local-repair heuristic
    that looked right but wasn't: tested against real corpus data (not
    synthetic stress tests), it failed to find the true subset on
    genuinely well-separated cases — greedy's first-fit-decreasing order
    has no guarantee of reaching an exact target even when one exists.
    DP with nonnegative weights does, and stays bounded by masking every
    intermediate sum to max_sum+1 bits (see _dp_forward) rather than by
    an iteration cap — there's no combinatorial search happening, so
    there's nothing to cap.

    Tries an EXACT match first. Only falls back to the +-tolerance
    window when no exact sum exists, and only accepts the fallback when
    exactly ONE sum in that window is achievable at all — if two
    different sums both land in range, the pool is ambiguous (most
    likely two real but unrelated settlements overlapping in the same
    date window) and guessing would risk merging them; that case is
    correctly abandoned rather than resolved with a coin flip.
    """
    pool = sorted(candidates, key=lambda r: -net_of(r))[:max_candidates]
    nets = [net_of(r) for r in pool]
    n = len(nets)

    if n == 0 or target < 0 or any(v < 0 for v in nets):
        return None, None, n

    width = target + tolerance
    if width > MAX_DP_TARGET_PAISE:
        # Defensive cap: an exceptionally large settlement is rare and
        # better routed to manual review than a multi-million-bit bitset.
        return None, None, n

    dp = _dp_forward(nets, width)
    twos = _multiplicity_ge2(nets, width)

    if (dp[-1] >> target) & 1:
        if (twos >> target) & 1:
            return None, None, n  # more than one subset hits it exactly
        chosen = _dp_reconstruct(nets, dp, target)
        return [pool[i] for i in chosen], target, n

    if tolerance == 0:
        return None, None, n

    lo = max(0, target - tolerance)
    achievable = [s for s in range(lo, width + 1) if (dp[-1] >> s) & 1]
    if len(achievable) != 1:
        return None, None, n  # 0 = nothing close; >1 = ambiguous, don't guess

    best_sum = achievable[0]
    if (twos >> best_sum) & 1:
        return None, None, n
    chosen = _dp_reconstruct(nets, dp, best_sum)
    return [pool[i] for i in chosen], best_sum, n


def _page_txns(batch_id: str) -> list[dict]:
    select = ",".join(_MATCH_COLUMNS)
    rows: list[dict] = []
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client().table("txns").select(select)
            .eq("batch_id", batch_id).order("id")
            .range(o, o + _PAGE_SIZE - 1).execute()
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
            lambda o=offset: db.get_client().table("match_groups").select("id")
            .eq("batch_id", batch_id).order("id")
            .range(o, o + _PAGE_SIZE - 1).execute()
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
                lambda c=chunk, o=offset: db.get_client().table("match_members")
                .select("txn_id").in_("match_group_id", c).order("id")
                .range(o, o + _PAGE_SIZE - 1).execute()
            ).data
            matched.update(r["txn_id"] for r in page)
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
    return matched


def _order_members(rows: list[dict]) -> list[dict]:
    def sort_key(r):
        try:
            rank = _PRIMARY_PREFERENCE.index(r["source_kind"])
        except ValueError:
            rank = len(_PRIMARY_PREFERENCE)
        return (rank, str(r["id"]))
    return sorted(rows, key=sort_key)


def _create_group(batch_id: str, bank: dict, members: list[dict], *,
                  path: str, confidence: float, extra: dict) -> dict:
    """member_count is the SETTLEMENT SUBSET size — how many gateway
    payments this credit covers — per spec. `members` may legitimately
    contain non-gateway rows too (a path-1 merge absorbs each payment's
    ledger leg), so both the count and the net sum are taken over the
    gateway rows only: summing ledger amounts into the settlement total
    would double-count the same economic event and corrupt the residual.
    match_members still records every row, so the group stays queryable
    as a whole.
    """
    gateway_members = [m for m in members if m["source_kind"] == GATEWAY_SOURCE]
    net_sum = sum(net_of(m) for m in gateway_members)
    residual = bank["amount_paise"] - net_sum
    variance_components = {
        "path": path,
        "bank_amount_paise": bank["amount_paise"],
        "gateway_net_sum_paise": net_sum,
        "residual_paise": residual,
        "total_member_rows": len(members) + 1,
        **extra,
    }

    inserted = db.run_with_retry(
        lambda: db.get_client().table("match_groups").insert({
            "batch_id": batch_id, "tier": TIER, "strategy": STRATEGY,
            "confidence": confidence, "member_count": len(gateway_members),
            "total_variance_paise": residual,
            "variance_components": variance_components,
        }).execute()
    ).data[0]

    all_members = _order_members([bank] + members)
    member_payload = [
        {"match_group_id": inserted["id"], "txn_id": m["id"],
         "role": "primary" if i == 0 else "counterpart"}
        for i, m in enumerate(all_members)
    ]
    for i in range(0, len(member_payload), _INSERT_CHUNK_SIZE):
        db.run_with_retry(
            lambda c=member_payload[i:i + _INSERT_CHUNK_SIZE]:
            db.get_client().table("match_members").insert(c).execute()
        )
    return inserted


def _existing_group_map(batch_id: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    """(txn_id -> group_id, group_id -> [txn_id, ...]) for this batch."""
    group_ids: list[str] = []
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client().table("match_groups").select("id")
            .eq("batch_id", batch_id).order("id")
            .range(o, o + _PAGE_SIZE - 1).execute()
        ).data
        group_ids.extend(r["id"] for r in page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    txn_to_group: dict[str, str] = {}
    group_to_txns: dict[str, list[str]] = defaultdict(list)
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
                txn_to_group[r["txn_id"]] = r["match_group_id"]
                group_to_txns[r["match_group_id"]].append(r["txn_id"])
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
    return txn_to_group, group_to_txns


def _delete_groups(group_ids: list[str]) -> None:
    """Remove superseded groups and their members. Called only when a
    settlement_id merge absorbs them into a strictly larger group."""
    for i in range(0, len(group_ids), 100):
        chunk = group_ids[i:i + 100]
        db.run_with_retry(
            lambda c=chunk: db.get_client().table("match_members")
            .delete().in_("match_group_id", c).execute()
        )
        db.run_with_retry(
            lambda c=chunk: db.get_client().table("match_groups")
            .delete().in_("id", c).execute()
        )


def _write_variance(batch_id: str, bank: dict, reason: str, detail: str) -> None:
    db.run_with_retry(
        lambda: db.get_client().table("variances").insert({
            "batch_id": batch_id, "txn_id": bank["id"],
            "variance_paise": bank["amount_paise"],
            "category": "many_to_one_unresolved", "subcategory": reason,
            "explanation": detail,
            "suggested_action": "manual review: no gateway subset found within search bounds",
            "status": "open",
        }).execute()
    )


def _write_audit(batch_id: str, action: str, detail: dict) -> None:
    db.run_with_retry(
        lambda: db.get_client().table("audit_log").insert({
            "batch_id": batch_id, "actor": "matcher", "step": "tier4_aggregate",
            "action": action, "detail": detail,
        }).execute()
    )


def run_tier4(batch_id: str) -> dict:
    _write_audit(batch_id, "start", {"tier": TIER, "strategy": STRATEGY})

    all_rows = _page_txns(batch_id)
    row_by_id = {r["id"]: r for r in all_rows}
    matched = _already_matched_txn_ids(batch_id)
    unmatched = [r for r in all_rows if r["id"] not in matched]

    bank_targets = [r for r in unmatched if r["source_kind"] == BANK_SOURCE]
    gateway_pool = {r["id"]: r for r in unmatched if r["source_kind"] == GATEWAY_SOURCE}

    stats = {"path1_resolved": 0, "path2_resolved": 0, "unresolved": 0,
             "path1_groups_absorbed": 0, "path1_members_via_absorbed_groups": 0}
    max_elapsed = 0.0
    largest_group = None

    # ---- Path 1: explicit settlement_id ----
    # A settlement_id is authoritative linkage from the source system, so
    # this path considers gateway rows whether or not an earlier tier
    # already claimed them. When it finds one inside an existing group,
    # it absorbs that whole group — otherwise the payment's OTHER legs
    # (typically its ledger row, matched to the gateway row by tier 2)
    # would be stranded outside the settlement, which is a large and
    # entirely avoidable recall loss: every ledger<->bank and
    # ledger<->ledger pair within the settlement goes missing.
    txn_to_group, group_to_txns = _existing_group_map(batch_id)

    all_gateways = [r for r in all_rows if r["source_kind"] == GATEWAY_SOURCE]
    explicit_hits = find_by_settlement_id(bank_targets, all_gateways)
    resolved_bank_ids: set[str] = set()

    for bank, gateway_members in explicit_hits:
        member_ids: set[str] = set()
        absorbed_groups: set[str] = set()

        for gw in gateway_members:
            member_ids.add(gw["id"])
            gid = txn_to_group.get(gw["id"])
            if gid:
                absorbed_groups.add(gid)
                member_ids.update(group_to_txns.get(gid, []))

        member_ids.discard(bank["id"])
        members = [row_by_id[t] for t in member_ids if t in row_by_id]
        if not members:
            continue

        if absorbed_groups:
            _delete_groups(sorted(absorbed_groups))
            for gid in absorbed_groups:
                for tid in group_to_txns.get(gid, []):
                    txn_to_group.pop(tid, None)
            stats["path1_groups_absorbed"] += len(absorbed_groups)

        group = _create_group(
            batch_id, bank, members, path="settlement_id",
            confidence=CONFIDENCE_SETTLEMENT_ID,
            extra={
                "settlement_id": _settlement_id_of(bank),
                "absorbed_group_count": len(absorbed_groups),
            },
        )
        for m in members:
            gateway_pool.pop(m["id"], None)
            txn_to_group[m["id"]] = group["id"]
        resolved_bank_ids.add(bank["id"])
        stats["path1_resolved"] += 1
        if largest_group is None or len(members) > largest_group["size"]:
            largest_group = {"group_id": group["id"], "size": len(members), "path": "settlement_id"}

    # ---- Path 2: constrained subset-sum search ----
    # Candidate pool is "gateway rows not yet tied to ANY bank credit",
    # not "gateway rows no tier has touched". Those differ, and the
    # distinction matters: once tier 2 links a payment to its ledger leg,
    # the payment is no longer unmatched but is still unsettled, and
    # restricting to untouched rows left this path with an empty pool and
    # silently unable to resolve anything. A payment already sitting in a
    # group that contains a bank row is genuinely settled and correctly
    # excluded.
    def _awaiting_settlement(row: dict) -> bool:
        gid = txn_to_group.get(row["id"])
        if gid is None:
            return True
        return not any(
            row_by_id[t]["source_kind"] == BANK_SOURCE
            for t in group_to_txns.get(gid, [])
            if t in row_by_id
        )

    remaining_targets = [b for b in bank_targets if b["id"] not in resolved_bank_ids]
    remaining_targets.sort(key=lambda r: -(r["amount_paise"] or 0))

    for bank in remaining_targets:
        available = [r for r in all_rows
                     if r["source_kind"] == GATEWAY_SOURCE and _awaiting_settlement(r)]
        candidates = candidates_for(bank, available)

        start = time.monotonic()
        # Exact first: a genuine settlement sum has zero rounding loss.
        subset, achieved, iterations = greedy_subset_sum(candidates, bank["amount_paise"], tolerance=0)
        used_tolerance = False
        if not subset:
            iterations_exact = iterations
            subset, achieved, iterations = greedy_subset_sum(candidates, bank["amount_paise"])
            iterations += iterations_exact
            if subset and len(subset) < MIN_SUBSET_SIZE_FOR_TOLERANCE_MATCH:
                # A few paise of drift on a tiny subset is far more likely
                # to be a coincidental fit than genuine rounding noise.
                subset = None
            else:
                used_tolerance = True
        elapsed = time.monotonic() - start
        max_elapsed = max(max_elapsed, elapsed)

        if not subset:
            reason = "search_cap_hit" if iterations >= MAX_ITERATIONS_PER_TARGET else "no_subset_found"
            _write_variance(
                batch_id, bank, reason,
                f"searched {len(candidates)} candidates (capped at {MAX_CANDIDATES_PER_TARGET}), "
                f"{iterations} iterations (capped at {MAX_ITERATIONS_PER_TARGET}), "
                f"no exact combination, and no tolerance combination with >= "
                f"{MIN_SUBSET_SIZE_FOR_TOLERANCE_MATCH} members, within "
                f"{SUM_TOLERANCE_PAISE} paise of {bank['amount_paise']}",
            )
            stats["unresolved"] += 1
            continue

        # Same absorb rule as path 1: pull in each matched payment's
        # existing group so its ledger leg joins the settlement too.
        member_ids: set[str] = set()
        absorbed: set[str] = set()
        for m in subset:
            member_ids.add(m["id"])
            gid = txn_to_group.get(m["id"])
            if gid:
                absorbed.add(gid)
                member_ids.update(group_to_txns.get(gid, []))
        member_ids.discard(bank["id"])
        members = [row_by_id[t] for t in member_ids if t in row_by_id]

        if absorbed:
            _delete_groups(sorted(absorbed))
            for gid in absorbed:
                for tid in group_to_txns.get(gid, []):
                    txn_to_group.pop(tid, None)

        group = _create_group(
            batch_id, bank, members, path="greedy_search", confidence=CONFIDENCE_SEARCH,
            extra={
                "candidate_pool_size": len(candidates),
                "iterations": iterations,
                "elapsed_seconds": round(elapsed, 4),
                "used_tolerance": used_tolerance,
                "absorbed_group_count": len(absorbed),
            },
        )
        for m in members:
            gateway_pool.pop(m["id"], None)
            txn_to_group[m["id"]] = group["id"]
        stats["path2_resolved"] += 1
        if largest_group is None or len(subset) > largest_group["size"]:
            largest_group = {"group_id": group["id"], "size": len(subset), "path": "greedy_search"}

    summary = {
        "tier": TIER,
        "strategy": STRATEGY,
        "bank_targets": len(bank_targets),
        "path1_resolved": stats["path1_resolved"],
        "path2_resolved": stats["path2_resolved"],
        "unresolved_to_variance_queue": stats["unresolved"],
        "max_seconds_per_target": round(max_elapsed, 4),
        "within_time_budget": max_elapsed <= MAX_SECONDS_PER_TARGET,
        "largest_group": largest_group,
    }
    _write_audit(batch_id, "finish", summary)
    return summary

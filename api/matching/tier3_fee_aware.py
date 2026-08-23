"""Tier 3 matcher: fee-aware amount reconstruction.

Runs on whatever tiers 1 and 2 left unmatched.

The premise: gateway gross, gateway net, and ledger gross are three
different numbers describing ONE payment. A matcher comparing amounts
for equality can never link them. This tier reconstructs the
arithmetic instead — for a gateway row carrying (gross, fee, tax), a
counterpart is accepted when its amount equals any of:

    gross
    gross - fee
    gross - fee - tax
    gross - (fee + tax)          within FEE_TOLERANCE_PAISE

The last two are arithmetically identical in exact integer maths; they
differ only when a source rounds the combined deduction separately from
the individual ones, which is exactly when the 2-paise tolerance earns
its keep. Every comparison is integer paise — no float, ever.

Two linking paths, because the bucket this tier exists to solve shows up
both ways:

  A. gateway row and its counterparts are all still unmatched -> form a
     new tier-3 group (the case the spec describes).
  B. the gateway row was already claimed by an earlier tier (tier 1
     matches gateway<->ledger on identical gross), leaving the bank net
     row orphaned with no unmatched gateway partner left to find. Then
     the only way to resolve it is to attach the orphan to that existing
     group, using the group's gateway member for the arithmetic.

Path B is what actually clears the fee/tax bucket in practice, since an
exact-match tier will always claim the gross<->gross pair first.

Refunds are handled explicitly: a negative amount whose absolute value
matches an earlier positive amount from the same counterparty within
REFUND_WINDOW_DAYS is a refund pair, not an orphan.

=====================================================================
 THE MATCHER MUST NEVER READ truth_group OR is_noise.
=====================================================================
Same rule and same enforcement as tiers 1 and 2.
"""

import logging
from collections import defaultdict
from datetime import date

from lib import db
from matching.tier2_normalised import _fetch_groups_with_members, normalize_ref

logger = logging.getLogger("matching.tier3_fee_aware")

TIER = 3
STRATEGY = "fee_reconstructed"

# Tolerance for the combined gross-(fee+tax) form, per spec.
FEE_TOLERANCE_PAISE = 2
# Exact forms get no slack.
EXACT_TOLERANCE_PAISE = 0

REFUND_WINDOW_DAYS = 30

# Amount arithmetic alone is NOT sufficient evidence of a match. Across
# thousands of rows some unrelated pair will always satisfy
# gross - fee - tax ~= candidate by coincidence — observed in practice
# linking a bank row to a gateway row 28 days away with an unrelated
# reference. So a candidate must ALSO corroborate on reference or date.
CORROBORATION_DATE_WINDOW_DAYS = 3

BASE_CONFIDENCE = 0.9
CONFIDENCE_STEP = 0.05

GATEWAY_SOURCE = "razorpay"

FORBIDDEN_COLUMNS = frozenset({"truth_group", "is_noise"})

_MATCH_COLUMNS = (
    "id", "source_kind", "external_ref", "amount_paise",
    "fee_paise", "tax_paise", "net_paise", "txn_date", "counterparty",
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


def amount_interpretations(gross: int, fee: int | None, tax: int | None) -> list[tuple[str, int, int]]:
    """The amounts a counterpart of this gateway row could legitimately
    carry. Returns (label, expected_amount, tolerance_paise).

    Integer arithmetic throughout; fee/tax absent are treated as zero
    but the corresponding interpretations are skipped rather than
    silently collapsing onto `gross`.
    """
    out: list[tuple[str, int, int]] = [("gross", gross, EXACT_TOLERANCE_PAISE)]
    if fee is not None:
        out.append(("gross_minus_fee", gross - fee, EXACT_TOLERANCE_PAISE))
    if fee is not None and tax is not None:
        out.append(("gross_minus_fee_minus_tax", gross - fee - tax, EXACT_TOLERANCE_PAISE))
        # Same value in exact integer maths; kept separate because a
        # source that rounds the combined deduction lands slightly off,
        # and only this form is allowed the tolerance.
        out.append(("gross_minus_fee_plus_tax", gross - (fee + tax), FEE_TOLERANCE_PAISE))
    return out


def classify_amount(candidate: int, gross: int, fee: int | None, tax: int | None) -> tuple[str, int] | None:
    """Which interpretation (if any) explains `candidate`. Returns
    (label, residual_paise) for the tightest-fitting interpretation, or
    None if nothing explains it."""
    best: tuple[str, int] | None = None
    for label, expected, tolerance in amount_interpretations(gross, fee, tax):
        residual = candidate - expected
        if abs(residual) <= tolerance:
            if best is None or abs(residual) < abs(best[1]):
                best = (label, residual)
    return best


def variance_breakdown(gross: int, fee: int | None, tax: int | None,
                       counterpart_amount: int, interpretation: str) -> dict:
    """Reconstructed explanation of the gap between a gateway gross and a
    counterpart's amount, with fee + tax + residual == total_variance.

    Components are attributed according to which deduction the
    interpretation actually says happened. Attributing fee and tax
    unconditionally would be wrong: for a gross<->gross match nothing was
    deducted, and blindly recording fee/tax there produces a bogus
    negative residual that cancels them back out.
    """
    total = gross - counterpart_amount
    if interpretation == "gross":
        fee_part = tax_part = 0
    elif interpretation == "gross_minus_fee":
        fee_part, tax_part = (fee or 0), 0
    else:  # gross_minus_fee_minus_tax / gross_minus_fee_plus_tax
        fee_part, tax_part = (fee or 0), (tax or 0)

    return {
        "gross_paise": gross,
        "fee_paise": fee_part,
        "tax_paise": tax_part,
        "residual_paise": total - fee_part - tax_part,
        "counterpart_amount_paise": counterpart_amount,
        "total_variance_paise": total,
        "interpretation": interpretation,
    }


def is_corroborated(gateway_row: dict, candidate: dict) -> bool:
    """Does anything besides the amount arithmetic support this link?

    Requires either normalised-reference agreement (reusing tier 2's
    normalisation so the two tiers can't disagree about what a reference
    is) or dates within CORROBORATION_DATE_WINDOW_DAYS. Without this,
    tier 3 links arithmetically-coincidental rows from unrelated
    payments weeks apart.
    """
    ref_a, ref_b = gateway_row.get("external_ref"), candidate.get("external_ref")
    if ref_a and ref_b:
        full_a, last_a = normalize_ref(ref_a)
        full_b, last_b = normalize_ref(ref_b)
        if full_a == full_b or last_a == last_b:
            return True

    d_a, d_b = gateway_row.get("txn_date"), candidate.get("txn_date")
    if d_a and d_b:
        delta = abs((date.fromisoformat(d_a) - date.fromisoformat(d_b)).days)
        if delta <= CORROBORATION_DATE_WINDOW_DAYS:
            return True

    return False


def _page_txns(batch_id: str) -> list[dict]:
    select = ",".join(_MATCH_COLUMNS)
    rows: list[dict] = []
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client()
            .table("txns").select(select)
            .eq("batch_id", batch_id)
            .order("id")
            .range(o, o + _PAGE_SIZE - 1).execute()
        ).data
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    if rows:
        _assert_no_truth_columns(rows[0].keys())
    return rows


def _fetch_groups(batch_id: str, by_id: dict[str, dict]) -> list[dict]:
    group_rows: list[dict] = []
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client().table("match_groups")
            .select("id,tier,strategy,confidence,member_count")
            .eq("batch_id", batch_id).order("id")
            .range(o, o + _PAGE_SIZE - 1).execute()
        ).data
        group_rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    if not group_rows:
        return []

    ids = [g["id"] for g in group_rows]
    members_by_group: dict[str, list[str]] = defaultdict(list)
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        offset = 0
        while True:
            page = db.run_with_retry(
                lambda c=chunk, o=offset: db.get_client().table("match_members")
                .select("match_group_id,txn_id").in_("match_group_id", c).order("id")
                .range(o, o + _PAGE_SIZE - 1).execute()
            ).data
            for r in page:
                members_by_group[r["match_group_id"]].append(r["txn_id"])
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

    groups = []
    for g in group_rows:
        members = [by_id[t] for t in members_by_group.get(g["id"], []) if t in by_id]
        if members:
            groups.append({**g, "members": members})
    return groups


def _matched_txn_ids(groups: list[dict]) -> set[str]:
    return {m["id"] for g in groups for m in g["members"]}


def _order_members(rows: list[dict]) -> list[dict]:
    def sort_key(r):
        try:
            rank = _PRIMARY_PREFERENCE.index(r["source_kind"])
        except ValueError:
            rank = len(_PRIMARY_PREFERENCE)
        return (rank, str(r["id"]))
    return sorted(rows, key=sort_key)


def find_refund_pairs(rows: list[dict]) -> list[tuple[dict, dict]]:
    """A negative amount whose absolute value matches an earlier positive
    amount from the same counterparty within REFUND_WINDOW_DAYS is a
    refund of that original, not an orphan.

    Counterparty is the pairing key when present; where a source doesn't
    carry one, the normalised reference tail is used instead, so a
    refund still pairs to its original rather than being dropped.
    """
    def pair_key(r: dict) -> str:
        if r.get("counterparty"):
            return f"cp:{r['counterparty']}"
        ref = (r.get("external_ref") or "").upper()
        alnum = "".join(c for c in ref if c.isalnum())
        return f"ref:{alnum[-8:]}"

    positives: dict[str, list[dict]] = defaultdict(list)
    negatives: list[dict] = []
    for r in rows:
        if r["amount_paise"] is None or not r["txn_date"]:
            continue
        if r["amount_paise"] < 0:
            negatives.append(r)
        else:
            positives[pair_key(r)].append(r)

    pairs: list[tuple[dict, dict]] = []
    claimed: set[str] = set()
    for neg in negatives:
        key = pair_key(neg)
        neg_date = date.fromisoformat(neg["txn_date"])
        target = abs(neg["amount_paise"])
        best: dict | None = None
        for pos in positives.get(key, []):
            if pos["id"] in claimed or pos["amount_paise"] != target:
                continue
            pos_date = date.fromisoformat(pos["txn_date"])
            delta = (neg_date - pos_date).days
            if 0 <= delta <= REFUND_WINDOW_DAYS:
                if best is None or pos_date > date.fromisoformat(best["txn_date"]):
                    best = pos
        if best is not None:
            claimed.add(best["id"])
            pairs.append((best, neg))
    return pairs


def _write_audit(batch_id: str, action: str, detail: dict) -> None:
    db.run_with_retry(
        lambda: db.get_client().table("audit_log").insert({
            "batch_id": batch_id, "actor": "matcher", "step": "tier3_fee_aware",
            "action": action, "detail": detail,
        }).execute()
    )


REFUND_STRATEGY = "refund_linked"


def _refund_ref_links(refund_ref: str | None, original_ref: str | None) -> bool:
    """A refund's reference normally carries its original's inside it —
    'rfnd_QVmvb0' against 'QVmvb0'. Normalisation strips the ledger/
    gateway prefixes both sides share, then containment (not equality)
    is the test, since the refund keeps its own marker."""
    if not refund_ref or not original_ref:
        return False
    r_full, _ = normalize_ref(refund_ref)
    o_full, _ = normalize_ref(original_ref)
    if not r_full or not o_full:
        return False
    return o_full in r_full and len(o_full) >= 3


def _merge_refund_groups(batch_id: str, groups: list[dict]) -> dict:
    """Link a refund group back to the group holding its original.

    Tier 1 matches each leg perfectly but INDEPENDENTLY: the original's
    three source rows form one group and the refund's three form
    another, so every original<->refund pair across the two is missed.
    The refund is not an orphan and not a separate economic event — it
    nets against the original — so the two groups belong together.

    Merged only when exactly one candidate original group matches on
    reference containment, direction, magnitude and date window. More
    than one candidate means guessing, so it is left alone.
    """
    stats = {"refund_groups_merged": 0, "refund_ambiguous_skipped": 0}

    def all_negative(g):
        return g["members"] and all((m["amount_paise"] or 0) < 0 for m in g["members"])

    def all_positive(g):
        return g["members"] and all((m["amount_paise"] or 0) > 0 for m in g["members"])

    refund_groups = [g for g in groups if all_negative(g)]
    original_groups = [g for g in groups if all_positive(g)]

    for rg in refund_groups:
        r_row = rg["members"][0]
        r_amount = abs(r_row["amount_paise"] or 0)
        r_date = date.fromisoformat(r_row["txn_date"]) if r_row.get("txn_date") else None

        candidates = []
        for og in original_groups:
            o_row = og["members"][0]
            if not _refund_ref_links(r_row.get("external_ref"), o_row.get("external_ref")):
                continue
            # A refund can be partial, never larger than what was paid.
            if r_amount > (o_row["amount_paise"] or 0):
                continue
            if r_date and o_row.get("txn_date"):
                delta = (r_date - date.fromisoformat(o_row["txn_date"])).days
                if delta < 0 or delta > REFUND_WINDOW_DAYS:
                    continue
            candidates.append(og)

        if len(candidates) != 1:
            if len(candidates) > 1:
                stats["refund_ambiguous_skipped"] += 1
            continue

        target = candidates[0]
        db.run_with_retry(
            lambda src=rg["id"], dst=target["id"]: db.get_client().table("match_members")
            .update({"match_group_id": dst}).eq("match_group_id", src).execute()
        )
        db.run_with_retry(
            lambda src=rg["id"]: db.get_client().table("match_groups").delete().eq("id", src).execute()
        )

        target["members"].extend(rg["members"])
        net = sum(m["amount_paise"] or 0 for m in target["members"])
        db.run_with_retry(
            lambda gid=target["id"], mc=len(target["members"]), n=net:
            db.get_client().table("match_groups").update({
                "tier": TIER, "strategy": REFUND_STRATEGY,
                "member_count": mc, "total_variance_paise": n,
                "variance_components": {
                    "refund_pair": True, "fee_paise": 0, "tax_paise": 0,
                    "residual_paise": n, "total_variance_paise": n,
                },
            }).eq("id", gid).execute()
        )
        stats["refund_groups_merged"] += 1

    return stats


def run_tier3(batch_id: str) -> dict:
    _write_audit(batch_id, "start", {"tier": TIER, "strategy": STRATEGY})

    all_rows = _page_txns(batch_id)
    by_id = {r["id"]: r for r in all_rows}

    groups = _fetch_groups(batch_id, by_id)
    matched = _matched_txn_ids(groups)
    unmatched = [r for r in all_rows if r["id"] not in matched]
    unmatched_before = len(unmatched)

    stats = {
        "new_groups": 0, "groups_enriched": 0, "txns_attached": 0,
        "refund_pairs_linked": 0, "ambiguous_skipped": 0, "uncorroborated_rejected": 0,
        "interpretation_counts": defaultdict(int),
    }
    consumed: set[str] = set()

    # ---- Path A: gateway row still unmatched -> form a new group ----
    unmatched_gateways = [r for r in unmatched if r["source_kind"] == GATEWAY_SOURCE]
    others = [r for r in unmatched if r["source_kind"] != GATEWAY_SOURCE]

    for gw in unmatched_gateways:
        if gw["id"] in consumed or gw["amount_paise"] is None:
            continue
        gross, fee, tax = gw["amount_paise"], gw["fee_paise"], gw["tax_paise"]

        members = [gw]
        used_labels = []
        for cand in others:
            if cand["id"] in consumed or cand["amount_paise"] is None:
                continue
            if cand["source_kind"] in {m["source_kind"] for m in members}:
                continue
            hit = classify_amount(cand["amount_paise"], gross, fee, tax)
            if hit is None:
                continue
            if not is_corroborated(gw, cand):
                stats["uncorroborated_rejected"] += 1
                continue
            members.append(cand)
            used_labels.append(hit[0])

        # Tier 3's job is reconstructing fee/tax deductions. A group whose
        # only link is gross == gross is an exact amount match wearing a
        # 'fee_reconstructed' label — it belongs to the settlement tier,
        # not here. Leave those rows for it.
        if len(members) < 2 or all(lbl == "gross" for lbl in used_labels):
            continue

        # Describe the variance against the counterpart that actually
        # demonstrates the deduction, not merely the first one found.
        primary_label = next((lbl for lbl in used_labels if lbl != "gross"), used_labels[0])
        counterpart = members[1 + used_labels.index(primary_label)]
        breakdown = variance_breakdown(gross, fee, tax, counterpart["amount_paise"], primary_label)
        breakdown["interpretations"] = used_labels
        confidence = round(BASE_CONFIDENCE - CONFIDENCE_STEP * (1 if breakdown["residual_paise"] else 0), 2)

        inserted = db.run_with_retry(
            lambda: db.get_client().table("match_groups").insert({
                "batch_id": batch_id, "tier": TIER, "strategy": STRATEGY,
                "confidence": confidence, "member_count": len(members),
                "total_variance_paise": breakdown["total_variance_paise"],
                "variance_components": breakdown,
            }).execute()
        ).data[0]

        db.run_with_retry(
            lambda gid=inserted["id"], ms=members: db.get_client().table("match_members").insert([
                {"match_group_id": gid, "txn_id": m["id"],
                 "role": "primary" if i == 0 else "counterpart"}
                for i, m in enumerate(_order_members(ms))
            ]).execute()
        )
        for m in members:
            consumed.add(m["id"])
        for lbl in used_labels:
            stats["interpretation_counts"][lbl] += 1
        stats["new_groups"] += 1

    # ---- Path B: attach orphan to an existing group's gateway row ----
    still_unmatched = [r for r in unmatched if r["id"] not in consumed]
    groups_touched: dict[str, dict] = {}

    for row in still_unmatched:
        if row["amount_paise"] is None:
            continue
        candidates = []
        for g in groups:
            gw = next((m for m in g["members"] if m["source_kind"] == GATEWAY_SOURCE), None)
            if gw is None or gw["amount_paise"] is None:
                continue
            if row["source_kind"] in {m["source_kind"] for m in g["members"]}:
                continue
            hit = classify_amount(row["amount_paise"], gw["amount_paise"], gw["fee_paise"], gw["tax_paise"])
            if hit is None:
                continue
            # An exact-gross re-match adds nothing tiers 1/2 didn't already
            # have; tier 3 only claims genuine fee/tax reconstructions.
            if hit[0] == "gross":
                continue
            if not is_corroborated(gw, row):
                stats["uncorroborated_rejected"] += 1
                continue
            candidates.append((g, gw, hit))

        if len(candidates) != 1:
            if len(candidates) > 1:
                stats["ambiguous_skipped"] += 1
            continue

        group, gw, (label, residual) = candidates[0]
        db.run_with_retry(
            lambda gid=group["id"], tid=row["id"]: db.get_client().table("match_members")
            .insert({"match_group_id": gid, "txn_id": tid, "role": "counterpart"}).execute()
        )
        group["members"].append(row)
        groups_touched[group["id"]] = group
        consumed.add(row["id"])
        stats["txns_attached"] += 1
        stats["interpretation_counts"][label] += 1

        breakdown = variance_breakdown(gw["amount_paise"], gw["fee_paise"], gw["tax_paise"],
                                       row["amount_paise"], label)
        breakdown["interpretations"] = [label]
        confidence = round(BASE_CONFIDENCE - CONFIDENCE_STEP * (1 if breakdown["residual_paise"] else 0), 2)
        db.run_with_retry(
            lambda gid=group["id"], b=breakdown, mc=len(group["members"]), conf=confidence:
            db.get_client().table("match_groups").update({
                "tier": TIER, "strategy": STRATEGY, "confidence": conf,
                "member_count": mc, "total_variance_paise": b["total_variance_paise"],
                "variance_components": b,
            }).eq("id", gid).execute()
        )

    stats["groups_enriched"] = len(groups_touched)

    # ---- Refund pairs among whatever is still loose ----
    leftovers = [r for r in unmatched if r["id"] not in consumed]
    for original, refund in find_refund_pairs(leftovers):
        if original["id"] in consumed or refund["id"] in consumed:
            continue
        breakdown = {
            "refund_pair": True,
            "original_txn_id": original["id"],
            "original_amount_paise": original["amount_paise"],
            "refund_amount_paise": refund["amount_paise"],
            "fee_paise": 0, "tax_paise": 0,
            "residual_paise": original["amount_paise"] + refund["amount_paise"],
            "total_variance_paise": original["amount_paise"] + refund["amount_paise"],
        }
        inserted = db.run_with_retry(
            lambda: db.get_client().table("match_groups").insert({
                "batch_id": batch_id, "tier": TIER, "strategy": STRATEGY,
                "confidence": BASE_CONFIDENCE, "member_count": 2,
                "total_variance_paise": breakdown["total_variance_paise"],
                "variance_components": breakdown,
            }).execute()
        ).data[0]
        db.run_with_retry(
            lambda gid=inserted["id"], o=original, rf=refund: db.get_client().table("match_members").insert([
                {"match_group_id": gid, "txn_id": o["id"], "role": "primary"},
                {"match_group_id": gid, "txn_id": rf["id"], "role": "counterpart"},
            ]).execute()
        )
        consumed.add(original["id"])
        consumed.add(refund["id"])
        stats["refund_pairs_linked"] += 1

    # ---- Refund groups already formed by an earlier tier ----
    # Re-read: the attach pass above mutated group membership.
    refund_stats = _merge_refund_groups(batch_id, _fetch_groups_with_members(batch_id, by_id))

    summary = {
        "tier": TIER,
        "strategy": STRATEGY,
        "unmatched_before": unmatched_before,
        "new_groups": stats["new_groups"],
        "groups_enriched": stats["groups_enriched"],
        "txns_attached_to_existing_groups": stats["txns_attached"],
        "refund_pairs_linked": stats["refund_pairs_linked"],
        "refund_groups_merged": refund_stats["refund_groups_merged"],
        "refund_ambiguous_skipped": refund_stats["refund_ambiguous_skipped"],
        "ambiguous_skipped": stats["ambiguous_skipped"],
        "uncorroborated_rejected": stats["uncorroborated_rejected"],
        "txns_matched": len(consumed),
        "unmatched_after": unmatched_before - len(consumed),
        "interpretation_counts": dict(stats["interpretation_counts"]),
    }
    _write_audit(batch_id, "finish", summary)
    return summary

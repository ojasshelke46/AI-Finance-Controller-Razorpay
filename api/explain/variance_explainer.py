"""LLM-based classification of the variance queue.

For each open variances row, assembles compact context — the variance
amount, its provisional (deterministic) category, the full record
detail of every txn involved (including raw fields), and the tier
history of any associated match_group — and asks BytePlus to classify
it. Independent variances are batched 5-10 per call: they don't need
each other's context, and batching cuts latency and cost substantially
compared to one call per row.

Uses lib.byteplus.complete_json exclusively — this module does not
implement its own HTTP call, per the project-wide rule that every
BytePlus consumer shares the one client.

=====================================================================
 THIS MODULE MUST NEVER READ truth_group OR is_noise.
=====================================================================
Same rule as every matching tier, extended to the LLM: an explainer
that could see the answer key could satisfy that check by parroting it
instead of reasoning from the record, which would make its output
worthless as a signal of whether the explanation is actually any good.
It's also simply not real data — no production system has a
truth_group column.
"""

import json
import logging
import time
from collections import defaultdict

from lib import db
from lib.byteplus import ByteplusError, complete_json

logger = logging.getLogger("explain.variance_explainer")

BATCH_MIN = 5
BATCH_MAX = 10

VALID_CATEGORIES = frozenset({
    "gateway_fee", "gst_on_fee", "refund_offset", "chargeback",
    "timing_difference", "duplicate_entry", "missing_source_record",
    "fx_or_rounding", "partial_settlement", "unexplained",
})
VALID_ACTIONS = frozenset({
    "auto_accept", "book_to_fee_account", "await_next_settlement",
    "request_bank_advice", "flag_for_human", "write_off",
})
UNEXPLAINED_CONFIDENCE_CEILING = 0.49  # strictly below 0.5, per the hard rule

FORBIDDEN_COLUMNS = frozenset({"truth_group", "is_noise"})

_TXN_DETAIL_COLUMNS = (
    "id", "source_kind", "external_ref", "amount_paise", "fee_paise",
    "tax_paise", "net_paise", "txn_date", "value_date", "description",
    "counterparty", "raw",
)

_PAGE_SIZE = 1000


def _assert_no_forbidden(columns) -> None:
    leaked = FORBIDDEN_COLUMNS & set(columns)
    if leaked:
        raise AssertionError(
            f"variance explainer attempted to read ground-truth column(s): {sorted(leaked)}. "
            "The explainer must reason only from real record data, same rule as every matcher."
        )


_assert_no_forbidden(_TXN_DETAIL_COLUMNS)


# ---------------------------------------------------------------------
# ground-truth redaction
# ---------------------------------------------------------------------
# _assert_no_forbidden above covers the SCHEMA columns. It does not
# cover the second, quieter leak: scripts/generate_corpus.py stamps its
# own answer key into two ordinary record fields on every synthetic row —
# description "synthetic:<category>" and raw["category"] — so a context
# assembled from those fields hands the model strings like
# "synthetic:fee_tax_split" and then asks it to classify that variance.
# It can read the answer off the record.
#
# The fix belongs HERE and not in the generator. Those fields are real
# record data as far as the database is concerned, and eval/scorer.py
# legitimately recovers the injected category from description to grade
# against. Redacting at context-build time keeps the label in the
# database for the grader and keeps it away from every model.
_LEAK_KEYS = frozenset({"synthetic", "category", "truth_group"})

# Substrings that must never survive into a serialized model context.
_LEAK_MARKERS = ("synthetic:", "truth_group")


def _redact(t: dict) -> dict:
    """Strip the corpus's answer key out of one txn row."""
    d = dict(t)
    if (d.get("description") or "").startswith("synthetic:"):
        d["description"] = ""
    raw = d.get("raw") or {}
    d["raw"] = {k: v for k, v in raw.items() if k not in _LEAK_KEYS}
    return d


def assert_no_leak(payload, *, where: str = "context") -> None:
    """Raise if something about to reach a model still carries the label.

    Deliberately loud, and deliberately checked on the SERIALIZED form
    rather than on the fields we remembered to look at — a leak that
    reopens through some field nobody thought about is exactly the case
    a field-by-field check misses. A leak that reopens quietly is worse
    than one never closed: by then every explainer and grounding number
    since the regression was measured against a model that could read
    the answer, and nothing in the output says so.
    """
    serialized = json.dumps(payload, default=str)
    for marker in _LEAK_MARKERS:
        if marker in serialized:
            raise AssertionError(
                f"ground-truth leak in {where}: serialized context contains {marker!r}. "
                "The corpus label must be redacted before any record reaches a model "
                "(see _redact). Refusing to send it."
            )


SYSTEM_PROMPT = """You are a reconciliation controller for a payment gateway
reconciliation system (Razorpay gateway, bank statements, and an internal
ledger). You are given one or more independent "variance" cases: a
discrepancy between what different systems recorded about the same or
related transaction(s), the full record for every transaction involved
(including its raw source payload), and, when the variance came from an
already-matched group, how an earlier automated matching step formed and
scored that group. Classify each variance using ONLY the record data
given to you — never assume information that is not present.

For EACH variance, return exactly these fields:
  category          one of: gateway_fee, gst_on_fee, refund_offset,
                    chargeback, timing_difference, duplicate_entry,
                    missing_source_record, fx_or_rounding,
                    partial_settlement, unexplained
  subcategory       short free text (a few words) giving more specific
                    detail than the category alone
  confidence        a number from 0 to 1
  explanation       at most two sentences, plain language, and it MUST
                    cite the specific amounts involved (real paise or
                    rupee figures taken from the record) — a vague
                    explanation like "a fee was likely deducted" is not
                    acceptable, it must say which amounts and how they
                    relate
  suggested_action  one of: auto_accept, book_to_fee_account,
                    await_next_settlement, request_bank_advice,
                    flag_for_human, write_off

The suggested_action must actually fit the category you assigned — it
is the instruction a controller will follow, not a label. Use these
rules:

  book_to_fee_account   ONLY when the variance IS a cost of processing
                        the payment: gateway_fee, or gst_on_fee. Never
                        use it for a chargeback, a refund, a missing
                        record, or anything you called unexplained — a
                        chargeback is a reversal of revenue, not a fee,
                        and booking it to a fee account misstates both
                        accounts.
  await_next_settlement ONLY for timing_difference or partial_settlement
                        where the record shows the missing leg is simply
                        not settled yet, and the date supports that.
  auto_accept           ONLY when the variance is fully explained by
                        arithmetic you can show and is immaterial — in
                        practice fx_or_rounding, or an exactly
                        reconciling fee. Never on a case your own
                        explanation describes as uncertain.
  request_bank_advice   when the bank side is the one that is missing,
                        wrong, or unexplained and only the bank can
                        resolve it.
  write_off             ONLY for an immaterial residual that no further
                        work will recover. Amount matters: do not
                        propose writing off a large sum.
  flag_for_human        chargeback, duplicate_entry, missing_source_record,
                        anything unexplained, and anything material or
                        ambiguous. This is the correct conservative
                        default — choosing it is never a failure.

HARD RULE: if the record data given to you does not support a confident
classification, you MUST return category "unexplained" with confidence
strictly below 0.5. Inventing a plausible-sounding explanation that the
data does not actually support is worse than admitting you do not know:
a wrong confident answer can silently corrupt a real ledger, while an
honest "unexplained" simply routes the case to a human for review. Do
not guess in order to fill in a category — when in doubt, say so."""

_SCHEMA_HINT_TEMPLATE = """{{
  "results": [
    {{
      "variance_id": "<must exactly match one of the input variance_id values, as a string>",
      "category": "gateway_fee|gst_on_fee|refund_offset|chargeback|timing_difference|duplicate_entry|missing_source_record|fx_or_rounding|partial_settlement|unexplained",
      "subcategory": "short free text",
      "confidence": 0.0,
      "explanation": "at most two sentences, must cite specific real amounts from the record",
      "suggested_action": "auto_accept|book_to_fee_account|await_next_settlement|request_bank_advice|flag_for_human|write_off"
    }}
  ]
}}
"results" must contain exactly {n} objects, one per input variance, in any order."""


def chunk_variances(items: list, min_size: int = BATCH_MIN, max_size: int = BATCH_MAX) -> list[list]:
    """Groups of min_size to max_size, avoiding a small leftover tail —
    the last two chunks split evenly rather than leaving e.g. 9 then 1."""
    n = len(items)
    if n == 0:
        return []
    if n <= max_size:
        return [items]

    chunks = []
    i = 0
    while i < n:
        remaining = n - i
        if remaining <= max_size:
            chunks.append(items[i:])
            break
        take = max_size
        if remaining - take < min_size:
            take = remaining - min_size
        chunks.append(items[i:i + take])
        i += take
    return chunks


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


def _fetch_by_ids(table: str, columns: str, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    rows: list[dict] = []
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        offset = 0
        while True:
            page = db.run_with_retry(
                lambda c=chunk, o=offset: db.get_client().table(table).select(columns)
                .in_("id", c).order("id").range(o, o + _PAGE_SIZE - 1).execute()
            ).data
            rows.extend(page)
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
    return rows


def _fetch_group_members(group_ids: list[str]) -> dict[str, list[str]]:
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


def _txn_detail(t: dict) -> dict:
    # Every record reaching a model goes through here, so this is the one
    # place the redaction has to hold.
    t = _redact(t)
    return {
        "txn_id": t["id"],
        "source_kind": t["source_kind"],
        "external_ref": t["external_ref"],
        "amount_paise": t["amount_paise"],
        "fee_paise": t["fee_paise"],
        "tax_paise": t["tax_paise"],
        "net_paise": t["net_paise"],
        "txn_date": t["txn_date"],
        "value_date": t["value_date"],
        "description": t["description"],
        "counterparty": t["counterparty"],
        "raw": t["raw"],
    }


def build_context(
    variance: dict,
    txns_by_id: dict[str, dict],
    groups_by_id: dict[str, dict],
    members_by_group: dict[str, list[str]],
) -> dict:
    records = []
    if variance.get("txn_id") and variance["txn_id"] in txns_by_id:
        records.append(_txn_detail(txns_by_id[variance["txn_id"]]))

    match_group_info = None
    if variance.get("match_group_id"):
        g = groups_by_id.get(variance["match_group_id"])
        if g:
            match_group_info = {
                "tier": g.get("tier"),
                "strategy": g.get("strategy"),
                "confidence": g.get("confidence"),
                "total_variance_paise": g.get("total_variance_paise"),
                "variance_components": g.get("variance_components"),
            }
        for tid in members_by_group.get(variance["match_group_id"], []):
            if tid in txns_by_id:
                records.append(_txn_detail(txns_by_id[tid]))

    context = {
        "variance_id": variance["id"],
        "variance_paise": variance["variance_paise"],
        "provisional_category": variance.get("category"),
        "match_group": match_group_info,
        "records": records,
    }
    assert_no_leak(context, where=f"variance {variance['id']} context")
    return context


def _user_prompt(contexts: list[dict]) -> str:
    return (
        f"Classify the following {len(contexts)} variance case(s). Each is independent "
        f"unless its own records say otherwise — do not assume cases relate to one another.\n\n"
        f"{json.dumps(contexts, indent=2, default=str)}"
    )


def _normalize_result(item: dict | None) -> dict:
    """Validates one model result. Anything malformed, out-of-enum, or
    missing is downgraded to unexplained/flag_for_human — the same hard
    rule the prompt asks the model to self-enforce, enforced again here
    in case it doesn't."""
    item = item or {}
    category = item.get("category")
    action = item.get("suggested_action")
    confidence = item.get("confidence")
    explanation = item.get("explanation")
    subcategory = item.get("subcategory")

    well_formed = (
        category in VALID_CATEGORIES
        and action in VALID_ACTIONS
        and isinstance(confidence, (int, float))
        and isinstance(explanation, str) and explanation.strip()
        and isinstance(subcategory, str)
    )

    if not well_formed:
        return {
            "category": "unexplained",
            "subcategory": "malformed_model_response",
            "confidence": 0.0,
            "explanation": (
                explanation.strip() if isinstance(explanation, str) and explanation.strip()
                else "Model response for this variance was missing or did not match the required format."
            ),
            "suggested_action": "flag_for_human",
            "model_raw": item,
        }

    confidence = max(0.0, min(1.0, float(confidence)))
    if category == "unexplained":
        confidence = min(confidence, UNEXPLAINED_CONFIDENCE_CEILING)

    return {
        "category": category,
        "subcategory": subcategory,
        "confidence": confidence,
        "explanation": explanation.strip(),
        "suggested_action": action,
        "model_raw": item,
    }


def _write_result(variance_id: str, result: dict, status: str) -> None:
    db.run_with_retry(
        lambda: db.get_client().table("variances").update({
            "category": result["category"],
            "subcategory": result["subcategory"],
            "confidence": result["confidence"],
            "explanation": result["explanation"],
            "suggested_action": result["suggested_action"],
            "model_raw": result["model_raw"],
            "status": status,
        }).eq("id", variance_id).execute()
    )


def _write_audit(batch_id: str, action: str, detail: dict) -> None:
    db.run_with_retry(
        lambda: db.get_client().table("audit_log").insert({
            "batch_id": batch_id, "actor": "explainer", "step": "variance_explainer",
            "action": action, "detail": detail,
        }).execute()
    )


def run_variance_explainer(batch_id: str) -> dict:
    """Explains every open variances row for a batch. Rows the model
    classifies as unexplained keep status='open' — nothing here forces
    a row closed that the model itself said it couldn't confidently
    resolve."""
    open_variances = _page(
        "variances", "id,match_group_id,txn_id,variance_paise,category,status", batch_id, status="open"
    )
    if not open_variances:
        return {
            "variances_considered": 0, "batches_sent": 0, "explained": 0,
            "still_open_unexplained": 0, "malformed_responses": 0,
            "total_latency_ms": 0.0, "total_tokens": 0,
        }

    txn_ids: set[str] = {v["txn_id"] for v in open_variances if v.get("txn_id")}
    group_ids: set[str] = {v["match_group_id"] for v in open_variances if v.get("match_group_id")}

    groups_by_id = {
        g["id"]: g for g in _fetch_by_ids(
            "match_groups", "id,tier,strategy,confidence,total_variance_paise,variance_components",
            list(group_ids),
        )
    }
    members_by_group = _fetch_group_members(list(group_ids))
    for ids in members_by_group.values():
        txn_ids.update(ids)

    txns = _fetch_by_ids("txns", ",".join(_TXN_DETAIL_COLUMNS), list(txn_ids))
    if txns:
        _assert_no_forbidden(txns[0].keys())
    txns_by_id = {t["id"]: t for t in txns}

    contexts = [build_context(v, txns_by_id, groups_by_id, members_by_group) for v in open_variances]

    stats = {
        "batches_sent": 0, "explained": 0, "still_open_unexplained": 0,
        "malformed_responses": 0, "total_latency_ms": 0.0, "total_tokens": 0,
    }

    for chunk in chunk_variances(contexts):
        variance_ids = [c["variance_id"] for c in chunk]
        usage: dict = {}
        try:
            raw = complete_json(
                SYSTEM_PROMPT, _user_prompt(chunk),
                _SCHEMA_HINT_TEMPLATE.format(n=len(chunk)),
                usage_out=usage,
            )
        except ByteplusError as exc:
            logger.error("variance batch (%d ids) failed: %s", len(chunk), exc)
            _write_audit(batch_id, "batch_failed", {
                "variance_ids": variance_ids, "error": str(exc),
                "latency_ms": usage.get("latency_ms"),
                "attempts": getattr(exc, "attempts", None),
            })
            continue

        results = raw.get("results") if isinstance(raw, dict) else None
        results_by_id = {}
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict) and item.get("variance_id"):
                    results_by_id[str(item["variance_id"])] = item

        for vid in variance_ids:
            normalized = _normalize_result(results_by_id.get(vid))
            if results_by_id.get(vid) is None:
                stats["malformed_responses"] += 1
            status = "explained" if normalized["category"] != "unexplained" else "open"
            _write_result(vid, normalized, status)
            if status == "explained":
                stats["explained"] += 1
            else:
                stats["still_open_unexplained"] += 1

        stats["batches_sent"] += 1
        stats["total_latency_ms"] += usage.get("latency_ms") or 0.0
        stats["total_tokens"] += usage.get("total_tokens") or 0

        _write_audit(batch_id, "batch_explained", {
            "variance_ids": variance_ids,
            "latency_ms": round(usage.get("latency_ms") or 0.0, 1),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "provider": usage.get("provider"),
            "provider_model": usage.get("provider_model"),
            "fallback": usage.get("fallback"),
            "attempts": usage.get("attempts"),
        })

    return {
        "variances_considered": len(open_variances),
        "batches_sent": stats["batches_sent"],
        "explained": stats["explained"],
        "still_open_unexplained": stats["still_open_unexplained"],
        "malformed_responses": stats["malformed_responses"],
        "total_latency_ms": round(stats["total_latency_ms"], 1),
        "total_tokens": stats["total_tokens"],
    }

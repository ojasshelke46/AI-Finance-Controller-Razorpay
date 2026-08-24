"""Second pass over the explainer: grade the explanations it produced.

The matcher is graded by eval/scorer.py against ground truth. The
explainer cannot be graded that way — there is no truth_group for
"why does this variance exist". So it is graded the way a human
controller would grade a junior's work: hand a critic the ORIGINAL
record plus the explanation that was written about it, and ask whether
the explanation actually follows from that record.

Three checks per explanation, all of which must pass:
  grounded            the reasoning follows from the record data
  amounts_correct     every amount cited really appears in the record
  action_appropriate  the suggested_action fits the assigned category

Anything failing any check has its status reset to 'open' and its
category set to 'unexplained'. A confident-sounding explanation that
the data does not support is more dangerous than no explanation at all
— it invites a human to sign off on a number nobody actually verified.
So the failure direction is deliberately conservative: a malformed or
unparseable critic verdict is treated as a FAIL, not a pass, because
"could not verify" and "verified good" must never collapse into the
same outcome.

Two independence notes, since this module's whole value is that its
verdict means something:

  1. The critic is a SEPARATE call with a separate system prompt. It
     never sees the explainer's system prompt, its confidence score, or
     its own earlier verdicts on other rows — only the record and the
     claim made about it.

  2. Alongside the critic, this module runs a cheap DETERMINISTIC
     amount check: pull every number out of the explanation text and
     confirm it appears in the record (as paise, or as rupees to two
     decimals). That is not the graded metric — the spec asks for the
     critic's judgement — but it is reported next to it, because a
     critic that rubber-stamps everything is exactly the failure mode
     an LLM grader is prone to, and this is the one signal in the
     module that no model can talk its way past.

Uses lib.byteplus.complete_json exclusively, same as every other
BytePlus consumer in the project.

=====================================================================
 THIS MODULE MUST NEVER READ truth_group OR is_noise.
=====================================================================
Same rule as the matching tiers and the explainer. eval/scorer.py is
the single deliberate exception in this codebase; this module is not.
A critic that could see the answer key would be grading against truth
rather than against groundedness, which is a different question from
the one being asked here — and no production system has a truth_group
column for a critic to lean on.
"""

import json
import logging
import random
import re
from decimal import Decimal

from lib import db
from lib.byteplus import ByteplusError, complete_json
from explain.variance_explainer import (
    FORBIDDEN_COLUMNS,
    UNEXPLAINED_CONFIDENCE_CEILING,
    _TXN_DETAIL_COLUMNS,
    _assert_no_forbidden,
    _fetch_by_ids,
    _fetch_group_members,
    _page,
    build_context,
)

logger = logging.getLogger("eval.explanation_audit")

DEFAULT_SAMPLE_SIZE = 30
CRITIC_BATCH_SIZE = 5  # small: the critic should not carry six cases' reasoning at once
SAMPLE_SEED = 20260823  # fixed so a rerun grades the same rows unless the pool changes

_assert_no_forbidden(_TXN_DETAIL_COLUMNS)

CRITIC_SYSTEM_PROMPT = """You are an audit reviewer for a payment reconciliation
system. Another model was shown a reconciliation variance (a discrepancy
between a payment gateway, a bank statement, and an internal ledger) and
wrote an explanation of it. Your job is NOT to explain the variance
yourself. Your job is to check the explanation that was written.

You are given, for each case: the full record data (every transaction
involved, with its amounts in paise, dates, references, and raw source
payload), and the claim that was made about it (category, subcategory,
explanation text, suggested action).

Judge exactly three things:

  grounded            Does the explanation follow from the record data
                      shown? An explanation is NOT grounded if it asserts
                      a cause, a fee, a duplicate, a refund, or a timing
                      effect that the record does not actually evidence,
                      or if it describes a relationship between records
                      that is not present. Generic filler that could have
                      been written about any variance is NOT grounded.

  amounts_correct     Is every amount cited in the explanation actually
                      present in, or correctly derived by arithmetic
                      from, the record? Check the arithmetic yourself.
                      Amounts are in paise; an explanation may quote the
                      same figure in rupees (100 paise = 1 rupee) and
                      that is fine. If the explanation states a
                      subtraction, sum, or difference, verify it. A
                      single wrong or invented figure means false.

  action_appropriate  Does the suggested_action make sense for the
                      category assigned? For example: writing off a
                      large unexplained bank credit is not appropriate;
                      auto_accept on a case the explanation itself calls
                      uncertain is not appropriate; booking a genuine
                      gateway fee to a fee account is appropriate.

Be strict and be specific. You are the last check before a human is
told this case is settled, so a plausible-sounding but unverifiable
explanation must fail rather than pass. If you cannot confirm something
from the record in front of you, that is a failure, not a benefit of
the doubt — do not assume data exists that you were not shown.

When any check fails, "issue" must state concretely what is wrong (name
the specific amount, claim, or mismatch). When all three pass, "issue"
must be null."""

_CRITIC_SCHEMA_TEMPLATE = """{{
  "results": [
    {{
      "variance_id": "<must exactly match one of the input variance_id values, as a string>",
      "grounded": true,
      "amounts_correct": true,
      "action_appropriate": true,
      "issue": "concrete description of what is wrong, or null if all three checks pass"
    }}
  ]
}}
"results" must contain exactly {n} objects, one per input case, in any order."""


# ---------------------------------------------------------------------
# deterministic amount cross-check (not the graded metric — see docstring)
# ---------------------------------------------------------------------

# Bounded on both sides so digit runs inside an identifier
# ("txn d7e829fa") are never read as a cited figure.
_NUMBER_RE = re.compile(r"(?<![0-9A-Za-z])\d[\d,]*(?:\.\d+)?(?![0-9A-Za-z])")
# Dates are legitimately cited by an explanation ("settled on 2026-08-24")
# and are not money claims. Strip them before scanning, or the check
# reports the year as an invented figure.
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}[/-]\d{2}[/-]\d{2,4}")
_YEAR_RANGE = (1900, 2100)
# Bare small integers in an explanation are usually counts ("3 sources",
# "2 records"), dates, or tier numbers rather than money. Only treat a
# number as a money claim if it is big enough to be a real figure or is
# written with a decimal / thousands separator.
_MONEY_MIN_BARE = 100


def _record_amount_universe(context: dict) -> set[Decimal]:
    """Every paise figure the explanation could legitimately cite: each
    record's own amounts, plus the pairwise sums and differences a
    correct explanation would derive from them."""
    base: set[int] = set()
    if context.get("variance_paise") is not None:
        base.add(int(context["variance_paise"]))
    mg = context.get("match_group") or {}
    if mg.get("total_variance_paise") is not None:
        base.add(int(mg["total_variance_paise"]))
    for comp in (mg.get("variance_components") or {}).values():
        if isinstance(comp, int):
            base.add(comp)

    per_record: set[int] = set()
    for rec in context.get("records", []):
        for key in ("amount_paise", "fee_paise", "tax_paise", "net_paise"):
            v = rec.get(key)
            if isinstance(v, int):
                per_record.add(v)

    universe = base | per_record
    derived: set[int] = set()
    ordered = sorted(per_record)
    for i, a in enumerate(ordered):
        for b in ordered[i:]:
            derived.add(a + b)
            derived.add(abs(a - b))
    universe |= derived

    out: set[Decimal] = set()
    for paise in universe:
        out.add(Decimal(paise))          # quoted as paise
        out.add(Decimal(paise) / 100)    # quoted as rupees
        out.add(Decimal(abs(paise)))
        out.add(Decimal(abs(paise)) / 100)
    return out


def deterministic_amount_check(context: dict, explanation: str) -> dict:
    """Pull the money-looking numbers out of the explanation text and
    check each one against the record. Returns which figures matched and
    which did not — a purely mechanical signal, no model involved."""
    universe = _record_amount_universe(context)
    cited: list[str] = []
    unmatched: list[str] = []

    text = _DATE_RE.sub(" ", explanation or "")
    for token in _NUMBER_RE.findall(text):
        cleaned = token.rstrip(",").replace(",", "")
        if not cleaned:
            continue
        try:
            value = Decimal(cleaned)
        except Exception:
            continue
        looks_like_money = ("," in token) or ("." in token) or value >= _MONEY_MIN_BARE
        if not looks_like_money:
            continue
        # A bare four-digit year is a date reference, not an amount —
        # unless the record actually contains that figure as money.
        is_bare_year = (
            "." not in token and "," not in token
            and len(cleaned) == 4
            and _YEAR_RANGE[0] <= int(cleaned) <= _YEAR_RANGE[1]
            and Decimal(cleaned) not in universe
        )
        if is_bare_year:
            continue
        cited.append(token)
        if value not in universe:
            unmatched.append(token)

    return {
        "cited_figures": cited,
        "unmatched_figures": unmatched,
        "cites_any_amount": bool(cited),
        "all_cited_found": bool(cited) and not unmatched,
    }


# ---------------------------------------------------------------------
# sampling + critic
# ---------------------------------------------------------------------

def sample_explained(batch_id: str, sample_size: int) -> list[dict]:
    """A fixed-seed random sample of explained rows. Random rather than
    the first N by id, so the grade reflects the whole queue and not
    whichever cases happened to sort first; seeded so a rerun grades the
    same rows."""
    explained = _page(
        "variances",
        "id,match_group_id,txn_id,variance_paise,category,subcategory,confidence,"
        "explanation,suggested_action,status,model_raw",
        batch_id,
        status="explained",
    )
    explained = [v for v in explained if (v.get("explanation") or "").strip()]
    if len(explained) <= sample_size:
        return explained
    return random.Random(SAMPLE_SEED).sample(explained, sample_size)


def build_audit_contexts(batch_id: str, variances: list[dict]) -> list[tuple[dict, dict]]:
    """Rebuilds the exact record context the explainer was given, and
    pairs it with the claim it made. Reuses variance_explainer's own
    context builder so the critic grades against the same view of the
    data, not a differently-assembled one."""
    txn_ids = {v["txn_id"] for v in variances if v.get("txn_id")}
    group_ids = {v["match_group_id"] for v in variances if v.get("match_group_id")}

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

    paired = []
    for v in variances:
        context = build_context(v, txns_by_id, groups_by_id, members_by_group)
        claim = {
            "variance_id": v["id"],
            "category": v.get("category"),
            "subcategory": v.get("subcategory"),
            "explanation": v.get("explanation"),
            "suggested_action": v.get("suggested_action"),
        }
        paired.append((context, claim))
    return paired


def _critic_prompt(pairs: list[tuple[dict, dict]]) -> str:
    cases = [
        {
            "variance_id": ctx["variance_id"],
            "record_data": {k: v for k, v in ctx.items() if k != "variance_id"},
            "claim_made_about_it": {k: v for k, v in claim.items() if k != "variance_id"},
        }
        for ctx, claim in pairs
    ]
    return (
        f"Review the following {len(cases)} independent case(s). For each, check the "
        f"claim against the record data.\n\n"
        f"{json.dumps(cases, indent=2, default=str)}"
    )


def _normalize_verdict(item: dict | None) -> dict:
    """A verdict must be explicitly, unambiguously positive on all three
    checks to count as a pass. Missing, malformed, or non-boolean output
    fails — 'could not verify' is not 'verified'."""
    if not isinstance(item, dict):
        return {
            "grounded": False, "amounts_correct": False, "action_appropriate": False,
            "issue": "critic returned no usable verdict for this variance",
            "_malformed": True,
        }

    def flag(key: str) -> bool:
        return item.get(key) is True

    issue = item.get("issue")
    if not isinstance(issue, str) or not issue.strip():
        issue = None

    verdict = {
        "grounded": flag("grounded"),
        "amounts_correct": flag("amounts_correct"),
        "action_appropriate": flag("action_appropriate"),
        "issue": issue,
        "_malformed": not all(isinstance(item.get(k), bool)
                              for k in ("grounded", "amounts_correct", "action_appropriate")),
    }
    if verdict["_malformed"] and verdict["issue"] is None:
        verdict["issue"] = "critic verdict fields were missing or not boolean"
    return verdict


def _passed(verdict: dict) -> bool:
    return (
        verdict["grounded"]
        and verdict["amounts_correct"]
        and verdict["action_appropriate"]
    )


# ---------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------

def _reset_to_open(variance: dict, verdict: dict, det: dict) -> None:
    """Demote a failed explanation. The explanation TEXT is deliberately
    kept so a human can see what was rejected and why; what changes is
    that the system stops calling it settled."""
    model_raw = variance.get("model_raw")
    if not isinstance(model_raw, dict):
        model_raw = {"prior_model_raw": model_raw}
    model_raw = dict(model_raw)
    model_raw["grounding_audit"] = {
        "grounded": verdict["grounded"],
        "amounts_correct": verdict["amounts_correct"],
        "action_appropriate": verdict["action_appropriate"],
        "issue": verdict["issue"],
        "deterministic_amount_check": det,
        "rejected_category": variance.get("category"),
        "rejected_subcategory": variance.get("subcategory"),
    }

    confidence = variance.get("confidence")
    try:
        confidence = min(float(confidence), UNEXPLAINED_CONFIDENCE_CEILING)
    except (TypeError, ValueError):
        confidence = 0.0

    db.run_with_retry(
        lambda: db.get_client().table("variances").update({
            "category": "unexplained",
            "subcategory": "failed_grounding_audit",
            "confidence": confidence,
            "status": "open",
            "model_raw": model_raw,
        }).eq("id", variance["id"]).execute()
    )


def write_grounding_pct(batch_id: str, pct: float) -> str:
    """Writes the grade onto the batch's most recent run_scores row. If
    the batch has none (the scorer never ran for it), inserts a row
    carrying just this metric rather than silently dropping it."""
    existing = db.run_with_retry(
        lambda: db.get_client().table("run_scores").select("id")
        .eq("batch_id", batch_id).order("run_at", desc=True).limit(1).execute()
    ).data

    if existing:
        row_id = existing[0]["id"]
        db.run_with_retry(
            lambda: db.get_client().table("run_scores")
            .update({"explanation_grounding_pct": pct}).eq("id", row_id).execute()
        )
        return row_id

    inserted = db.run_with_retry(
        lambda: db.get_client().table("run_scores")
        .insert({"batch_id": batch_id, "explanation_grounding_pct": pct}).execute()
    ).data[0]
    return inserted["id"]


def _write_audit(batch_id: str, action: str, detail: dict) -> None:
    db.run_with_retry(
        lambda: db.get_client().table("audit_log").insert({
            "batch_id": batch_id, "actor": "scorer", "step": "explanation_audit",
            "action": action, "detail": detail,
        }).execute()
    )


# ---------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------

def run_explanation_audit(batch_id: str, sample_size: int = DEFAULT_SAMPLE_SIZE) -> dict:
    sampled = sample_explained(batch_id, sample_size)
    if not sampled:
        return {
            "sampled": 0, "graded": 0, "passed": 0, "failed": 0,
            "explanation_grounding_pct": None, "critic_calls": 0,
            "malformed_verdicts": 0, "reset_to_open": 0,
            "total_latency_ms": 0.0, "total_tokens": 0,
            "failures": [], "deterministic": {},
        }

    pairs = build_audit_contexts(batch_id, sampled)
    by_id = {v["id"]: v for v in sampled}
    ctx_by_id = {ctx["variance_id"]: ctx for ctx, _ in pairs}

    verdicts: dict[str, dict] = {}
    stats = {"critic_calls": 0, "malformed_verdicts": 0,
             "total_latency_ms": 0.0, "total_tokens": 0}

    for i in range(0, len(pairs), CRITIC_BATCH_SIZE):
        chunk = pairs[i:i + CRITIC_BATCH_SIZE]
        ids = [ctx["variance_id"] for ctx, _ in chunk]
        usage: dict = {}
        try:
            raw = complete_json(
                CRITIC_SYSTEM_PROMPT, _critic_prompt(chunk),
                _CRITIC_SCHEMA_TEMPLATE.format(n=len(chunk)),
                usage_out=usage,
            )
        except ByteplusError as exc:
            # A failed critic call is not a pass. Every row in the chunk
            # is graded as unverified and demoted.
            logger.error("critic batch (%d ids) failed: %s", len(chunk), exc)
            for vid in ids:
                verdicts[vid] = _normalize_verdict(None)
                verdicts[vid]["issue"] = f"critic call failed: {exc}"
                stats["malformed_verdicts"] += 1
            _write_audit(batch_id, "critic_batch_failed", {
                "variance_ids": ids, "error": str(exc),
                "latency_ms": usage.get("latency_ms"),
            })
            continue

        results = raw.get("results") if isinstance(raw, dict) else None
        results_by_id = {}
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict) and item.get("variance_id"):
                    results_by_id[str(item["variance_id"])] = item

        for vid in ids:
            verdict = _normalize_verdict(results_by_id.get(vid))
            if verdict["_malformed"]:
                stats["malformed_verdicts"] += 1
            verdicts[vid] = verdict

        stats["critic_calls"] += 1
        stats["total_latency_ms"] += usage.get("latency_ms") or 0.0
        stats["total_tokens"] += usage.get("total_tokens") or 0

        _write_audit(batch_id, "critic_batch_graded", {
            "variance_ids": ids,
            "latency_ms": round(usage.get("latency_ms") or 0.0, 1),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "verdicts": {vid: {k: verdicts[vid][k] for k in
                               ("grounded", "amounts_correct", "action_appropriate", "issue")}
                         for vid in ids},
        })

    passed = 0
    failed = 0
    reset = 0
    failures: list[dict] = []
    det_all_found = 0
    det_cites_amount = 0
    det_disagreements: list[dict] = []

    for vid, verdict in verdicts.items():
        variance = by_id[vid]
        det = deterministic_amount_check(ctx_by_id[vid], variance.get("explanation") or "")
        if det["cites_any_amount"]:
            det_cites_amount += 1
        if det["all_cited_found"]:
            det_all_found += 1

        ok = _passed(verdict)
        if ok:
            passed += 1
            # The critic said the amounts are right but the mechanical
            # check found a figure that is not in the record. Worth
            # surfacing: it is the signature of a rubber-stamping critic.
            if det["cited_figures"] and not det["all_cited_found"]:
                det_disagreements.append({
                    "variance_id": vid,
                    "unmatched_figures": det["unmatched_figures"],
                    "explanation": variance.get("explanation"),
                })
        else:
            failed += 1
            failures.append({
                "variance_id": vid,
                "category": variance.get("category"),
                "suggested_action": variance.get("suggested_action"),
                "explanation": variance.get("explanation"),
                "grounded": verdict["grounded"],
                "amounts_correct": verdict["amounts_correct"],
                "action_appropriate": verdict["action_appropriate"],
                "issue": verdict["issue"],
                "deterministic_amount_check": det,
            })
            _reset_to_open(variance, verdict, det)
            reset += 1

    graded = len(verdicts)
    pct = round(100.0 * passed / graded, 2) if graded else None
    if pct is not None:
        write_grounding_pct(batch_id, pct)

    _write_audit(batch_id, "audit_complete", {
        "sampled": len(sampled), "graded": graded, "passed": passed,
        "failed": failed, "reset_to_open": reset,
        "explanation_grounding_pct": pct,
        "critic_calls": stats["critic_calls"],
        "malformed_verdicts": stats["malformed_verdicts"],
        "total_tokens": stats["total_tokens"],
    })

    return {
        "sampled": len(sampled),
        "graded": graded,
        "passed": passed,
        "failed": failed,
        "explanation_grounding_pct": pct,
        "critic_calls": stats["critic_calls"],
        "malformed_verdicts": stats["malformed_verdicts"],
        "reset_to_open": reset,
        "total_latency_ms": round(stats["total_latency_ms"], 1),
        "total_tokens": stats["total_tokens"],
        "failures": failures,
        "deterministic": {
            "cites_any_amount": det_cites_amount,
            "all_cited_figures_found_in_record": det_all_found,
            "critic_passed_but_figure_not_in_record": det_disagreements,
        },
    }

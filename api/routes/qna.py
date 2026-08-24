"""POST /qna/{batch_id} — ask a question about a reconciliation run.

Two design decisions carry this endpoint.

1. Context is BUILT BY QUERYING, not by dumping rows. A reconciliation
   run holds thousands of txns; pasting them into a prompt would blow
   the window, cost a fortune, and bury the answer. Instead four
   targeted queries produce the figures a controller actually asks
   about — the run's score, the shape of the variance queue by
   category, the biggest open items, and which tier did the matching —
   rendered into roughly 2000 tokens of plain text.

2. The grounding guard is IN CODE, NOT IN THE PROMPT. Asking a model
   nicely not to invent figures reduces invented figures; it does not
   eliminate them, and there is no way to tell from the output which
   run got unlucky. So every number in the answer is extracted with a
   regex and checked against the numbers in the context that was
   supplied. A figure that cannot be traced means the answer is not
   returned at all — one regeneration, then an honest refusal.

   The refusal is the point. A reconciliation tool that shows a
   confident wrong number is worse than one that says it cannot answer,
   because the wrong number gets copied into a ledger and the refusal
   gets escalated to a human.

   To keep the guard strict without making it unusable, every amount is
   rendered into the context in BOTH paise and rupee form, so a model
   quoting either one matches exactly and never has to convert.
"""

import logging
import re
from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from lib import db
from lib.byteplus import ByteplusError, complete_text
from lib.money import paise_to_rupee_string

logger = logging.getLogger("routes.qna")

router = APIRouter(prefix="/qna", tags=["qna"])

_PAGE_SIZE = 1000
TOP_VARIANCE_COUNT = 5
CONTEXT_TOKEN_BUDGET = 2000
_CHARS_PER_TOKEN = 4  # rough, but the budget it enforces is rough too

SYSTEM_PROMPT = """You are a reconciliation analyst answering questions about
one payment reconciliation run (Razorpay gateway, bank statement, and
internal ledger). You are given a set of figures computed from that run.

Rules:
- Answer ONLY from the figures provided. They are the complete set of
  facts available to you.
- Cite the specific amounts and counts your answer depends on, quoted
  EXACTLY as they appear in the figures above — same digits, same
  formatting. Do not round, rescale, reformat, or convert between paise
  and rupees; both forms are already given where they apply.
- Do not calculate new numbers. If a question needs a figure that is not
  listed, that figure is not available to you.
- If the figures cannot answer the question — a different time period, a
  different batch, an individual customer, anything not present — say so
  plainly in one or two sentences and state what is missing. Do not
  estimate, do not extrapolate, and do not offer a plausible number as
  if it were derived from the data.

Answer in at most four sentences, plain language, no markdown."""

REFUSAL_MESSAGE = (
    "The system could not produce a verified answer to that question. A draft "
    "answer was generated but it cited figures that could not be traced back to "
    "the reconciliation data for this batch, so it was withheld rather than shown."
)


# ---------------------------------------------------------------------
# request / response
# ---------------------------------------------------------------------

class QnARequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


# ---------------------------------------------------------------------
# figure extraction (shared by context and guard)
# ---------------------------------------------------------------------

# Bounded on both sides so digit runs inside an identifier
# ("txn d7e829fa") are never read as a cited figure.
_NUMBER_RE = re.compile(r"(?<![0-9A-Za-z])\d[\d,]*(?:\.\d+)?(?![0-9A-Za-z])")
# Dates are legitimately quoted and are not figures to trace.
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}[/-]\d{2}[/-]\d{2,4}")
_YEAR_RANGE = (1900, 2100)


def extract_figures(text: str) -> set[Decimal]:
    """Every number in the text, as an exact Decimal. Dates are stripped
    first so a year is never mistaken for an amount."""
    out: set[Decimal] = set()
    for token in _NUMBER_RE.findall(_DATE_RE.sub(" ", text or "")):
        cleaned = token.rstrip(",").replace(",", "")
        if not cleaned:
            continue
        try:
            out.add(Decimal(cleaned))
        except Exception:  # noqa: BLE001
            continue
    return out


def _is_bare_year(token: str) -> bool:
    cleaned = token.rstrip(",").replace(",", "")
    return (
        "." not in token and "," not in token
        and len(cleaned) == 4
        and cleaned.isdigit()
        and _YEAR_RANGE[0] <= int(cleaned) <= _YEAR_RANGE[1]
    )


def ungrounded_figures(answer: str, context: str) -> list[str]:
    """Figures cited in the answer that do not appear in the context.

    Deliberately strict: EVERY number is checked, not only the ones that
    look like money. A fabricated count ("14 variances are open") misleads
    a controller exactly as badly as a fabricated amount, and since the
    context contains every count the answer could legitimately use,
    strictness costs nothing that should have been said.

    Trailing-zero differences are not treated as mismatches — Decimal
    comparison is by value, so 97.48 and 97.480 are the same figure.
    """
    allowed = extract_figures(context)
    bad: list[str] = []
    for token in _NUMBER_RE.findall(_DATE_RE.sub(" ", answer or "")):
        if _is_bare_year(token):
            continue
        cleaned = token.rstrip(",").replace(",", "")
        if not cleaned:
            continue
        try:
            value = Decimal(cleaned)
        except Exception:  # noqa: BLE001
            continue
        if value not in allowed:
            bad.append(token)
    return bad


# ---------------------------------------------------------------------
# context assembly — four targeted queries, not a dump
# ---------------------------------------------------------------------

def _page(table: str, columns: str, batch_id: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = db.run_with_retry(
            lambda o=offset: db.get_client().table(table).select(columns)
            .eq("batch_id", batch_id).order("id").range(o, o + _PAGE_SIZE - 1).execute()
        ).data
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return rows


def _money(paise: int) -> str:
    """Both forms, so the model never has to convert and the guard can
    stay an exact match either way."""
    sign = "-" if paise < 0 else ""
    return f"{sign}Rs {paise_to_rupee_string(int(paise))} ({int(paise)} paise)"


def fetch_run_score(batch_id: str) -> dict | None:
    rows = db.run_with_retry(
        lambda: db.get_client().table("run_scores").select("*")
        .eq("batch_id", batch_id).order("run_at", desc=True).limit(1).execute()
    ).data
    return rows[0] if rows else None


def fetch_variance_summary(batch_id: str) -> tuple[list[dict], list[dict]]:
    """Counts and summed value grouped by category, plus the largest open
    variances. One read of the queue serves both — grouping happens here
    because PostgREST has no GROUP BY."""
    rows = _page(
        "variances",
        "id,variance_paise,category,status,explanation,suggested_action,confidence",
        batch_id,
    )

    grouped: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"count": 0, "total_paise": 0}
    )
    for r in rows:
        key = (r.get("category") or "uncategorised", r.get("status") or "unknown")
        g = grouped[key]
        g["count"] += 1
        g["total_paise"] += int(r.get("variance_paise") or 0)

    summary = [
        {"category": cat, "status": status, **vals}
        for (cat, status), vals in grouped.items()
    ]
    summary.sort(key=lambda d: abs(d["total_paise"]), reverse=True)

    open_rows = [r for r in rows if (r.get("status") or "") == "open"]
    open_rows.sort(key=lambda r: abs(int(r.get("variance_paise") or 0)), reverse=True)
    return summary, open_rows[:TOP_VARIANCE_COUNT]


def _member_counts_by_group(group_ids: list[str]) -> dict[str, int]:
    """Counts actual match_members rows rather than trusting the
    denormalised member_count column on match_groups.

    Not paranoia: on a real batch the two disagree. Tier 4 can absorb an
    existing group into a settlement, which adds match_members rows
    without updating the absorbing group's member_count, so the column
    undercounts. An answer built on the stale column would be traceable
    to the context and still wrong — exactly the failure the grounding
    guard cannot catch, because the guard verifies provenance, not
    truth. The fix belongs here, at the source of the figure.

    Fetched by group id in chunks rather than by paging the whole table:
    match_members has no batch_id, so an unfiltered scan reads every
    membership row in the database and gets slower with every batch ever
    run.
    """
    counts: dict[str, int] = defaultdict(int)
    for i in range(0, len(group_ids), 100):
        chunk = group_ids[i:i + 100]
        offset = 0
        while True:
            page = db.run_with_retry(
                lambda c=chunk, o=offset: db.get_client().table("match_members")
                .select("id,match_group_id").in_("match_group_id", c)
                .order("id").range(o, o + _PAGE_SIZE - 1).execute()
            ).data
            for m in page:
                counts[m["match_group_id"]] += 1
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
    return counts


def fetch_tier_breakdown(batch_id: str) -> list[dict]:
    rows = _page("match_groups", "id,tier,strategy,member_count,total_variance_paise", batch_id)
    member_counts = _member_counts_by_group([r["id"] for r in rows])

    grouped: dict[tuple[int, str], dict] = defaultdict(
        lambda: {"groups": 0, "members": 0, "variance_paise": 0}
    )
    for r in rows:
        key = (r.get("tier"), r.get("strategy") or "?")
        g = grouped[key]
        g["groups"] += 1
        g["members"] += member_counts.get(r["id"], 0)
        g["variance_paise"] += int(r.get("total_variance_paise") or 0)

    out = [{"tier": tier, "strategy": strategy, **vals}
           for (tier, strategy), vals in grouped.items()]
    out.sort(key=lambda d: (d["tier"] if d["tier"] is not None else 99))
    return out


def _pct(value) -> str:
    """A ratio rendered both as the stored decimal and as a percentage,
    since a question may be asked either way and the guard requires an
    exact match against whichever the model quotes."""
    if value is None:
        return "not recorded"
    d = Decimal(str(value))
    return f"{d} ({d * 100:.2f}%)"


def build_context(batch_id: str) -> str:
    score = fetch_run_score(batch_id)
    summary, top_open = fetch_variance_summary(batch_id)
    tiers = fetch_tier_breakdown(batch_id)

    lines: list[str] = [f"RECONCILIATION RUN — batch {batch_id}", ""]

    lines.append("RUN SCORE")
    if not score:
        lines.append("  no run_scores row recorded for this batch")
    else:
        lines.append(f"  total transactions ingested: {score.get('total_txns')}")
        lines.append(f"  transactions matched into a group: {score.get('matched_txns')}")
        lines.append(f"  match rate: {_pct(score.get('match_rate'))}")
        lines.append(f"  precision: {_pct(score.get('precision'))}")
        lines.append(f"  recall: {_pct(score.get('recall'))}")
        lines.append(f"  f1: {_pct(score.get('f1'))}")
        lines.append(f"  true positives: {score.get('true_positives')}, "
                     f"false positives: {score.get('false_positives')}, "
                     f"false negatives: {score.get('false_negatives')}")
        if score.get("unexplained_paise") is not None:
            lines.append(f"  unexplained value: {_money(score['unexplained_paise'])}")
        if score.get("variance_explained_pct") is not None:
            lines.append(f"  variance explained: {score['variance_explained_pct']}%")
        if score.get("explanation_grounding_pct") is not None:
            lines.append("  explanation grounding rate (share of sampled LLM explanations "
                         f"that passed an independent audit): {score['explanation_grounding_pct']}%")
        if score.get("wall_clock_seconds") is not None:
            lines.append(f"  wall clock: {score['wall_clock_seconds']} seconds")
    lines.append("")

    lines.append("VARIANCE QUEUE BY CATEGORY (count and summed value)")
    if not summary:
        lines.append("  the variance queue is empty for this batch")
    for s in summary:
        lines.append(f"  {s['category']} [{s['status']}]: {s['count']} variances, "
                     f"total {_money(s['total_paise'])}")
    lines.append("")

    lines.append(f"{TOP_VARIANCE_COUNT} LARGEST OPEN VARIANCES")
    if not top_open:
        lines.append("  no open variances")
    for i, v in enumerate(top_open, 1):
        lines.append(f"  {i}. {_money(v['variance_paise'])} — category {v.get('category')}"
                     f", suggested action {v.get('suggested_action')}")
        if v.get("explanation"):
            lines.append(f"     explanation: {v['explanation']}")
    lines.append("")

    lines.append("MATCHING TIER CONTRIBUTION")
    if not tiers:
        lines.append("  no match groups recorded for this batch")
    for t in tiers:
        lines.append(f"  tier {t['tier']} ({t['strategy']}): {t['groups']} groups, "
                     f"{t['members']} transactions, residual variance "
                     f"{_money(t['variance_paise'])}")

    text = "\n".join(lines)
    return _enforce_budget(text)


def _enforce_budget(text: str) -> str:
    """Trim from the end if the assembled context runs long. Sections are
    ordered most-answerable-first, so what gets cut is the least likely to
    be asked about — and a trimmed line is dropped whole, never truncated
    mid-number, which would leave a figure in the context that means
    nothing."""
    limit = CONTEXT_TOKEN_BUDGET * _CHARS_PER_TOKEN
    if len(text) <= limit:
        return text

    lines = text.split("\n")
    while lines and len("\n".join(lines)) > limit:
        lines.pop()
    lines.append("  [context truncated to fit the token budget]")
    logger.warning("qna context truncated to %d chars", len("\n".join(lines)))
    return "\n".join(lines)


# ---------------------------------------------------------------------
# endpoint
# ---------------------------------------------------------------------

def answer_question(batch_id: str, question: str) -> dict:
    context = build_context(batch_id)
    user_prompt = f"FIGURES FROM THIS RECONCILIATION RUN:\n\n{context}\n\nQUESTION: {question}"

    attempts: list[dict] = []
    for attempt in range(2):  # one generation, then one regeneration
        usage: dict = {}
        try:
            answer = complete_text(SYSTEM_PROMPT, user_prompt, usage_out=usage)
        except ByteplusError as exc:
            logger.error("qna generation failed: %s", exc)
            attempts.append({"attempt": attempt + 1, "error": str(exc)})
            continue

        answer = (answer or "").strip()
        bad = ungrounded_figures(answer, context)
        attempts.append({
            "attempt": attempt + 1,
            "ungrounded_figures": bad,
            "latency_ms": round(usage.get("latency_ms") or 0.0, 1),
            "total_tokens": usage.get("total_tokens"),
        })

        if not bad:
            return {
                "batch_id": batch_id,
                "question": question,
                "answer": answer,
                "verified": True,
                "attempts": attempts,
                "context_chars": len(context),
            }

        logger.warning("qna attempt %d cited untraceable figures %s — %s",
                       attempt + 1, bad, "regenerating" if attempt == 0 else "refusing")

    return {
        "batch_id": batch_id,
        "question": question,
        "answer": REFUSAL_MESSAGE,
        "verified": False,
        "attempts": attempts,
        "context_chars": len(context),
    }


@router.post("/{batch_id}")
def qna(batch_id: str, body: QnARequest):
    return answer_question(batch_id, body.question)

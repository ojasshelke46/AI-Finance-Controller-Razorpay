"""Shared Razorpay (test mode) client, plain httpx + HTTP basic auth over
the documented REST API. Endpoints/fields verified against live Razorpay
docs on 2026-08-22:
  https://razorpay.com/docs/api/payments/fetch-all-payments/
  https://razorpay.com/docs/api/settlements/fetch-all/
  https://razorpay.com/docs/api/settlements/fetch-with-id/
  https://razorpay.com/docs/api/settlements/fetch-recon/
"""

import httpx

from .config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

_BASE_URL = "https://api.razorpay.com/v1"
_PAGE_SIZE = 100


class RazorpayError(RuntimeError):
    """Raised when a Razorpay API call fails."""


def _client() -> httpx.Client:
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        raise RazorpayError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set")
    return httpx.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET), timeout=30.0)


def _get(path: str, params: dict) -> dict:
    with _client() as client:
        resp = client.get(f"{_BASE_URL}{path}", params=params)
    if resp.status_code >= 400:
        raise RazorpayError(f"Razorpay GET {path} returned HTTP {resp.status_code}: {resp.text}")
    return resp.json()


def _paginate(path: str, params: dict) -> list[dict]:
    """GET-all pagination via count/skip, as used by /payments, /settlements
    and /settlements/recon/combined."""
    items: list[dict] = []
    skip = 0
    while True:
        page = _get(path, {**params, "count": _PAGE_SIZE, "skip": skip})
        page_items = page.get("items", [])
        items.extend(page_items)
        if len(page_items) < _PAGE_SIZE:
            break
        skip += _PAGE_SIZE
    return items


def create_payment_link(
    amount_paise: int,
    description: str,
    *,
    currency: str = "INR",
    contact: str = "9000090000",
    email: str = "test@example.com",
    customer_name: str = "Test User",
) -> dict:
    """POST /v1/payment_links. Returns the created link, including
    short_url — the hosted checkout page to pay it."""
    body = {
        "amount": amount_paise,
        "currency": currency,
        "description": description,
        "customer": {"name": customer_name, "email": email, "contact": contact},
        "notify": {"sms": False, "email": False},
    }
    with _client() as client:
        resp = client.post(f"{_BASE_URL}/payment_links", json=body)
    if resp.status_code >= 400:
        raise RazorpayError(f"Razorpay POST /payment_links returned HTTP {resp.status_code}: {resp.text}")
    return resp.json()


def refund_payment(payment_id: str, *, amount_paise: int | None = None) -> dict:
    """POST /v1/payments/{id}/refund. Omit amount_paise for a full refund,
    pass it for a partial refund."""
    body = {}
    if amount_paise is not None:
        body["amount"] = amount_paise
    with _client() as client:
        resp = client.post(f"{_BASE_URL}/payments/{payment_id}/refund", json=body)
    if resp.status_code >= 400:
        raise RazorpayError(
            f"Razorpay POST /payments/{payment_id}/refund returned HTTP {resp.status_code}: {resp.text}"
        )
    return resp.json()


def ping() -> None:
    """Minimal authenticated call for health checks. Raises RazorpayError
    if the credentials or API are not working."""
    _get("/payments", {"count": 1})


def fetch_payments(from_ts: int, to_ts: int) -> list[dict]:
    """GET /v1/payments?from=&to=. from_ts/to_ts are unix seconds.
    Each item has: id, amount (paise), currency, status, method, email,
    contact, created_at (unix seconds)."""
    return _paginate("/payments", {"from": from_ts, "to": to_ts})


def fetch_settlements(from_ts: int, to_ts: int) -> list[dict]:
    """GET /v1/settlements?from=&to=. from_ts/to_ts are unix seconds.
    Each item has: id, entity ("settlement"), amount (paise), status,
    fees, tax, utr, created_at (unix seconds)."""
    return _paginate("/settlements", {"from": from_ts, "to": to_ts})


def fetch_settlement_recon(settlement_id: str) -> list[dict]:
    """Razorpay has no recon-by-settlement-id endpoint — /v1/settlements/recon/combined
    is scoped by year/month/day only, and each row carries its own
    settlement_id. So this: 1) fetches the settlement to read its
    created_at date, 2) pulls that day's combined recon, 3) filters to
    rows matching settlement_id.

    Each returned row has: entity_id, type, debit, credit, amount,
    currency, fee, tax, on_hold, settled, created_at, settled_at,
    settlement_id, description, notes, payment_id, settlement_utr,
    order_id, order_receipt, method, card_network, card_issuer,
    card_type, dispute_id."""
    settlement = _get(f"/settlements/{settlement_id}", {})
    created_at = settlement.get("created_at")
    if created_at is None:
        raise RazorpayError(f"Settlement {settlement_id} has no created_at to scope recon by")

    from datetime import datetime, timezone

    dt = datetime.fromtimestamp(created_at, tz=timezone.utc)
    recon_rows = _paginate(
        "/settlements/recon/combined",
        {"year": dt.year, "month": dt.month, "day": dt.day},
    )
    return [row for row in recon_rows if row.get("settlement_id") == settlement_id]

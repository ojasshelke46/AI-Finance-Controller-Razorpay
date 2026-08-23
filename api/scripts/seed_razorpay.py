"""Seed the connected Razorpay TEST MODE account with realistic activity:
a spread of successful card payments at varying amounts, a few failed
payments, and both a full and a partial refund — using Razorpay's own
test tooling, not invented data.

How it actually creates a payment (reverse-engineered against the live
test account on 2026-08-22, since Razorpay's public REST API has no
"create payment with card details" endpoint for un-onboarded accounts —
that's by design, PCI scope stays on Razorpay's hosted Checkout):

  1. POST /v1/payment_links -> a hosted Checkout page (short_url).
  2. Drive that page just far enough with a headless browser (contact
     number -> "Cards" -> card number/expiry/cvv -> submit) to capture
     the checkout's own POST to /v1/standard_checkout/payments/create/ajax,
     whose response carries {payment_id, request: {url, task_id}} for
     the next step. This is the only part that needs a browser.
  3. From there it's plain HTTP, no browser: POST to that authenticate
     URL returns an HTML page whose hidden form auto-posts to Razorpay's
     TEST-MODE-ONLY mock bank simulator (gateway "mocksharp"). POST that
     form to reach a real "Success / Failure" mock bank page, then POST
     its own form with success=S or success=F to deterministically
     resolve the payment either way.
  4. Refunds are the plain, documented POST /v1/payments/{id}/refund
     (full, or partial via an amount).

Every payment gets a real fee/tax structure computed by Razorpay itself
(visible in the printed summary and later in `raw` once ingested).

Run: cd api && source .venv/bin/activate && python -m scripts.seed_razorpay
"""

import json
import random
import time
from html.parser import HTMLParser

import httpx
from playwright.sync_api import sync_playwright

from lib.config import RAZORPAY_KEY_ID
from lib.razorpay_client import RazorpayError, create_payment_link, refund_payment

# Razorpay's documented test card for Indian payments (Visa, generic
# success card — https://razorpay.com/docs/payments/payments/test-card-details/).
# The mock bank page (step 3 above) is what actually decides success vs
# failure, so this single card is reused for both outcomes.
_CARD_NUMBER = "4100280000001007"
_CARD_EXPIRY = "1228"
_CARD_CVV = "123"
_CONTACT = "9000090000"


class _FormExtractor(HTMLParser):
    """Pulls every <form action=...> and its hidden <input name=value>
    pairs out of the plain HTML pages in Razorpay's test-mode auth flow."""

    def __init__(self):
        super().__init__()
        self.forms: list[dict] = []
        self._current: dict | None = None

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "form":
            self._current = {"action": attrs_d.get("action"), "inputs": {}}
            self.forms.append(self._current)
        elif tag == "input" and self._current is not None:
            name = attrs_d.get("name")
            if name:
                self._current["inputs"][name] = attrs_d.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self._current = None


def _extract_forms(html_text: str) -> list[dict]:
    parser = _FormExtractor()
    parser.feed(html_text)
    return parser.forms


def _drive_checkout_to_payment(short_url: str) -> dict:
    """Headless-browser step: fill contact + test card on the hosted
    Checkout page, submit, and capture the resulting create/ajax response
    (payment_id + the URL/task_id needed to continue over plain HTTP)."""
    captured: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(resp):
            if "standard_checkout/payments/create/ajax" in resp.url:
                try:
                    captured["body"] = resp.json()
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto(short_url, wait_until="load", timeout=30000)
        page.wait_for_timeout(2500)

        cf = next(f for f in page.frames if "checkout/public" in f.url)
        cf.fill('input[data-testid="contactNumber"]', _CONTACT)
        cf.click('button[data-testid="bottom-cta-button"]')
        page.wait_for_timeout(2500)

        cf = next(f for f in page.frames if "checkout/public" in f.url)
        cf.click("text=Cards")
        page.wait_for_timeout(1500)

        cf = next(f for f in page.frames if "checkout/public" in f.url)
        cf.fill('input[name="card.number"]', _CARD_NUMBER)
        cf.fill('input[name="card.expiry"]', _CARD_EXPIRY)
        cf.fill('input[name="card.cvv"]', _CARD_CVV)
        page.wait_for_timeout(400)
        cf.click('button[data-testid="bottom-cta-button"]')
        page.wait_for_timeout(3000)

        # RBI "save this card" consent sheet doesn't always appear.
        try:
            cf2 = next(f for f in page.frames if "checkout/public" in f.url)
            cf2.click("text=Maybe later", timeout=6000)
        except Exception:
            pass
        page.wait_for_timeout(3000)

        browser.close()

    if "body" not in captured or "payment_id" not in captured["body"]:
        raise RuntimeError(f"Checkout did not yield a payment_id: {captured}")
    return captured["body"]


def _resolve_payment(create_ajax_body: dict, outcome: str) -> str:
    """Plain-HTTP step: complete the test-mode mock-bank auth flow,
    choosing 'S' (success) or 'F' (failure). Returns the payment id."""
    payment_id = create_ajax_body["payment_id"]
    req = create_ajax_body["request"]  # {"url", "method", "task_id"}

    with httpx.Client(timeout=30.0) as client:
        auth_resp = client.post(req["url"], data={"task_id": req["task_id"], "key_id": RAZORPAY_KEY_ID})
        auth_forms = _extract_forms(auth_resp.text)
        form1 = next(
            f for f in auth_forms if f["action"] and "mocksharp/payment" in f["action"] and "submit" not in f["action"]
        )

        bank_resp = client.post(form1["action"], data=form1["inputs"])
        bank_forms = _extract_forms(bank_resp.text)
        submit_form = next(f for f in bank_forms if f["action"] and "mocksharp/payment/submit" in f["action"])
        submit_form["inputs"]["success"] = outcome

        client.post(submit_form["action"], data=submit_form["inputs"], follow_redirects=True)

    return payment_id


def seed_card_payment(amount_paise: int, description: str, outcome: str = "S") -> str:
    """Create one real Razorpay test-mode card payment and resolve it to
    'S' (captured) or 'F' (failed). Retries once on transient browser
    flakiness."""
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            link = create_payment_link(amount_paise, description)
            ajax_body = _drive_checkout_to_payment(link["short_url"])
            return _resolve_payment(ajax_body, outcome)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"  attempt {attempt + 1} failed for {description!r}: {exc}")
            time.sleep(2)
    raise RuntimeError(f"Could not seed payment {description!r}") from last_exc


def main():
    random.seed(42)
    summary: dict[str, list] = {"success": [], "failed": [], "refunded_full": [], "refunded_partial": []}

    success_amounts = [4900, 12000, 25000, 89900, 150000, 32500, 67800, 99900, 45000, 21000, 9900, 300000]
    failed_amounts = [15000, 42000, 8800]

    print(f"Seeding {len(success_amounts)} successful payments...")
    for i, amount in enumerate(success_amounts):
        pid = seed_card_payment(amount, f"seed success {i + 1}", outcome="S")
        print(f"  [{i + 1}/{len(success_amounts)}] captured {pid} amount_paise={amount}")
        summary["success"].append({"payment_id": pid, "amount_paise": amount})
        time.sleep(1)

    print(f"Seeding {len(failed_amounts)} failed payments...")
    for i, amount in enumerate(failed_amounts):
        pid = seed_card_payment(amount, f"seed failed {i + 1}", outcome="F")
        print(f"  [{i + 1}/{len(failed_amounts)}] failed {pid} amount_paise={amount}")
        summary["failed"].append({"payment_id": pid, "amount_paise": amount})
        time.sleep(1)

    print("Issuing refunds...")
    full_target = summary["success"][0]["payment_id"]
    refund_payment(full_target)
    summary["refunded_full"].append(full_target)
    print(f"  full refund on {full_target}")

    partial_target = summary["success"][1]["payment_id"]
    partial_amount = summary["success"][1]["amount_paise"] // 3
    refund_payment(partial_target, amount_paise=partial_amount)
    summary["refunded_partial"].append({"payment_id": partial_target, "amount_paise": partial_amount})
    print(f"  partial refund on {partial_target} amount_paise={partial_amount}")

    another_full_target = summary["success"][2]["payment_id"]
    refund_payment(another_full_target)
    summary["refunded_full"].append(another_full_target)
    print(f"  full refund on {another_full_target}")

    print("\n=== seed summary ===")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    try:
        main()
    except RazorpayError as exc:
        print(f"Razorpay API error: {exc}")
        raise

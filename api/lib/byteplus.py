"""Shared BytePlus Ark chat-completion helper.

Every later module that needs BytePlus should import complete_text /
complete_json from here — nothing re-implements a client.
"""

import json
import logging
import re
import time
from typing import Any

import httpx

from .config import BYTEPLUS_ARK_API_KEY, BYTEPLUS_ARK_BASE_URL, BYTEPLUS_ARK_MODEL

logger = logging.getLogger("lib.byteplus")

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

_RETRIES = 2  # retry twice on network error / 5xx, then give up
_RETRY_BASE_DELAY = 1.0


class ByteplusError(RuntimeError):
    """Raised when a BytePlus call fails after retries."""


class ByteplusParseError(ByteplusError):
    """Raised when complete_json can't parse the model's response.
    Carries the raw response text so it shows up in logs."""

    def __init__(self, message: str, raw_text: str):
        super().__init__(message)
        self.raw_text = raw_text


def _request(messages: list[dict[str, str]], *, timeout: float = 60.0) -> dict[str, Any]:
    if not BYTEPLUS_ARK_API_KEY:
        raise ByteplusError("BYTEPLUS_ARK_API_KEY is not set")

    url = f"{BYTEPLUS_ARK_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {BYTEPLUS_ARK_API_KEY}",
        "Content-Type": "application/json",
    }
    # Deliberately no response_format — Ark may not support it. Ask for JSON
    # in the prompt text instead (see complete_json).
    payload = {"model": BYTEPLUS_ARK_MODEL, "messages": messages}

    last_exc: Exception | None = None
    for attempt in range(_RETRIES + 1):
        start = time.monotonic()
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < _RETRIES:
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning("BytePlus network error (attempt %d/%d): %s — retrying in %.1fs",
                               attempt + 1, _RETRIES + 1, exc, delay)
                time.sleep(delay)
                continue
            raise ByteplusError(f"BytePlus request failed: {exc}") from exc

        latency_ms = (time.monotonic() - start) * 1000

        if resp.status_code >= 500:
            last_exc = ByteplusError(
                f"BytePlus returned HTTP {resp.status_code}. Raw response: {resp.text}"
            )
            if attempt < _RETRIES:
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning("BytePlus 5xx (attempt %d/%d): %s — retrying in %.1fs",
                               attempt + 1, _RETRIES + 1, resp.status_code, delay)
                time.sleep(delay)
                continue
            raise last_exc

        if resp.status_code >= 400:
            raise ByteplusError(
                f"BytePlus returned HTTP {resp.status_code}. Raw response: {resp.text}"
            )

        data = resp.json()
        usage = data.get("usage", {})
        logger.info(
            "BytePlus call ok: latency=%.0fms prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            latency_ms,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
        )
        return data

    assert last_exc is not None
    raise ByteplusError(str(last_exc))


def complete_text(system: str, user: str) -> str:
    """Single chat completion, returns the assistant message content."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    data = _request(messages)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise ByteplusError(
            f"Could not read content from BytePlus response ({exc}). Raw response: {data}"
        ) from exc


def complete_json(system: str, user: str, schema_hint: str) -> dict:
    """Chat completion that asks the model for JSON in the prompt text
    (no response_format param — Ark may not support it), then parses it.
    Raises ByteplusParseError (carrying the raw text) if parsing fails."""
    json_user = (
        f"{user}\n\n"
        f"Respond with ONLY a single JSON object matching this shape, no other text:\n"
        f"{schema_hint}\n"
        f"Do not wrap it in markdown code fences or add any explanation."
    )
    raw = complete_text(system, json_user)

    stripped = _FENCE_RE.sub("", raw).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ByteplusParseError(
            f"Failed to parse JSON from BytePlus response: {exc}", raw
        ) from exc

    if not isinstance(parsed, dict):
        raise ByteplusParseError(
            f"BytePlus response parsed but was not a JSON object (got {type(parsed).__name__})",
            raw,
        )
    return parsed

"""Shared chat-completion helper — NVIDIA -> BytePlus -> OpenRouter fallback.

Every later module that needs an LLM call should import complete_text /
complete_json from here — nothing re-implements a client, and nothing
outside this file knows there are three providers behind it.

Priority order (tried in sequence, first success wins):
  1. NVIDIA      nemotron-3.5-lightning — fast, non-reasoning
  2. BytePlus    Ark DeepSeek
  3. OpenRouter  MiniMax M3 (free tier)

A provider is only skipped in favor of the next one on: HTTP 429, HTTP
5xx (after its own retry is exhausted), a connection timeout (after its
own retry is exhausted), HTTP 401/403 (this provider's own credentials
are invalid/expired — not a malformed request), or an explicit
quota/credit-exhausted error body. Any OTHER 4xx (400, 404, 422, ...) is
a bug in what we sent, not something another provider can fix — it is
raised immediately and does NOT trigger fallback, so it stays visible
instead of being silently masked.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import (
    BYTEPLUS_ARK_API_KEY, BYTEPLUS_ARK_BASE_URL, BYTEPLUS_ARK_MODEL,
    NVIDIA_API_KEY, NVIDIA_BASE_URL, NVIDIA_MODEL,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
)

logger = logging.getLogger("lib.byteplus")

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

_RETRIES = 2  # retry twice on network error / 5xx / 429, then hand off to the next provider
_RETRY_BASE_DELAY = 1.0

# Substrings that mark an error body as quota/credit exhaustion rather
# than a malformed request — checked case-insensitively against the raw
# response text of a non-429 4xx.
_QUOTA_MARKERS = (
    "insufficient_quota", "insufficient quota", "quota exceeded",
    "out of credits", "out of credit", "credit balance",
    "credits exhausted", "insufficient credits", "insufficient credit",
    "exceeded your current quota",
)


class ByteplusError(RuntimeError):
    """Raised when every provider in the fallback chain has failed, or
    when a provider returned a genuine (non-fallback-eligible) error."""


class ByteplusParseError(ByteplusError):
    """Raised when complete_json can't parse the model's response.
    Carries the raw response text so it shows up in logs."""

    def __init__(self, message: str, raw_text: str):
        super().__init__(message)
        self.raw_text = raw_text


class _ProviderFailed(Exception):
    """Internal only: this provider failed in a way that should try the
    next one in the priority list. Never raised past _call_with_fallback."""


@dataclass(frozen=True)
class _Provider:
    name: str
    base_url: str
    model: str
    api_key: str


def _providers() -> list[_Provider]:
    # Built fresh on every call (not cached at import) so a test or
    # script that monkeypatches a module-level constant (e.g.
    # byteplus.BYTEPLUS_ARK_MODEL) is honored at call time.
    return [
        _Provider("nvidia", NVIDIA_BASE_URL, NVIDIA_MODEL, NVIDIA_API_KEY),
        _Provider("byteplus", BYTEPLUS_ARK_BASE_URL, BYTEPLUS_ARK_MODEL, BYTEPLUS_ARK_API_KEY),
        _Provider("openrouter", OPENROUTER_BASE_URL, OPENROUTER_MODEL, OPENROUTER_API_KEY),
    ]


def _is_quota_exhausted(resp: httpx.Response) -> bool:
    body = (resp.text or "").lower()
    return any(marker in body for marker in _QUOTA_MARKERS)


def _request_one(provider: _Provider, messages: list[dict[str, str]], *, timeout: float = 60.0) -> tuple[dict[str, Any], float]:
    """Single provider's HTTP call, with that provider's own retry for
    network errors / 5xx / 429. Returns (response_json, latency_ms).

    No response_format param — not every provider in this chain supports
    it. Ask for JSON in the prompt text instead (see complete_json).

    Thinking/reasoning is explicitly disabled for NVIDIA (see below) —
    every model in this chain is used for closed-schema classification,
    not open-ended reasoning, and nemotron-3.5-lightning in particular is
    a fast execution model, not a reasoning one. BytePlus and OpenRouter
    don't reason by default on this payload shape, so nothing extra is
    sent for them; NVIDIA does, and needs the explicit off-switch below.
    """
    if not provider.api_key:
        raise _ProviderFailed(f"{provider.name}: no API key configured")

    url = f"{provider.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": provider.model, "messages": messages}
    if provider.name == "nvidia":
        # Omitting this does NOT default to non-thinking on this endpoint —
        # verified live: nemotron-3.5-lightning reasons by default unless
        # told otherwise, burning ~10x the tokens on a hidden
        # reasoning_content field and occasionally leaving the real
        # `content` field empty (which then fails JSON parsing downstream
        # with no indication why). Explicit off-switch, not a style choice.
        payload["chat_template_kwargs"] = {"thinking": False}

    last_exc: Exception | None = None
    for attempt in range(_RETRIES + 1):
        start = time.monotonic()
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < _RETRIES:
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning("%s network error (attempt %d/%d): %s — retrying in %.1fs",
                               provider.name, attempt + 1, _RETRIES + 1, exc, delay)
                time.sleep(delay)
                continue
            raise _ProviderFailed(f"{provider.name}: request failed after retries: {exc}") from exc

        latency_ms = (time.monotonic() - start) * 1000

        if resp.status_code == 429 or resp.status_code >= 500:
            last_exc = RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
            if attempt < _RETRIES:
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning("%s HTTP %d (attempt %d/%d) — retrying in %.1fs",
                               provider.name, resp.status_code, attempt + 1, _RETRIES + 1, delay)
                time.sleep(delay)
                continue
            raise _ProviderFailed(
                f"{provider.name}: HTTP {resp.status_code} after retries. Raw response: {resp.text[:500]}"
            )

        if resp.status_code in (401, 403):
            # Invalid/expired/unauthorized credentials for THIS provider —
            # not a malformed request, so it's not the "bug in what we
            # sent" case. This provider simply cannot serve any request
            # right now; move on to the next one.
            raise _ProviderFailed(
                f"{provider.name}: auth failed (HTTP {resp.status_code}): {resp.text[:500]}"
            )

        if resp.status_code >= 400:
            if _is_quota_exhausted(resp):
                raise _ProviderFailed(
                    f"{provider.name}: quota/credit exhausted (HTTP {resp.status_code}): {resp.text[:500]}"
                )
            # Genuine 4xx (malformed request, bad schema, etc.): a bug in
            # what we sent. Must surface as-is, not get silently retried
            # against a different provider — that would hide the bug.
            raise ByteplusError(
                f"{provider.name} returned HTTP {resp.status_code}. Raw response: {resp.text}"
            )

        # A 200 is not proof of success. OpenRouter in particular answers
        # HTTP 200 with an error payload in the BODY — an upstream rate
        # limit or provider outage wearing a success status code. Read
        # that as this provider failing (retry it if the embedded code is
        # itself retryable, otherwise hand off), never as a malformed
        # success: raising "could not read content" there would surface a
        # rate limit as if it were a bug in our own parsing, and would
        # skip the rest of the chain that could have answered.
        data = resp.json()
        embedded = data.get("error")
        if isinstance(embedded, dict) or not data.get("choices"):
            embedded_code = embedded.get("code") if isinstance(embedded, dict) else None
            # Providers are inconsistent about whether this is 429 or "429".
            if isinstance(embedded_code, str) and embedded_code.isdigit():
                embedded_code = int(embedded_code)
            retryable = isinstance(embedded_code, int) and (
                embedded_code == 429 or embedded_code >= 500
            )
            detail = json.dumps(embedded)[:500] if embedded else "no choices in response"
            if retryable and attempt < _RETRIES:
                last_exc = RuntimeError(f"HTTP 200 with embedded error: {detail}")
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning("%s HTTP 200 with embedded error %s (attempt %d/%d) — retrying in %.1fs",
                               provider.name, embedded_code, attempt + 1, _RETRIES + 1, delay)
                time.sleep(delay)
                continue
            raise _ProviderFailed(
                f"{provider.name}: HTTP 200 but the body carried an error: {detail}"
            )

        usage = data.get("usage", {})
        logger.info(
            "%s call ok: latency=%.0fms prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            provider.name, latency_ms,
            usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"),
        )
        return data, latency_ms

    assert last_exc is not None
    raise _ProviderFailed(f"{provider.name}: {last_exc}")


def _call_with_fallback(messages: list[dict[str, str]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Tries providers in priority order, returns the first success as
    (response_json, meta). meta carries the traceability fields: which
    provider actually served the call, its model id, latency, and
    whether this was a fallback or the primary succeeding.

    A genuine 4xx (ByteplusError, not _ProviderFailed) propagates
    immediately with no further providers tried. If every provider is
    exhausted via a fallback-eligible failure, raises one aggregated
    ByteplusError listing what each provider returned.
    """
    providers = _providers()
    failures: list[str] = []
    attempts: list[dict[str, Any]] = []

    for i, provider in enumerate(providers):
        is_fallback = i > 0
        try:
            data, latency_ms = _request_one(provider, messages)
        except _ProviderFailed as exc:
            logger.warning(
                "provider failed: provider=%s model=%s fallback=%s reason=%s",
                provider.name, provider.model, is_fallback, exc,
            )
            failures.append(f"{provider.name} ({provider.model}): {exc}")
            attempts.append({
                "provider": provider.name, "model": provider.model,
                "outcome": "failed", "reason": str(exc),
            })
            continue

        logger.info(
            "provider served call: provider=%s model=%s latency_ms=%.0f fallback=%s",
            provider.name, provider.model, latency_ms, is_fallback,
        )
        attempts.append({
            "provider": provider.name, "model": provider.model,
            "outcome": "success", "latency_ms": round(latency_ms, 1),
        })
        return data, {
            "provider": provider.name,
            "model": provider.model,
            "latency_ms": latency_ms,
            "fallback": is_fallback,
            "attempts": attempts,
        }

    error = ByteplusError(
        f"All {len(providers)} providers failed. " + " | ".join(failures)
    )
    error.attempts = attempts
    raise error


def complete_text(system: str, user: str, *, usage_out: dict | None = None) -> str:
    """Single chat completion, returns the assistant message content.

    Pass a dict as usage_out to receive {latency_ms, prompt_tokens,
    completion_tokens, total_tokens, provider, provider_model, fallback,
    attempts} for the call — callers that need to log cost/latency/
    provenance (e.g. an audit trail) don't have to re-implement a client
    to get it. attempts is the full per-provider chain in try order —
    {provider, model, outcome, reason|latency_ms} for each — so a caller
    that logs it can show which providers were tried and which one
    actually answered, not just the final winner.
    Optional and additive: existing callers that don't pass it, or that
    only read the fields they already know about, see no change.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    start = time.monotonic()
    data, meta = _call_with_fallback(messages)
    if usage_out is not None:
        usage = data.get("usage", {})
        usage_out.update({
            "latency_ms": (time.monotonic() - start) * 1000,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "provider": meta["provider"],
            "provider_model": meta["model"],
            "fallback": meta["fallback"],
            "attempts": meta["attempts"],
        })
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise ByteplusError(
            f"Could not read content from {meta['provider']} response ({exc}). Raw response: {data}"
        ) from exc


def complete_json(system: str, user: str, schema_hint: str, *, usage_out: dict | None = None) -> dict:
    """Chat completion that asks the model for JSON in the prompt text
    (no response_format param — not every provider in the chain supports
    it), then parses it. Raises ByteplusParseError (carrying the raw
    text) if parsing fails."""
    json_user = (
        f"{user}\n\n"
        f"Respond with ONLY a single JSON object matching this shape, no other text:\n"
        f"{schema_hint}\n"
        f"Do not wrap it in markdown code fences or add any explanation."
    )
    raw = complete_text(system, json_user, usage_out=usage_out)

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

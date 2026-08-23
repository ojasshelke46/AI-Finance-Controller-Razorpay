"""Shared Supabase client. Everything that talks to Supabase goes through
get_client() / run_with_retry() here — nothing re-implements a client.
"""

import logging
import time
from functools import lru_cache
from typing import Callable, TypeVar

from supabase import Client, create_client

from .config import SUPABASE_SERVICE_KEY, SUPABASE_URL

logger = logging.getLogger("lib.db")

T = TypeVar("T")


@lru_cache
def get_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY not set in .env")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def run_with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
) -> T:
    """Run fn() with up to `attempts` tries and exponential backoff between
    them (base_delay, base_delay*2, base_delay*4, ...). Needed because a
    free-tier Supabase project can cold-start slowly and a transient
    timeout must not kill a run.
    """
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, retried below
            last_exc = exc
            if attempt < attempts - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "supabase call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1,
                    attempts,
                    exc,
                    delay,
                )
                time.sleep(delay)
    assert last_exc is not None
    raise last_exc

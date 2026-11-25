"""LLM interaction layer – LiteLLM caching, key-pool failover, simulation hook."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

# Ensure litellm uses local cost map (avoid network fetch on import)
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm
from litellm import Cache
from litellm.exceptions import (
    BadRequestError,
    RateLimitError,
    InternalServerError,
    ServiceUnavailableError,
)

from app.config import settings

logger = logging.getLogger(__name__)

# ── Caching ───────────────────────────────────────────────────────────────────
# LiteLLM built-in in-memory cache; cache key = model + messages (NOT api_key).
litellm.cache = Cache(type="local")
litellm.enable_cache = True
litellm.drop_params = True  # gracefully handle models that don't support all params

# Suppress noisy litellm logs
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)


# ── Failure simulation helpers ────────────────────────────────────────────────

_SIM_STATUS_TO_EXCEPTION = {
    429: lambda: RateLimitError(
        message="Simulated 429", model=settings.LLM_MODEL, llm_provider="simulated"
    ),
    500: lambda: InternalServerError(
        message="Simulated 500", model=settings.LLM_MODEL, llm_provider="simulated"
    ),
    502: lambda: InternalServerError(
        message="Simulated 502", model=settings.LLM_MODEL, llm_provider="simulated"
    ),
    503: lambda: ServiceUnavailableError(
        message="Simulated 503", model=settings.LLM_MODEL, llm_provider="simulated"
    ),
}


def _parse_sim_header(header: str) -> Dict[str, int]:
    """Parse 'key_1=429,key_2=500' or '*=429'. Returns {key_id_or_*: status}."""
    result: Dict[str, int] = {}
    for pair in header.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        kid, _, code_str = pair.partition("=")
        kid = kid.strip()
        code_str = code_str.strip()
        try:
            code = int(code_str)
        except ValueError:
            continue
        if code in _SIM_STATUS_TO_EXCEPTION:
            result[kid] = code
    return result


# ── Retryable check ──────────────────────────────────────────────────────────

def _is_retryable(exc: Exception) -> bool:
    """Should we failover to the next key?"""
    if isinstance(exc, (RateLimitError, InternalServerError, ServiceUnavailableError)):
        return True
    # Connection / timeout errors
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    # litellm wraps some errors
    exc_name = type(exc).__name__
    if "Timeout" in exc_name or "Connection" in exc_name:
        return True
    # 401/403 auth errors – treat as key failure
    if hasattr(exc, "status_code") and getattr(exc, "status_code", None) in (401, 403):
        return True
    return False


# ── Main completion call ──────────────────────────────────────────────────────

async def complete(
    messages: List[Dict[str, str]],
    sim_header: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Call the LLM with key-pool failover and caching.

    Returns (reply_text, metadata_dict).
    Raises ServiceUnavailableError if all keys exhausted.
    """
    keys = settings.LLM_API_KEYS
    if not keys:
        raise ServiceUnavailableError(
            message="No API keys configured", model=settings.LLM_MODEL, llm_provider="config"
        )

    sim_map: Dict[str, int] = {}
    skip_cache = False
    if settings.ENABLE_FAILURE_SIMULATION and sim_header:
        sim_map = _parse_sim_header(sim_header)
        skip_cache = True  # always bypass cache when simulating

    start = time.perf_counter()
    fallback_attempts = 0
    last_exc: Optional[Exception] = None

    for idx, api_key in enumerate(keys):
        key_id = f"key_{idx + 1}"

        # ── Simulate failure? ─────────────────────────────────────────────
        if sim_map:
            sim_code = sim_map.get(key_id) or sim_map.get("*")
            if sim_code is not None:
                logger.info("Simulating %d for %s", sim_code, key_id)
                fallback_attempts += 1
                last_exc = _SIM_STATUS_TO_EXCEPTION[sim_code]()
                continue  # skip to next key

        # ── Real call ─────────────────────────────────────────────────────
        try:
            kwargs: Dict[str, Any] = dict(
                model=settings.LLM_MODEL,
                messages=messages,
                api_key=api_key,
                temperature=0,
                timeout=settings.LLM_TIMEOUT,
            )
            if skip_cache:
                kwargs["cache"] = {"no-cache": True}

            response = await litellm.acompletion(**kwargs)

            elapsed_ms = int((time.perf_counter() - start) * 1000)

            # Detect cache hit
            cache_hit = False
            if hasattr(response, "_hidden_params") and response._hidden_params:
                cache_hit = response._hidden_params.get("cache_hit", False)

            reply = response.choices[0].message.content or ""

            usage = response.usage if response.usage else None
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0

            metadata = {
                "resolution_source": "LLM_CACHE" if cache_hit else "LIVE_INFERENCE",
                "model": settings.LLM_MODEL,
                "latency_ms": elapsed_ms,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "key_id": None if cache_hit else key_id,
                "fallback_attempts": fallback_attempts,
            }
            return reply, metadata

        except Exception as exc:
            if _is_retryable(exc):
                logger.warning("Key %s failed (%s), failing over", key_id, type(exc).__name__)
                fallback_attempts += 1
                last_exc = exc
                continue
            else:
                # Non-retryable client error – bubble up immediately
                raise

    # All keys exhausted
    raise ServiceUnavailableError(
        message="all providers unavailable",
        model=settings.LLM_MODEL,
        llm_provider="pool",
    )

"""Post sense.* facts to the Hub fact-ingress.

The worker is a trusted internal producer, but the Hub remains the authority:
it re-validates the active GuardBinding, epoch, and dedup before projecting or
gating. So a fact that races a binding revocation is rejected at the Hub, not
here. This module just serializes and delivers.
"""

from __future__ import annotations

import httpx
from eidolon_sdk.biz.sense import SenseMessage
from loguru import logger


class HubIngress:
    def __init__(self, *, base_url: str, timeout_s: float = 5.0) -> None:
        self._url = base_url.rstrip("/") + "/internal/sense/facts"
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def emit(self, fact: SenseMessage) -> bool:
        """Deliver one fact. Returns False on transport/HTTP failure (caller degrades)."""
        payload = fact.model_dump(mode="json")
        try:
            resp = await self._client.post(self._url, json=payload)
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            # No local retry/queue: facts are cheap and gated; the Hub-side
            # reflex baseline covers gaps. Just log and move on.
            logger.warning("sense fact delivery failed ({}): {}", fact.type, exc)
            return False

    async def aclose(self) -> None:
        await self._client.aclose()

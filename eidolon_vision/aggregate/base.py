"""Aggregator port.

A Detector is stateless (frame -> observation). An Aggregator is stateful: it
holds a short, per-binding rolling window of observations and decides when a
``sense.*`` fact should fire. This is the ONLY state the worker holds; it is
ephemeral and rebuildable (losing it at most drops one detection window — the
authoritative state lives in the Hub).

Time is injected (``now_ms``) rather than read from a wall clock so the
decision logic is deterministic and unit-testable.
"""

from __future__ import annotations

from typing import Protocol

from eidolon_sdk.biz.sense import SenseMessage

from ..core.types import BurstContext, Observation


class Aggregator(Protocol):
    def observe(
        self, observation: Observation, ctx: BurstContext, now_ms: int
    ) -> SenseMessage | None:
        """Fold one observation into the window; return a fact iff one fires now."""
        ...

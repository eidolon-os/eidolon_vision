"""Presence window with hysteresis: enter fast, leave slow.

Asymmetric on purpose. Deciding somebody arrived can be quick — being wrong
costs a wasted greeting. Deciding somebody left must be slow, because being
wrong there means the companion talks to an empty chair, or worse, stops
listening while they are still sitting there.

Emits ``sense.attention``, which the contract documents as device-derived (T0).
Producing it host-side is exactly the attribution question left open in the
plan: either the contract grows a host-derived producer, or this capability
needs its own fact type. Flagged here rather than papered over.
"""

from __future__ import annotations

from dataclasses import dataclass

from eidolon_sdk.biz.sense import SenseAttention

from ...runtime.types import Observation, RequestContext


@dataclass(frozen=True, slots=True)
class PresenceConfig:
    enter_ms: int = 600        # consecutive presence before we believe an arrival
    exit_ms: int = 12_000      # consecutive absence before we believe a departure
    min_confidence: float = 0.5


class PresenceWindow:
    def __init__(self, *, config: PresenceConfig | None = None) -> None:
        self._cfg = config or PresenceConfig()
        self._state: str | None = None       # last published state
        self._pending: str | None = None     # candidate state
        self._since_ms: int | None = None

    def observe(
        self, observation: Observation, ctx: RequestContext, now_ms: int
    ) -> SenseAttention | None:
        if observation.role != "presence":
            return None

        confident = (observation.confidence or 0.0) >= self._cfg.min_confidence
        candidate = "present" if (observation.label == "present" and confident) else "absent"

        if candidate != self._pending:
            self._pending, self._since_ms = candidate, now_ms
            return None

        # `or` would be wrong here: a legitimate since_ms of 0 is falsy, which
        # would reset dwell to zero on every call and never publish anything.
        dwell = now_ms - (now_ms if self._since_ms is None else self._since_ms)
        needed = self._cfg.enter_ms if candidate == "present" else self._cfg.exit_ms
        if dwell < needed or candidate == self._state:
            return None

        self._state = candidate
        # Low confidence must never read as a rejection of the owner, so the
        # uncertain case maps to `relaxed` rather than `away_from_screen`.
        state = "relaxed" if candidate == "present" else "away_from_screen"
        return SenseAttention(
            owner_id=ctx.owner_id,
            device_id=ctx.device_id,
            correlation_id=ctx.correlation_id,
            epoch=ctx.epoch,
            ts_ms=ctx.ts_ms,
            state=state,
            signals={"dwell_ms": dwell},
        )

"""Fatigue window: face metrics in, at most one ``sense.fatigue`` per cooldown.

Design notes:
* Thresholds and window/cooldown are the only things open to calibration; they
  live here in the decision layer, never in a perceptor.
* ``now_ms`` is injected, so every rule is testable without a clock or a model.
* One fact per cooldown window — never a stream.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from eidolon_sdk.biz.sense import SenseFatigue

from ...runtime.types import Observation, RequestContext


@dataclass(frozen=True, slots=True)
class FatigueConfig:
    """PLACEHOLDER thresholds — must be calibrated against real faces."""

    mar_yawn: float = 0.6          # mouth-aspect-ratio above this = mouth wide open
    ear_closed: float = 0.18       # eye-aspect-ratio below this = eyes closed
    window_ms: int = 300_000       # 5 min rolling window
    min_yawns: int = 3             # yawns within the window to call it fatigue
    cooldown_ms: int = 1_200_000   # >=20 min between facts (interruption budget)


class FatigueWindow:
    """One instance per (capability, owner, device). Holds a short yawn window."""

    def __init__(
        self,
        *,
        model_id: str = "unknown",
        model_version: str = "unknown",
        config: FatigueConfig | None = None,
    ) -> None:
        self._model_id = model_id
        self._model_version = model_version
        self._cfg = config or FatigueConfig()
        self._yawn_ts: deque[int] = deque()
        self._last_emit_ms: int | None = None

    def observe(
        self, observation: Observation, ctx: RequestContext, now_ms: int
    ) -> SenseFatigue | None:
        if observation.role != "face_metrics":
            return None

        mar = observation.metrics.get("mar")
        if mar is not None and mar >= self._cfg.mar_yawn:
            self._yawn_ts.append(now_ms)

        cutoff = now_ms - self._cfg.window_ms
        while self._yawn_ts and self._yawn_ts[0] < cutoff:
            self._yawn_ts.popleft()

        if len(self._yawn_ts) < self._cfg.min_yawns:
            return None
        if self._last_emit_ms is not None and now_ms - self._last_emit_ms < self._cfg.cooldown_ms:
            return None

        self._last_emit_ms = now_ms
        yawns = len(self._yawn_ts)
        self._yawn_ts.clear()
        return SenseFatigue(
            owner_id=ctx.owner_id,
            device_id=ctx.device_id,
            correlation_id=ctx.correlation_id,
            epoch=ctx.epoch,
            ts_ms=ctx.ts_ms,
            hint="yawn",
            confidence=None,
            model_id=self._model_id,
            model_version=self._model_version,
            signals={"yawn_count": yawns},
        )

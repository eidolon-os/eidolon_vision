"""The device as a remote perceptor.

The ESP32 already runs a luminance-grid motion gate and an ESP-DL person/face
judgement, and sends bounded scalars along with the burst. This adapter turns
those scalars into ordinary :class:`Observation` objects — identical in shape to
what a host-side perceptor produces for the same role.

That sameness is the whole point. A capability asks for a ``presence`` perceptor;
whether the judgement came off a 240x240 frame on an MCU or off a full frame on
the host is a line in ``bootstrap.py``, not an architectural decision.

Consumes no pixels at all: the frames argument is ignored by design.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...runtime.types import Frame, Observation, PerceptorRole, RequestContext


class DeviceReportedPerceptor:
    """Pass through a device-computed judgement for one role.

    ``signal_key`` names the scalar the device sends; ``threshold`` is the only
    interpretation applied here — a device signal is by definition already a
    thresholdable, deterministic judgement, or it should not have been computed
    on the device (see the determinism-vs-semantics boundary).
    """

    def __init__(
        self,
        *,
        role: PerceptorRole,
        signal_key: str,
        threshold: float = 0.5,
        model_id: str = "device-reported",
        model_version: str = "v1",
    ) -> None:
        self.role = role
        self.model_id = model_id
        self.model_version = model_version
        self._key = signal_key
        self._threshold = threshold

    def infer(self, frames: Sequence[Frame], ctx: RequestContext) -> list[Observation]:
        value = ctx.device_signals.get(self._key)
        if value is None:
            return []
        return [
            Observation(
                role=self.role,
                metrics={self._key: float(value)},
                label="present" if value >= self._threshold else "absent",
                confidence=min(max(float(value), 0.0), 1.0),
            )
        ]

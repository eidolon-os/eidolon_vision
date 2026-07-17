"""The async-fact pipeline: decode -> route-by-trigger -> detect -> aggregate.

Detectors and the aggregator factory are injected so the wiring is testable
with fakes and heavy models are constructed only at app startup. The pipeline
owns the per-binding aggregator windows (the worker's only state).
"""

from __future__ import annotations

from typing import Callable, Sequence

from eidolon_sdk.biz.sense import SenseMessage

from ..aggregate.base import Aggregator
from ..detect.base import Detector
from .types import BurstContext, Frame


def decode_jpeg(data: bytes) -> Frame:
    """Decode one JPEG to a Frame (BGR). Lazy opencv import keeps pure paths light."""
    import cv2
    import numpy as np

    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("undecodable JPEG frame")
    h, w = img.shape[:2]
    return Frame(pixels=img, width=int(w), height=int(h))


def _binding_key(ctx: BurstContext) -> str:
    return f"{ctx.guard_companion_id}:{ctx.device_id}:{ctx.trigger}"


class Pipeline:
    def __init__(
        self,
        *,
        detectors: dict[str, Detector],
        aggregator_factory: Callable[[BurstContext], Aggregator],
    ) -> None:
        self._detectors = detectors  # keyed by trigger
        self._agg_factory = aggregator_factory
        self._aggregators: dict[str, Aggregator] = {}

    def _aggregator(self, ctx: BurstContext) -> Aggregator:
        key = _binding_key(ctx)
        agg = self._aggregators.get(key)
        if agg is None:
            agg = self._agg_factory(ctx)
            self._aggregators[key] = agg
        return agg

    def process(
        self, frames: Sequence[Frame], ctx: BurstContext, now_ms: int
    ) -> list[SenseMessage]:
        """Run the burst through its detector + aggregator; return any facts that fired."""
        detector = self._detectors.get(ctx.trigger)
        if detector is None:
            return []  # e.g. away_watch (④) / user_look (⑥) not wired on the fact path in v1
        aggregator = self._aggregator(ctx)
        facts: list[SenseMessage] = []
        for observation in detector.infer(frames, ctx):
            fact = aggregator.observe(observation, ctx, now_ms)
            if fact is not None:
                facts.append(fact)
        return facts

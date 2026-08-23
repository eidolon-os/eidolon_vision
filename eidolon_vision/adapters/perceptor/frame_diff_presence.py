"""Host-side ``presence`` from frame differencing. OpenCV only, no model asset.

Mirrors what the device already does — the firmware reduces a frame to a 24x18
luminance grid and scores the delta — but runs it here instead. That is the point:
the same deterministic judgement, computed on either side, emitting the same
:class:`Observation`. No neural network is involved because none is needed; this
is a thresholdable question, which is exactly the kind that belongs below the
semantics line.

Stateless per the Perceptor contract, so the "previous" grid is derived from the
burst itself rather than held across calls: a burst of one frame yields no motion
signal, which is honest — you cannot see movement in a single photograph.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from ...runtime.types import Frame, Observation, RequestContext

GRID_W, GRID_H = 24, 18


class FrameDiffPresencePerceptor:
    role = "presence"
    model_id = "frame-diff-luminance"
    model_version = "grid24x18-v1"

    def __init__(self, *, motion_threshold: float = 18.0) -> None:
        self._threshold = motion_threshold

    def infer(self, frames: Sequence[Frame], ctx: RequestContext) -> list[Observation]:
        if len(frames) < 2:
            return []

        import cv2  # lazy: opencv is a base dep but the runtime must not need it
        import numpy as np

        grids = []
        for frame in frames:
            gray = cv2.cvtColor(frame.pixels, cv2.COLOR_BGR2GRAY)
            grids.append(
                cv2.resize(gray, (GRID_W, GRID_H), interpolation=cv2.INTER_AREA).astype(
                    np.int16
                )
            )

        out: list[Observation] = []
        for before, after in pairwise(grids):
            score = float(np.abs(after - before).mean())
            present = score >= self._threshold
            out.append(
                Observation(
                    role=self.role,
                    metrics={"motion_score": score},
                    label="present" if present else "absent",
                    confidence=min(score / (self._threshold * 2.0), 1.0),
                )
            )
        return out

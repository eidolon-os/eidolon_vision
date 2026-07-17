"""MediaPipe Face Landmarker detector — the fatigue signal source (CPU).

Computes Mouth-Aspect-Ratio (yawn) and Eye-Aspect-Ratio (eye closure) from the
468-point face mesh. It only emits bounded scalars (mar/ear); no landmarks, no
image, nothing that could reconstruct the frame leaves this object.

Heavy deps (mediapipe, opencv, numpy) are imported lazily inside ``__init__``
so the pure pipeline logic, aggregators, and their tests import cleanly without
them installed.
"""

from __future__ import annotations

from typing import Sequence

from ..core.types import BurstContext, Frame, Observation

# 468-mesh indices for the aspect-ratio landmarks (standard MediaPipe mesh).
_MOUTH = {"top": 13, "bottom": 14, "left": 78, "right": 308}
_LEFT_EYE = {"top": 159, "bottom": 145, "left": 33, "right": 133}
_RIGHT_EYE = {"top": 386, "bottom": 374, "left": 362, "right": 263}


class FaceLandmarkerDetector:
    model_id = "mediapipe-face-landmarker"
    model_version = "mar-ear-v1"

    def __init__(self, *, model_asset_path: str) -> None:
        import mediapipe as mp  # lazy: keep heavy deps out of pure-logic imports
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        options = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=model_asset_path),
            num_faces=1,
            running_mode=mp_vision.RunningMode.IMAGE,
        )
        self._mp = mp
        self._landmarker = mp_vision.FaceLandmarker.create_from_options(options)

    def infer(self, frames: Sequence[Frame], ctx: BurstContext) -> list[Observation]:
        out: list[Observation] = []
        for frame in frames:
            image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=frame.pixels)
            result = self._landmarker.detect(image)
            if not result.face_landmarks:
                continue
            lm = result.face_landmarks[0]
            out.append(
                Observation(
                    kind="face",
                    metrics={
                        "mar": _aspect_ratio(lm, _MOUTH),
                        "ear": min(_aspect_ratio(lm, _LEFT_EYE), _aspect_ratio(lm, _RIGHT_EYE)),
                    },
                )
            )
        return out


def _aspect_ratio(landmarks, idx: dict[str, int]) -> float:
    """Vertical/horizontal opening ratio from four normalized landmarks."""
    vertical = abs(landmarks[idx["top"]].y - landmarks[idx["bottom"]].y)
    horizontal = abs(landmarks[idx["right"]].x - landmarks[idx["left"]].x)
    if horizontal <= 1e-6:
        return 0.0
    return vertical / horizontal

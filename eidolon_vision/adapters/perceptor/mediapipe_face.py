"""MediaPipe Face Landmarker — two roles off one model asset.

Computes Mouth- and Eye-Aspect-Ratio from the face mesh for ``face_metrics``,
and answers "is a face there at all" for ``presence``. Both emit only bounded
scalars: no landmarks, no crops, nothing that could reconstruct the frame leaves
these objects.

The ``presence`` variant exists so the same judgement the device makes can be
made here instead — that swap is the cheapest available proof that the role
indirection actually decouples anything.

Heavy deps are imported lazily in ``__init__`` so the runtime, the registry and
the aggregators stay importable with mediapipe absent.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...runtime.types import Frame, Observation, RequestContext

# Standard MediaPipe 468-mesh indices for the aspect-ratio landmarks.
_MOUTH = {"top": 13, "bottom": 14, "left": 78, "right": 308}
_LEFT_EYE = {"top": 159, "bottom": 145, "left": 33, "right": 133}
_RIGHT_EYE = {"top": 386, "bottom": 374, "left": 362, "right": 263}

MODEL_ID = "mediapipe-face-landmarker"


class _Landmarker:
    """Shared model handle so two perceptor roles can share one loaded asset."""

    def __init__(self, model_asset_path: str, num_faces: int) -> None:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        self._mp = mp
        self._landmarker = mp_vision.FaceLandmarker.create_from_options(
            mp_vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=model_asset_path),
                num_faces=num_faces,
                running_mode=mp_vision.RunningMode.IMAGE,
            )
        )

    def detect(self, frame: Frame):
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=frame.pixels)
        return self._landmarker.detect(image)


class MediaPipeFaceMetricsPerceptor:
    role = "face_metrics"
    model_id = MODEL_ID
    model_version = "mar-ear-v1"

    def __init__(self, *, model_asset_path: str) -> None:
        self._model = _Landmarker(model_asset_path, num_faces=1)

    def infer(self, frames: Sequence[Frame], ctx: RequestContext) -> list[Observation]:
        out: list[Observation] = []
        for frame in frames:
            result = self._model.detect(frame)
            if not result.face_landmarks:
                continue
            lm = result.face_landmarks[0]
            out.append(
                Observation(
                    role=self.role,
                    metrics={
                        "mar": _aspect_ratio(lm, _MOUTH),
                        "ear": min(
                            _aspect_ratio(lm, _LEFT_EYE), _aspect_ratio(lm, _RIGHT_EYE)
                        ),
                    },
                )
            )
        return out


class MediaPipeFacePresencePerceptor:
    """Host-side ``presence``: a detected face means somebody is there.

    Drop-in for :class:`DeviceReportedPerceptor` bound to the same role.
    """

    role = "presence"
    model_id = MODEL_ID
    model_version = "face-presence-v1"

    def __init__(self, *, model_asset_path: str, max_faces: int = 2) -> None:
        self._model = _Landmarker(model_asset_path, num_faces=max_faces)

    def infer(self, frames: Sequence[Frame], ctx: RequestContext) -> list[Observation]:
        out: list[Observation] = []
        for frame in frames:
            faces = len(self._model.detect(frame).face_landmarks or ())
            out.append(
                Observation(
                    role=self.role,
                    metrics={"faces": float(faces)},
                    label="present" if faces else "absent",
                    confidence=1.0 if faces else 0.0,
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

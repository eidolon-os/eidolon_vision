"""YuNet detection + SFace embedding, both through OpenCV's own classes.

Needs nothing beyond ``opencv-python-headless``, which the service already
carries for JPEG decode. The weights are not in this repository: they are a
pinned, checksum-verified package owned by ``eidolon_models``
(``face_recognition/sface_yunet_opencv_zoo/<revision>/``) and this adapter is
given that directory. It never downloads anything.

Inference is serialized with a lock: OpenCV's detector keeps its input size as
instance state, so two requests on worker threads must not interleave.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from ...runtime.faces import EncodedFace
from ...runtime.types import Frame

MANIFEST = "manifest.json"
#: Frames wider or taller than this are scaled down before detection. YuNet is
#: trained for faces of roughly 10-300 px; a 12 MP phone photo would otherwise
#: present a face larger than anything it has seen.
MAX_DETECT_EDGE = 1024
#: What "the same preprocessing" means for stored templates: detector, its
#: thresholds, the detection scale cap, and SFace's own 5-point alignment.
PREPROCESSING_VERSION = "yunet2023mar-s0.6-n0.3-edge1024-sface-align112-v1"


class FaceModelError(RuntimeError):
    """The model package is missing, incomplete, or not the bytes its manifest names."""


class OpenCvZooFaceEncoder:
    preprocessing_version = PREPROCESSING_VERSION
    vector_length = 128

    def __init__(self, model_dir: str | Path, *, verify_checksums: bool = True) -> None:
        import cv2

        root = Path(model_dir)
        try:
            manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
            artifacts = {a["kind"]: a for a in manifest["artifacts"]}
            detector, recognizer = artifacts["face_detector"], artifacts["face_embedding"]
            self.model_id = str(manifest["model_alias"])
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise FaceModelError(f"unusable face model package {root}: {exc}") from exc

        for artifact in (detector, recognizer):
            path = root / artifact["path"]
            if not path.is_file():
                raise FaceModelError(f"missing model file {path}")
            if verify_checksums and _sha256(path) != artifact["sha256"]:
                raise FaceModelError(f"{path} does not match the manifest checksum")

        self.weights_hash = str(recognizer["sha256"])
        self._detector = cv2.FaceDetectorYN.create(
            str(root / detector["path"]), "", (320, 320), 0.6, 0.3, 5000
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(root / recognizer["path"]), "")
        self._lock = threading.Lock()

    def encode(self, frame: Frame) -> list[EncodedFace]:
        import cv2

        image = frame.pixels
        scale = 1.0
        longest = max(frame.width, frame.height)
        if longest > MAX_DETECT_EDGE:
            scale = MAX_DETECT_EDGE / longest
            image = cv2.resize(
                image,
                (max(1, round(frame.width * scale)), max(1, round(frame.height * scale))),
                interpolation=cv2.INTER_AREA,
            )

        faces: list[EncodedFace] = []
        with self._lock:
            height, width = image.shape[:2]
            self._detector.setInputSize((int(width), int(height)))
            _, rows = self._detector.detect(image)
            for row in rows if rows is not None else ():
                aligned = self._recognizer.alignCrop(image, row)
                vector = self._recognizer.feature(aligned).reshape(-1)
                x, y, w, h = (float(v) / scale for v in row[:4])
                faces.append(
                    EncodedFace(
                        box=(x, y, w, h),
                        score=float(row[14]),
                        vector=tuple(float(v) for v in vector),
                    )
                )
        return faces


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()

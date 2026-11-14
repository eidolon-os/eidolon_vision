"""Face evidence: one still in, per-face comparisons against enrolled templates out.

This is the third shape of work beside the fact path and the answer path, and it
is kept out of :class:`~.graph.PerceptionGraph` on purpose: a comparison is
neither a fact (nothing is emitted to the control plane) nor an answer (no text
is produced). The caller sends one frame and the templates it is entitled to
compare against; what comes back is evidence, and the caller decides.

Rules this module holds, whatever encoder is bound:

* Nothing is stored. Templates arrive with the request and leave with it; a
  probe's vector exists only inside :func:`compare`.
* No vector is ever returned from a comparison. Only :func:`enroll` returns one,
  to the authority that will store it beside the photo it came from.
* Vision does not decide who someone is. It reports a score per enrolled person
  and the band the model's own policy puts that score in; the caller applies
  consent, session, and cross-modal rules.

Pure logic: no numpy, no opencv, so the rules are testable without a model.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from .types import Frame

Band = Literal["strong", "weak", "none"]
ProbeQuality = Literal["ok", "too_small", "low_confidence"]
Confidence = Literal["validated", "controlled_trial", "unvalidated"]
EnrollRejection = Literal["no_face", "multiple_faces", "face_too_small", "low_confidence"]


class FacePolicyError(ValueError):
    """The policy file is missing, malformed, or belongs to another model."""


class TemplateMismatch(ValueError):
    """A template was made by a different model or preprocessing than the bound one."""


@dataclass(frozen=True, slots=True)
class EncodedFace:
    """One detected face, as the encoder reports it. Never leaves this process."""

    box: tuple[float, float, float, float]  # x, y, w, h in pixels
    score: float  # detector confidence, 0..1
    vector: tuple[float, ...]


@runtime_checkable
class FaceEncoder(Protocol):
    """Detect every face in a frame and embed each one.

    ``model_id`` and ``preprocessing_version`` name what a vector means. Two
    vectors are comparable only when both match, which is why they travel with
    every stored template.
    """

    model_id: str
    preprocessing_version: str
    vector_length: int

    def encode(self, frame: Frame) -> list[EncodedFace]: ...


@dataclass(frozen=True, slots=True)
class FacePolicy:
    """How a score from one model becomes a band. Ships beside the weights."""

    version: str
    model_id: str
    preprocessing_version: str
    #: Cosine at or above which a comparison is ``strong`` / ``weak``.
    strong: float
    weak: float
    #: The leader must beat the runner-up by this much to stay ``strong``.
    margin: float
    #: Short side of the face box, in pixels of the frame as received.
    min_enroll_face_px: int
    min_probe_face_px: int
    min_enroll_score: float
    min_probe_score: float
    max_faces: int = 8
    #: What the thresholds were checked against. ``unvalidated`` until they have
    #: been measured on the cameras that will actually take the probe frames.
    confidence: Confidence = "unvalidated"

    def __post_init__(self) -> None:
        if not -1.0 <= self.weak <= self.strong <= 1.0:
            raise FacePolicyError("thresholds must satisfy -1 <= weak <= strong <= 1")
        if self.margin < 0 or self.max_faces < 1:
            raise FacePolicyError("margin and max_faces must be positive")

    def band(self, score: float) -> Band:
        if score >= self.strong:
            return "strong"
        if score >= self.weak:
            return "weak"
        return "none"


def load_policy(path: str | Path) -> FacePolicy:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return FacePolicy(
            version=str(raw["version"]),
            model_id=str(raw["model_id"]),
            preprocessing_version=str(raw["preprocessing_version"]),
            strong=float(raw["thresholds"]["strong"]),
            weak=float(raw["thresholds"]["weak"]),
            margin=float(raw["margin"]),
            min_enroll_face_px=int(raw["min_enroll_face_px"]),
            min_probe_face_px=int(raw["min_probe_face_px"]),
            min_enroll_score=float(raw["min_enroll_score"]),
            min_probe_score=float(raw["min_probe_score"]),
            max_faces=int(raw.get("max_faces", 8)),
            confidence=_confidence(raw.get("confidence", "unvalidated")),
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise FacePolicyError(f"unusable face policy {path}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class FaceTemplate:
    """One enrolled reference. ``ref`` is opaque here: the caller's own handle."""

    ref: str
    vector: tuple[float, ...]
    model_id: str
    preprocessing_version: str


@dataclass(frozen=True, slots=True)
class Enrollment:
    """Result of looking at a reference photo. A vector only when accepted."""

    accepted: bool
    faces: int
    rejection: EnrollRejection | None = None
    vector: tuple[float, ...] | None = None
    face_px: int | None = None


@dataclass(frozen=True, slots=True)
class Comparison:
    ref: str
    score: float
    band: Band


@dataclass(frozen=True, slots=True)
class FaceEvidence:
    """One face in the probe frame and how it compares to each enrolled ref.

    ``comparisons`` is ordered best first and is empty when ``quality`` is not
    ``ok``: a face too small to trust is reported as present, not compared.
    ``center_x`` / ``center_y`` are in -1..1 (right and down positive) so the
    caller can relate a face to where the device says a person is.
    """

    quality: ProbeQuality
    face_px: int
    area_ratio: float
    center_x: float
    center_y: float
    comparisons: tuple[Comparison, ...] = ()
    #: False when the runner-up is within the policy margin of the leader.
    distinct: bool = True


@dataclass(frozen=True, slots=True)
class MatchResult:
    faces: tuple[FaceEvidence, ...]
    #: Faces the detector found beyond ``max_faces``; reported, never compared.
    faces_dropped: int = 0
    templates_compared: int = 0
    model_id: str = ""
    policy_version: str = ""
    refs: tuple[str, ...] = field(default_factory=tuple)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise TemplateMismatch("vectors of different lengths are not comparable")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if norm == 0.0 or not math.isfinite(norm):
        return 0.0
    return max(-1.0, min(1.0, dot / norm))


def _short_side(face: EncodedFace) -> int:
    return int(min(face.box[2], face.box[3]))


def enroll(encoder: FaceEncoder, policy: FacePolicy, frame: Frame) -> Enrollment:
    """Judge a reference photo and, if it is usable, return its vector.

    A reference must show exactly one face: with two, nothing here could know
    whose template it is, and guessing the larger one enrolls the wrong person
    silently.
    """
    _require_same_model(encoder, policy)
    faces = encoder.encode(frame)
    if not faces:
        return Enrollment(accepted=False, faces=0, rejection="no_face")
    if len(faces) > 1:
        return Enrollment(accepted=False, faces=len(faces), rejection="multiple_faces")
    face = faces[0]
    px = _short_side(face)
    if px < policy.min_enroll_face_px:
        return Enrollment(accepted=False, faces=1, rejection="face_too_small", face_px=px)
    if face.score < policy.min_enroll_score:
        return Enrollment(accepted=False, faces=1, rejection="low_confidence", face_px=px)
    return Enrollment(accepted=True, faces=1, vector=face.vector, face_px=px)


def compare(
    encoder: FaceEncoder,
    policy: FacePolicy,
    frame: Frame,
    templates: Sequence[FaceTemplate],
) -> MatchResult:
    """Compare every usable face in ``frame`` with every enrolled ref.

    A ref with several templates scores as its best template. Every face gets
    its own evidence; nothing picks "the" person in a frame with several.
    """
    _require_same_model(encoder, policy)
    for template in templates:
        if (
            template.model_id != encoder.model_id
            or template.preprocessing_version != encoder.preprocessing_version
            or len(template.vector) != encoder.vector_length
        ):
            raise TemplateMismatch(f"template for {template.ref!r} was made by another model")

    refs = tuple(dict.fromkeys(t.ref for t in templates))
    detected = sorted(encoder.encode(frame), key=lambda f: f.box[2] * f.box[3], reverse=True)
    kept, dropped = detected[: policy.max_faces], max(0, len(detected) - policy.max_faces)

    area = float(frame.width * frame.height) or 1.0
    evidence: list[FaceEvidence] = []
    for face in kept:
        x, y, w, h = face.box
        common = {
            "face_px": _short_side(face),
            "area_ratio": round(max(0.0, min(1.0, (w * h) / area)), 4),
            "center_x": round(_unit((x + w / 2) / frame.width), 3),
            "center_y": round(_unit((y + h / 2) / frame.height), 3),
        }
        if _short_side(face) < policy.min_probe_face_px:
            evidence.append(FaceEvidence(quality="too_small", **common))
            continue
        if face.score < policy.min_probe_score:
            evidence.append(FaceEvidence(quality="low_confidence", **common))
            continue

        best: dict[str, float] = {}
        for template in templates:
            score = cosine(face.vector, template.vector)
            if score > best.get(template.ref, -2.0):
                best[template.ref] = score
        ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)
        distinct = len(ranked) < 2 or ranked[0][1] - ranked[1][1] >= policy.margin
        evidence.append(
            FaceEvidence(
                quality="ok",
                comparisons=tuple(
                    Comparison(ref=ref, score=round(score, 4), band=policy.band(score))
                    for ref, score in ranked
                ),
                distinct=distinct,
                **common,
            )
        )

    return MatchResult(
        faces=tuple(evidence),
        faces_dropped=dropped,
        templates_compared=len(templates),
        model_id=encoder.model_id,
        policy_version=policy.version,
        refs=refs,
    )


def _confidence(value: object) -> Confidence:
    if value not in ("validated", "controlled_trial", "unvalidated"):
        raise ValueError(f"unknown confidence {value!r}")
    return value  # type: ignore[return-value]


def _unit(fraction: float) -> float:
    return max(-1.0, min(1.0, fraction * 2.0 - 1.0))


def _require_same_model(encoder: FaceEncoder, policy: FacePolicy) -> None:
    if (
        policy.model_id != encoder.model_id
        or policy.preprocessing_version != encoder.preprocessing_version
    ):
        raise FacePolicyError(
            f"policy {policy.version} is for {policy.model_id}/{policy.preprocessing_version}, "
            f"encoder is {encoder.model_id}/{encoder.preprocessing_version}"
        )

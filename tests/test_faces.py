"""Face comparison rules with a fake encoder — no model, no opencv.

What matters here is what the module refuses to do: enroll an ambiguous photo,
compare across models, pick one person out of several, or hand back a vector.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from eidolon_vision.runtime.faces import (
    EncodedFace,
    FacePolicy,
    FacePolicyError,
    FaceTemplate,
    TemplateMismatch,
    compare,
    cosine,
    enroll,
    load_policy,
)
from eidolon_vision.runtime.types import Frame

MODEL = "fake-face"
PRE = "fake-pre-v1"
FRAME = Frame(pixels=None, width=800, height=400)
A, B, C = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)


class FakeEncoder:
    model_id = MODEL
    preprocessing_version = PRE
    vector_length = 3

    def __init__(self, *faces: EncodedFace) -> None:
        self.faces = list(faces)

    def encode(self, frame):
        return list(self.faces)


def face(vector, *, size=120.0, score=0.95, x=340.0, y=140.0) -> EncodedFace:
    return EncodedFace(box=(x, y, size, size), score=score, vector=tuple(vector))


def policy(**overrides) -> FacePolicy:
    values = {
        "version": "test-policy",
        "model_id": MODEL,
        "preprocessing_version": PRE,
        "strong": 0.5,
        "weak": 0.36,
        "margin": 0.08,
        "min_enroll_face_px": 80,
        "min_probe_face_px": 40,
        "min_enroll_score": 0.8,
        "min_probe_score": 0.7,
    }
    return FacePolicy(**(values | overrides))


def template(ref: str, vector) -> FaceTemplate:
    return FaceTemplate(ref=ref, vector=tuple(vector), model_id=MODEL, preprocessing_version=PRE)


def test_cosine_is_bounded_and_refuses_unequal_lengths() -> None:
    assert cosine(A, A) == pytest.approx(1.0)
    assert cosine(A, B) == 0.0
    assert cosine((0.0, 0.0, 0.0), A) == 0.0
    with pytest.raises(TemplateMismatch):
        cosine(A, (1.0, 0.0))


def test_enroll_accepts_exactly_one_good_face() -> None:
    result = enroll(FakeEncoder(face(A)), policy(), FRAME)
    assert result.accepted and result.vector == A and result.face_px == 120


@pytest.mark.parametrize(
    ("faces", "rejection"),
    [
        ((), "no_face"),
        ((face(A), face(B)), "multiple_faces"),
        ((face(A, size=60.0),), "face_too_small"),
        ((face(A, score=0.75),), "low_confidence"),
    ],
)
def test_enroll_rejects_an_ambiguous_or_poor_photo(faces, rejection) -> None:
    result = enroll(FakeEncoder(*faces), policy(), FRAME)
    assert not result.accepted
    assert result.rejection == rejection
    assert result.vector is None


def test_compare_ranks_every_ref_and_bands_by_policy() -> None:
    probe = (0.9, 0.42, 0.1)
    result = compare(
        FakeEncoder(face(probe)), policy(), FRAME, [template("a", A), template("b", B)]
    )
    (only,) = result.faces
    assert only.quality == "ok"
    assert [c.ref for c in only.comparisons] == ["a", "b"]
    assert [c.band for c in only.comparisons] == ["strong", "weak"]
    assert only.distinct
    assert result.templates_compared == 2 and result.refs == ("a", "b")


def test_a_ref_scores_as_its_best_template() -> None:
    result = compare(
        FakeEncoder(face(A)), policy(), FRAME, [template("a", B), template("a", A)]
    )
    (comparison,) = result.faces[0].comparisons
    assert comparison.ref == "a" and comparison.score == pytest.approx(1.0)


def test_two_refs_within_the_margin_are_not_distinct() -> None:
    probe = (0.72, 0.69, 0.0)
    result = compare(
        FakeEncoder(face(probe)), policy(), FRAME, [template("a", A), template("b", B)]
    )
    assert result.faces[0].comparisons[0].band == "strong"
    assert not result.faces[0].distinct


def test_every_face_gets_its_own_evidence_largest_first() -> None:
    result = compare(
        FakeEncoder(face(B, size=60.0, x=100.0), face(A, size=150.0, x=600.0)),
        policy(),
        FRAME,
        [template("a", A), template("b", B)],
    )
    assert [f.comparisons[0].ref for f in result.faces] == ["a", "b"]
    assert result.faces[0].center_x > 0 > result.faces[1].center_x


def test_a_small_or_doubtful_face_is_reported_but_not_compared() -> None:
    result = compare(
        FakeEncoder(face(A, size=30.0), face(A, score=0.6)), policy(), FRAME, [template("a", A)]
    )
    assert sorted(f.quality for f in result.faces) == ["low_confidence", "too_small"]
    assert all(f.comparisons == () for f in result.faces)


def test_faces_beyond_the_cap_are_counted_not_compared() -> None:
    encoder = FakeEncoder(*(face(A, size=50.0 + i) for i in range(5)))
    result = compare(encoder, policy(max_faces=2), FRAME, [template("a", A)])
    assert len(result.faces) == 2 and result.faces_dropped == 3


def test_no_templates_still_reports_faces() -> None:
    result = compare(FakeEncoder(face(A)), policy(), FRAME, [])
    assert result.faces[0].quality == "ok" and result.faces[0].comparisons == ()


@pytest.mark.parametrize(
    "bad",
    [
        FaceTemplate(ref="a", vector=A, model_id="other", preprocessing_version=PRE),
        FaceTemplate(ref="a", vector=A, model_id=MODEL, preprocessing_version="other"),
        FaceTemplate(ref="a", vector=(1.0, 0.0), model_id=MODEL, preprocessing_version=PRE),
    ],
)
def test_templates_from_another_model_are_refused(bad) -> None:
    with pytest.raises(TemplateMismatch):
        compare(FakeEncoder(face(A)), policy(), FRAME, [bad])


def test_a_policy_for_another_model_is_refused() -> None:
    with pytest.raises(FacePolicyError):
        compare(FakeEncoder(face(A)), policy(model_id="other"), FRAME, [])
    with pytest.raises(FacePolicyError):
        enroll(FakeEncoder(face(A)), policy(preprocessing_version="other"), FRAME)


def test_match_evidence_never_carries_a_vector() -> None:
    result = compare(FakeEncoder(face(A)), policy(), FRAME, [template("a", A)])
    text = json.dumps(asdict(result))
    assert "vector" not in text


def test_policy_file_round_trip_and_rejections(tmp_path) -> None:
    body = {
        "version": "p1",
        "model_id": MODEL,
        "preprocessing_version": PRE,
        "thresholds": {"strong": 0.5, "weak": 0.36},
        "margin": 0.08,
        "min_enroll_face_px": 80,
        "min_probe_face_px": 40,
        "min_enroll_score": 0.8,
        "min_probe_score": 0.7,
        "confidence": "controlled_trial",
    }
    path = tmp_path / "face-policy.json"
    path.write_text(json.dumps(body))
    loaded = load_policy(path)
    assert loaded.band(0.5) == "strong" and loaded.band(0.4) == "weak" and loaded.band(0.1) == "none"
    assert loaded.confidence == "controlled_trial"

    path.write_text(json.dumps(body | {"thresholds": {"strong": 0.3, "weak": 0.5}}))
    with pytest.raises(FacePolicyError):
        load_policy(path)
    path.write_text(json.dumps(body | {"confidence": "certain"}))
    with pytest.raises(FacePolicyError):
        load_policy(path)
    with pytest.raises(FacePolicyError):
        load_policy(tmp_path / "missing.json")

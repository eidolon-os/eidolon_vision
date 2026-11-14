"""The face routes over HTTP, with a fake encoder bound in place of the model."""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eidolon_vision.app.config import Settings
from eidolon_vision.app.faces_http import face_routes_usable, register_face_routes
from eidolon_vision.runtime.faces import EncodedFace, FacePolicy

TOKEN = "host-service-token-for-tests"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
VECTOR = [1.0, 0.0, 0.0]


class FakeEncoder:
    model_id = "fake-face"
    preprocessing_version = "fake-pre-v1"
    vector_length = 3
    weights_hash = "0" * 64

    def __init__(self) -> None:
        self.faces = [EncodedFace(box=(20.0, 20.0, 100.0, 100.0), score=0.95, vector=tuple(VECTOR))]

    def encode(self, frame):
        return list(self.faces)


class Audit:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def record(self, ctx, capability, **fields) -> None:
        self.rows.append({"owner": ctx.owner_id, "trigger": ctx.trigger, **fields})


POLICY = FacePolicy(
    version="test-policy",
    model_id="fake-face",
    preprocessing_version="fake-pre-v1",
    strong=0.5,
    weak=0.36,
    margin=0.08,
    min_enroll_face_px=80,
    min_probe_face_px=40,
    min_enroll_score=0.8,
    min_probe_score=0.7,
)


def jpeg(width: int = 160, height: int = 160) -> bytes:
    ok, data = cv2.imencode(".jpg", np.zeros((height, width, 3), np.uint8))
    assert ok
    return data.tobytes()


@pytest.fixture
def served():
    encoder, audit = FakeEncoder(), Audit()
    app = FastAPI()
    register_face_routes(app, Settings(service_token=TOKEN), (encoder, POLICY), audit)
    return TestClient(app), encoder, audit


def templates(**overrides) -> str:
    row = {
        "ref": "p1",
        "vector": VECTOR,
        "model_id": "fake-face",
        "preprocessing_version": "fake-pre-v1",
    }
    return json.dumps([row | overrides])


def test_embed_returns_the_vector_and_what_made_it(served) -> None:
    client, _, audit = served
    response = client.post(
        "/v1/faces/embed", files={"image": ("a.jpg", jpeg())}, data={"owner_id": "o"}, headers=AUTH
    )
    body = response.json()
    assert response.status_code == 200
    assert body["accepted"] is True and body["vector"] == VECTOR
    assert body["model_id"] == "fake-face" and body["feature_schema_version"] == 1
    assert audit.rows == [
        {
            "owner": "o",
            "trigger": "face_enroll",
            "egress": False,
            "pixels_retained_ms": 0,
            "faces": 1,
            "outcome": "accepted",
            "latency_ms": audit.rows[0]["latency_ms"],
        }
    ]


def test_embed_reports_a_rejected_photo_without_a_vector(served) -> None:
    client, encoder, _ = served
    encoder.faces = []
    body = client.post(
        "/v1/faces/embed", files={"image": ("a.jpg", jpeg())}, data={"owner_id": "o"}, headers=AUTH
    ).json()
    assert body["accepted"] is False and body["rejection"] == "no_face" and body["vector"] is None


def test_match_returns_evidence_and_no_vector(served) -> None:
    client, _, audit = served
    response = client.post(
        "/v1/faces/match",
        files={"image": ("a.jpg", jpeg())},
        data={"owner_id": "o", "device_id": "d", "templates": templates()},
        headers=AUTH,
    )
    body = response.json()
    assert response.status_code == 200
    assert body["faces"][0]["comparisons"] == [{"ref": "p1", "score": 1.0, "band": "strong"}]
    assert body["confidence"] == "unvalidated" and body["policy_version"] == "test-policy"
    assert "vector" not in response.text
    row = audit.rows[0]
    assert row["trigger"] == "face_match" and row["faces"] == 1 and row["templates"] == 1
    assert "p1" not in json.dumps(row)


def test_match_refuses_templates_from_another_model(served) -> None:
    client, _, _ = served
    response = client.post(
        "/v1/faces/match",
        files={"image": ("a.jpg", jpeg())},
        data={"owner_id": "o", "templates": templates(model_id="other")},
        headers=AUTH,
    )
    assert response.status_code == 409


@pytest.mark.parametrize("bad", ["not json", "{}", json.dumps([{"ref": "p1"}])])
def test_match_refuses_malformed_templates(served, bad) -> None:
    client, _, _ = served
    response = client.post(
        "/v1/faces/match",
        files={"image": ("a.jpg", jpeg())},
        data={"owner_id": "o", "templates": bad},
        headers=AUTH,
    )
    assert response.status_code == 422


def test_routes_need_the_service_token(served) -> None:
    client, _, _ = served
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = client.post(
            "/v1/faces/embed",
            files={"image": ("a.jpg", jpeg())},
            data={"owner_id": "o"},
            headers=headers,
        )
        assert response.status_code == 401


def test_routes_are_unavailable_until_configured() -> None:
    for settings, service in (
        (Settings(service_token=TOKEN), None),
        (Settings(service_token="", host="127.0.0.1"), None),
        (Settings(service_token="", host="0.0.0.0"), (FakeEncoder(), POLICY)),
    ):
        app = FastAPI()
        register_face_routes(app, settings, service, None)
        client = TestClient(app)
        response = client.post(
            "/v1/faces/embed", files={"image": ("a.jpg", jpeg())}, data={"owner_id": "o"}, headers=AUTH
        )
        assert response.status_code == 503
        assert client.get("/v1/faces/readyz").status_code == 503
        assert face_routes_usable(settings, service) is False


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_a_loopback_service_without_a_token_serves_the_host_itself(host) -> None:
    settings = Settings(service_token="", host=host)
    app = FastAPI()
    register_face_routes(app, settings, (FakeEncoder(), POLICY), None)
    client = TestClient(app)
    for headers in ({}, AUTH):
        response = client.post(
            "/v1/faces/embed", files={"image": ("a.jpg", jpeg())}, data={"owner_id": "o"}, headers=headers
        )
        assert response.status_code == 200 and response.json()["accepted"] is True
    assert face_routes_usable(settings, (FakeEncoder(), POLICY)) is True


def test_a_token_is_still_required_off_loopback_and_on_it() -> None:
    for host in ("0.0.0.0", "127.0.0.1"):
        app = FastAPI()
        register_face_routes(app, Settings(service_token=TOKEN, host=host), (FakeEncoder(), POLICY), None)
        client = TestClient(app)
        post = {"files": {"image": ("a.jpg", jpeg())}, "data": {"owner_id": "o"}}
        assert client.post("/v1/faces/embed", **post).status_code == 401
        assert client.post("/v1/faces/embed", headers=AUTH, **post).status_code == 200


def test_readiness_names_the_loaded_package(served) -> None:
    client, _, _ = served
    response = client.get("/v1/faces/readyz")
    assert response.status_code == 200
    assert response.json() == {"ready": True, "model_id": "fake-face", "policy_version": "test-policy"}


def test_oversized_and_undecodable_images_are_refused(served) -> None:
    client, _, _ = served
    app = FastAPI()
    register_face_routes(
        app, Settings(service_token=TOKEN, face_max_image_bytes=100), (FakeEncoder(), POLICY), None
    )
    too_big = TestClient(app).post(
        "/v1/faces/embed", files={"image": ("a.jpg", jpeg())}, data={"owner_id": "o"}, headers=AUTH
    )
    assert too_big.status_code == 413
    garbage = client.post(
        "/v1/faces/embed", files={"image": ("a.jpg", b"nope")}, data={"owner_id": "o"}, headers=AUTH
    )
    assert garbage.status_code == 400

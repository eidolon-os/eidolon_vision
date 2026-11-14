"""Face routes: enroll one reference photo, compare one still with templates.

Called by the Host's own services, never by a device: Admin when the Owner
enables recognition for a Person, Channel when a conversation asks who is in
view. They present the Host service token; the device upload tokens that guard
``/v1/burst`` and ``/v1/look`` do not open these routes.

The image is decoded, used, and dropped when the request returns. Templates
arrive with the request and are not kept. The audit row holds counts only.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import time
from dataclasses import asdict

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

from ..adapters.codec import decode_jpeg
from ..runtime.faces import (
    FaceEncoder,
    FacePolicy,
    FaceTemplate,
    TemplateMismatch,
    compare,
    enroll,
)
from ..runtime.ports import AuditSink
from ..runtime.types import RequestContext
from .config import Settings

FEATURE_SCHEMA_VERSION = 1
MAX_TEMPLATES = 200


def register_face_routes(
    app: FastAPI,
    settings: Settings,
    service: tuple[FaceEncoder, FacePolicy] | None,
    audit: AuditSink | None,
) -> None:
    def _authorize(authorization: str | None) -> None:
        token = settings.service_token
        if service is None or not token:
            raise HTTPException(status_code=503, detail="face identity is not configured")
        presented = (authorization or "").removeprefix("Bearer ")
        if not hmac.compare_digest(presented.encode(), token.encode()):
            raise HTTPException(status_code=401, detail="service token required")

    async def _frame(image: UploadFile):
        data = await image.read(settings.face_max_image_bytes + 1)
        if len(data) > settings.face_max_image_bytes:
            raise HTTPException(status_code=413, detail="image too large")
        try:
            return decode_jpeg(data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def _record(owner_id: str, device_id: str, correlation_id: str, trigger: str, **fields):
        if audit is None:
            return
        ctx = RequestContext(
            owner_id=owner_id,
            device_id=device_id,
            epoch=0,
            trigger=trigger,
            correlation_id=correlation_id,
            ts_ms=time.time_ns() // 1_000_000,
        )
        await audit.record(ctx, "face_identity", egress=False, pixels_retained_ms=0, **fields)

    @app.post("/v1/faces/embed")
    async def embed(
        image: UploadFile = File(...),
        owner_id: str = Form(..., min_length=1, max_length=128),
        correlation_id: str = Form(default="enroll", max_length=128),
        authorization: str | None = Header(default=None),
    ) -> dict:
        _authorize(authorization)
        encoder, policy = service
        frame = await _frame(image)
        started = time.monotonic()
        result = await asyncio.to_thread(enroll, encoder, policy, frame)
        await _record(
            owner_id,
            "host",
            correlation_id,
            "face_enroll",
            faces=result.faces,
            outcome="accepted" if result.accepted else result.rejection,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return {
            "accepted": result.accepted,
            "faces": result.faces,
            "rejection": result.rejection,
            "face_px": result.face_px,
            "model_id": encoder.model_id,
            "weights_hash": getattr(encoder, "weights_hash", ""),
            "preprocessing_version": encoder.preprocessing_version,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "vector": list(result.vector) if result.vector is not None else None,
        }

    @app.post("/v1/faces/match")
    async def match(
        image: UploadFile = File(...),
        templates: str = Form(...),
        owner_id: str = Form(..., min_length=1, max_length=128),
        device_id: str = Form(default="", max_length=128),
        correlation_id: str = Form(default="match", max_length=128),
        authorization: str | None = Header(default=None),
    ) -> dict:
        _authorize(authorization)
        encoder, policy = service
        try:
            rows = json.loads(templates)
            if not isinstance(rows, list) or len(rows) > MAX_TEMPLATES:
                raise ValueError("templates must be a list of bounded length")
            parsed = [
                FaceTemplate(
                    ref=str(row["ref"]),
                    vector=tuple(float(v) for v in row["vector"]),
                    model_id=str(row["model_id"]),
                    preprocessing_version=str(row["preprocessing_version"]),
                )
                for row in rows
            ]
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=f"bad templates: {exc}") from exc

        frame = await _frame(image)
        started = time.monotonic()
        try:
            result = await asyncio.to_thread(compare, encoder, policy, frame, parsed)
        except TemplateMismatch as exc:
            # The caller's templates were made by another model: they need
            # re-enrolling, and comparing them anyway would produce noise.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        await _record(
            owner_id,
            device_id or "unknown",
            correlation_id,
            "face_match",
            faces=len(result.faces) + result.faces_dropped,
            templates=result.templates_compared,
            outcome="compared",
            latency_ms=latency_ms,
        )
        return {
            "faces": [asdict(face) for face in result.faces],
            "faces_dropped": result.faces_dropped,
            "model_id": result.model_id,
            "preprocessing_version": encoder.preprocessing_version,
            "policy_version": result.policy_version,
            "confidence": policy.confidence,
            "latency_ms": latency_ms,
        }

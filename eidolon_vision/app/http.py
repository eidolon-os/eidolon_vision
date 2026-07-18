"""FastAPI transport: burst (async facts), look (sync VLM), health.

Image bytes arrive here directly from the device (never through the Hub). The
Hub only issued the scoped token this endpoint verifies, and later re-validates
the facts we emit. Frames are decoded, run through the pipeline, and dropped.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from loguru import logger

from ..aggregate.fatigue import FatigueAggregator
from ..core import auth
from ..core.pipeline import Pipeline, decode_jpeg
from ..detect.base import Detector
from ..emit.hub_ingress import HubIngress
from ..vlm import look as vlm_look
from .config import Settings, load_settings


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization[len("Bearer ") :]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="eidolon_vision", version="0.1.0")

    ingress = HubIngress(base_url=settings.hub_base_url)

    # Best-effort detector construction: the app still boots for /look and
    # /healthz if the face model asset is absent (fatigue simply unavailable).
    detectors: dict[str, Detector] = {}
    try:
        from ..detect.face_landmarker import FaceLandmarkerDetector

        face = FaceLandmarkerDetector(model_asset_path=settings.face_model_path)
        detectors["fatigue_sample"] = face
    except Exception as exc:  # missing asset / mediapipe not installed
        logger.warning("face detector unavailable: {}", exc)

    def _aggregator_factory(ctx) -> FatigueAggregator:
        det = detectors.get("fatigue_sample")
        model_id = getattr(det, "model_id", "unknown")
        model_version = getattr(det, "model_version", "unknown")
        return FatigueAggregator(model_id=model_id, model_version=model_version)

    pipeline = Pipeline(detectors=detectors, aggregator_factory=_aggregator_factory)

    @app.get("/healthz")
    async def healthz() -> dict:
        # §11.2(d): non-sensitive health/capability surface.
        return {
            "status": "ok",
            "version": app.version,
            "detectors": sorted(detectors.keys()),
        }

    @app.post("/v1/burst", status_code=202)
    async def burst(
        trigger: str = Form(...),
        correlation_id: str = Form(...),
        epoch: int = Form(...),
        ts_ms: int = Form(...),
        frames: list[UploadFile] = File(...),
        authorization: str | None = Header(default=None),
    ) -> dict:
        try:
            grant = auth.verify_upload_token(_bearer(authorization), hub_public_key=settings.hub_public_key)
            auth.authorize_trigger(grant, trigger)
        except auth.TokenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        ctx = auth.context_from_grant(
            grant, trigger=trigger, correlation_id=correlation_id, epoch=epoch, ts_ms=ts_ms
        )
        decoded = []
        for f in frames:
            try:
                decoded.append(decode_jpeg(await f.read()))
            except ValueError:
                continue  # skip a bad frame; a burst tolerates partial loss

        facts = pipeline.process(decoded, ctx, _now_ms())
        emitted = 0
        for fact in facts:
            if await ingress.emit(fact):
                emitted += 1
        return {"accepted": True, "frames": len(decoded), "facts_emitted": emitted}

    @app.post("/v1/look")
    async def look(
        question: str = Form(...),
        image: UploadFile = File(...),
        authorization: str | None = Header(default=None),
    ) -> dict:
        try:
            grant = auth.verify_upload_token(_bearer(authorization), hub_public_key=settings.hub_public_key)
            auth.authorize_trigger(grant, "user_look")
        except auth.TokenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        answer = await vlm_look.look(
            image_jpeg=await image.read(), question=question, model=settings.vlm_model
        )
        return {"answer": answer}

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await ingress.aclose()

    return app

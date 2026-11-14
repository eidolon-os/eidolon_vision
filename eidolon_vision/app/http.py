"""FastAPI transport: burst (facts), look (answer), audit, health.

Image bytes arrive here straight from the device and never through the Hub. The
Hub only issued the scoped token this module verifies. Frames are decoded, run
through the graph, and dropped when the request returns.

The transport knows about triggers because the *token* is scoped by trigger — it
never knows which capability serves one. That lookup belongs to the registry.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from loguru import logger

from ..adapters.codec import decode_jpeg
from ..runtime import auth
from ..runtime.graph import CapabilityUnavailable, EgressNotAuthorized, IntentUnsupported
from ..runtime.types import RequestContext
from .bootstrap import build_face_service, build_graph
from .config import Settings, load_settings
from .faces_http import face_routes_usable, register_face_routes


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization[len("Bearer ") :]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="eidolon_vision", version="0.2.0")
    graph = build_graph(settings, clock_ms=_now_ms)
    faces = build_face_service(settings)

    def _context(grant: auth.UploadGrant, **kw) -> RequestContext:
        return RequestContext(owner_id=grant.owner_id, device_id=grant.device_id, **kw)

    def _authorize(authorization: str | None, trigger: str) -> auth.UploadGrant:
        try:
            grant = auth.verify_upload_token(
                _bearer(authorization), hub_public_key=settings.hub_public_key
            )
            auth.authorize_trigger(grant, trigger)
        except auth.TokenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return grant

    @app.get("/healthz")
    async def healthz() -> dict:
        return {
            "status": "ok",
            "version": app.version,
            "capabilities": graph.capabilities(),
            "triggers": graph.triggers(),
            "roles_bound": graph.bound_roles(),
            "interpreters": graph.interpreter_names(),
            "face_identity": face_routes_usable(settings, faces),
        }

    @app.post("/v1/burst", status_code=202)
    async def burst(
        trigger: str = Form(...),
        correlation_id: str = Form(...),
        epoch: int = Form(...),
        ts_ms: int = Form(...),
        device_signals: str = Form(default="{}"),
        frames: list[UploadFile] = File(default=[]),
        authorization: str | None = Header(default=None),
    ) -> dict:
        grant = _authorize(authorization, trigger)
        try:
            signals = {k: float(v) for k, v in json.loads(device_signals).items()}
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(status_code=400, detail=f"bad device_signals: {exc}") from exc

        decoded = []
        for seq, upload in enumerate(frames):
            try:
                decoded.append(decode_jpeg(await upload.read(), seq=seq, ts_ms=ts_ms))
            except ValueError:
                continue  # a burst tolerates partial loss

        ctx = _context(
            grant,
            epoch=epoch,
            trigger=trigger,
            correlation_id=correlation_id,
            ts_ms=ts_ms,
            device_signals=signals,
        )
        try:
            facts = await graph.observe(decoded, ctx)
        except CapabilityUnavailable as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"accepted": True, "frames": len(decoded), "facts": len(facts)}

    @app.post("/v1/look")
    async def look(
        question: str = Form(...),
        image: UploadFile = File(...),
        correlation_id: str = Form(default="look"),
        # Declared by the caller: the companion already knows whether the owner
        # said "read this" or "what is this". See runtime.types.LOOK_INTENTS.
        intent: str = Form(default="read"),
        allow_egress: bool = Form(default=False),
        authorization: str | None = Header(default=None),
    ) -> dict:
        trigger = "user_look"
        grant = _authorize(authorization, trigger)
        try:
            frame = decode_jpeg(await image.read())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        ctx = _context(
            grant,
            epoch=0,
            trigger=trigger,
            correlation_id=correlation_id,
            ts_ms=_now_ms(),
        )
        try:
            answer = await graph.ask(
                [frame], question, ctx, intent=intent, allow_egress=allow_egress
            )
        except IntentUnsupported as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EgressNotAuthorized as exc:
            # 428: the request is well-formed but a precondition — the owner's
            # consent to send this frame off the machine — has not been met.
            raise HTTPException(status_code=428, detail=str(exc)) from exc
        except CapabilityUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return {
            "answer": answer.text,
            "intent": intent,
            "engine": answer.engine,
            "egress": answer.egress,
            "latency_ms": answer.latency_ms,
        }

    @app.get("/v1/audit")
    async def audit(limit: int = 50) -> dict:
        """The sovereignty promise, readable. Newest last, capped."""
        path = Path(settings.audit_log_path)
        if not path.exists():
            return {"rows": []}
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        return {"rows": [json.loads(line) for line in lines if line.strip()]}

    from ..adapters.sink.jsonl_audit import JsonlAuditSink

    register_face_routes(app, settings, faces, JsonlAuditSink(settings.audit_log_path))

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await graph.aclose()

    logger.info("eidolon_vision up: capabilities={}", graph.capabilities())
    return app

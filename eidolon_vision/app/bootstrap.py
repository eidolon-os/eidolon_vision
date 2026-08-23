"""The one file that knows which implementation fills which role.

Everything above this line asks for roles and declarations; everything below it
is a concrete class. Moving a judgement between the device and the host, or
swapping an OCR engine for another, is an edit *here* — capability code does not
change and does not find out.

This is also the only module allowed to import from every layer.
"""

from __future__ import annotations

from collections.abc import Sequence

from loguru import logger

from ..runtime.graph import PerceptionGraph
from ..runtime.ports import Interpreter, Perceptor
from ..runtime.registry import CapabilityRegistry
from .config import Settings


def build_registry(enabled: Sequence[str]) -> CapabilityRegistry:
    """Register the capabilities named in config, skipping any that are absent.

    A capability whose package has been deleted simply does not appear. That is
    the point: removal is a local operation, not a refactor.
    """
    registry = CapabilityRegistry()
    for name in enabled:
        try:
            module = __import__(f"eidolon_vision.capabilities.{name}", fromlist=["SPEC"])
        except ImportError as exc:
            logger.warning("capability {!r} not available: {}", name, exc)
            continue
        registry.register(module.SPEC)
        logger.info("capability enabled: {}", name)
    return registry


def build_perceptors(settings: Settings, needed_roles: frozenset[str]) -> dict[str, Perceptor]:
    """Bind roles to implementations. Only build what the enabled set asks for.

    An adapter whose optional extra or model asset is missing leaves its role
    unfilled and logs it — the service still starts and every other capability
    still works. A capability that needed that role fails at request time with a
    clear reason, which is the right blast radius.

    ``presence`` is the interesting row: flip ``presence_source`` between the
    device-reported adapter and the host-side MediaPipe one and no capability
    notices the difference.
    """
    perceptors: dict[str, Perceptor] = {}

    def _bind(role: str, build) -> None:
        if role not in needed_roles:
            return
        try:
            perceptors[role] = build()
        except Exception as exc:  # missing extra, missing model asset, bad path
            logger.warning("role {!r} unavailable: {}", role, exc)

    def _presence():
        if settings.presence_source == "host":
            from ..adapters.perceptor.mediapipe_face import MediaPipeFacePresencePerceptor

            return MediaPipeFacePresencePerceptor(model_asset_path=settings.face_model_path)
        from ..adapters.perceptor.device_reported import DeviceReportedPerceptor

        return DeviceReportedPerceptor(role="presence", signal_key="person_score")

    def _face_metrics():
        from ..adapters.perceptor.mediapipe_face import MediaPipeFaceMetricsPerceptor

        return MediaPipeFaceMetricsPerceptor(model_asset_path=settings.face_model_path)

    _bind("presence", _presence)
    _bind("face_metrics", _face_metrics)

    unfilled = needed_roles - set(perceptors)
    if unfilled:
        logger.warning("no perceptor bound for roles: {}", sorted(unfilled))
    return perceptors


def build_interpreters(settings: Settings) -> list[Interpreter]:
    """Local first, egress last. The order *is* the sovereignty policy."""
    chain: list[Interpreter] = []

    if settings.enable_local_ocr:
        try:
            from ..adapters.interpreter.rapidocr import RapidOcrInterpreter

            chain.append(RapidOcrInterpreter())
        except Exception as exc:  # optional extra not installed
            logger.warning("local OCR unavailable: {}", exc)

    if settings.enable_cloud_vlm:
        from ..adapters.interpreter.cloud_vlm import CloudVlmInterpreter

        chain.append(CloudVlmInterpreter(model=settings.vlm_model))

    logger.info("interpreter chain: {}", [i.name for i in chain])
    return chain


def build_graph(settings: Settings, *, clock_ms) -> PerceptionGraph:
    registry = build_registry(settings.enabled_capabilities)

    fact_sinks = []
    if settings.hub_base_url:
        from ..adapters.sink.hub_ingress import HubIngress

        fact_sinks.append(HubIngress(base_url=settings.hub_base_url))

    from ..adapters.sink.jsonl_audit import JsonlAuditSink

    return PerceptionGraph(
        registry=registry,
        perceptors=build_perceptors(settings, registry.required_roles()),
        interpreters=build_interpreters(settings),
        fact_sinks=fact_sinks,
        audit=JsonlAuditSink(settings.audit_log_path),
        clock_ms=clock_ms,
    )

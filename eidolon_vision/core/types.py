"""Shared internal types for the vision pipeline.

Wire-facing contracts (the ``sense.*`` facts the worker emits) live in the SDK
— ``eidolon_sdk.biz.sense`` — and are the single source of truth. Everything
here is worker-internal and never crosses the wire.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Authorized burst purposes. Mirrors the device-declared trigger enum; a token
# grants a subset and the worker refuses triggers outside it (§11.2).
Trigger = str  # one of: "fatigue_sample" | "away_watch" | "user_look"
AUTHORIZED_TRIGGERS: frozenset[str] = frozenset({"fatigue_sample", "away_watch", "user_look"})


@dataclass(frozen=True, slots=True)
class Frame:
    """A single decoded frame. Owned by the pipeline; discarded after the burst.

    ``pixels`` is a decoded image (BGR ndarray in practice); typed loosely here
    to keep this module import-light (no numpy/opencv dependency for pure
    logic + tests).
    """

    pixels: object
    width: int
    height: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class BurstContext:
    """Binding-scoped context resolved from the verified upload token."""

    guard_companion_id: str
    device_id: str
    guard_epoch: int
    trigger: Trigger
    correlation_id: str
    ts_ms: int


@dataclass(frozen=True, slots=True)
class Observation:
    """One detector output for one frame. Stateless; fed to an Aggregator.

    ``kind`` names the detector family ("face" | "object"); ``metrics`` carries
    only bounded scalars (e.g. mar/ear, or a class confidence).
    """

    kind: str
    metrics: dict[str, float] = field(default_factory=dict)
    label: str | None = None
    confidence: float | None = None

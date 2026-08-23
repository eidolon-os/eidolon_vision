"""Framework-internal value types.

Nothing here names a capability. The wire-facing contracts (``sense.*``) live in
``eidolon_sdk.biz.sense`` and are the single source of truth; these types are
the runtime's own vocabulary for moving data between ports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Perceptor roles — the framework's vocabulary.
#
# A role is *what kind of judgement* a perceptor produces, never *who produces
# it* and never *which capability consumes it*. Capabilities request roles;
# bootstrap decides which adapter fills each role. That indirection is what
# lets a judgement move between device and host as a deployment choice.
# ---------------------------------------------------------------------------
PerceptorRole = str
PERCEPTOR_ROLES: frozenset[str] = frozenset(
    {
        "presence",       # is a person there at all (boolean-ish, thresholdable)
        "identity",       # is it the owner (device-only by policy; never host-side)
        "face_metrics",   # bounded facial scalars (aspect ratios, head pose)
        "objects",        # coarse object classes with boxes
    }
)


@dataclass(frozen=True, slots=True)
class Frame:
    """One decoded frame. Owned by the graph; dropped when the call returns.

    ``pixels`` is typed loosely (a BGR ndarray in practice) so this module stays
    import-light — pure-logic tests must not need numpy or opencv.
    """

    pixels: object
    width: int
    height: int
    seq: int = 0
    ts_ms: int = 0


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Owner-scoped context for one graph invocation, resolved from a token.

    ``trigger`` is the device-declared purpose and the token's authorization
    scope. The runtime uses it only to *look up* a capability in the registry —
    it never branches on its value.
    """

    owner_id: str
    device_id: str
    epoch: int
    trigger: str
    correlation_id: str
    ts_ms: int

    # Bounded scalars the device already computed and sent along. This is how a
    # device acts as a remote perceptor: its judgement arrives with the request
    # instead of being derived from pixels here. Same shape either way, which is
    # what makes "where does this run" a deployment choice.
    device_signals: dict[str, float] = field(default_factory=dict, hash=False)


@dataclass(frozen=True, slots=True)
class Observation:
    """One perceptor output for one frame. Stateless; fed to an Aggregator.

    ``metrics`` carries only bounded scalars. ``bbox`` and ``track_id`` exist so
    a Tracker can establish cross-frame identity — without them, anything beyond
    single-frame judgement has to fight detection jitter in the decision layer.
    """

    role: PerceptorRole
    metrics: dict[str, float] = field(default_factory=dict)
    label: str | None = None
    confidence: float | None = None
    bbox: tuple[float, float, float, float] | None = None  # normalized xyxy
    track_id: int | None = None


@dataclass(frozen=True, slots=True)
class Answer:
    """The result of an owner-initiated question. Never enters the control plane.

    ``engine`` names the tier that answered and ``egress`` records whether pixels
    left the owner's machine to produce it. Both ride into the audit record —
    that pair is the whole sovereignty claim, so it is not optional.
    """

    text: str
    engine: str
    egress: bool
    latency_ms: int

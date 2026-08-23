"""The seven ports. Protocols only — no implementation, no capability names.

Every port is optional from a capability's point of view: a capability declares
the ones it uses and leaves the rest unset. Forcing all seven on everyone would
turn decoupling into a boilerplate tax.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from .types import Answer, Frame, Observation, PerceptorRole, RequestContext


class CannotAnswer(Exception):
    """An interpreter is not applicable to this frame or question.

    Part of the :class:`Interpreter` contract, not an error: a text engine that
    finds no text says so and the graph falls through to the next tier. Raising
    this is how the local-first ordering stays cheap.
    """


@runtime_checkable
class Source(Protocol):
    """Where frames come from, normalized so nothing above knows the origin."""

    name: str

    def frames(self, ctx: RequestContext) -> AsyncIterator[Frame]: ...


@runtime_checkable
class Gate(Protocol):
    """Which frames are worth spending a model on.

    Cheapest layer in the stack and the only real knob on power and cost. A
    device-side gate is strictly better than a host-side one, because a frame
    rejected on the device was never transmitted.
    """

    def admit(self, frame: Frame, ctx: RequestContext) -> bool: ...


@runtime_checkable
class Perceptor(Protocol):
    """Frames in, observations out. Stateless — this is load-bearing.

    ``role`` is what this perceptor *is for*; bootstrap binds roles to instances.
    ``model_id`` / ``model_version`` ride out on every fact for auditability, so
    swapping a model stays visible downstream without a contract change.
    """

    role: PerceptorRole
    model_id: str
    model_version: str

    def infer(self, frames: Sequence[Frame], ctx: RequestContext) -> list[Observation]: ...


@runtime_checkable
class Tracker(Protocol):
    """Cross-frame identity. Turns statistical guessing into a state machine."""

    def update(self, observations: Sequence[Observation], now_ms: int) -> list[Observation]: ...


@runtime_checkable
class Aggregator(Protocol):
    """Observations in, bounded facts out. The only stateful port.

    ``now_ms`` is injected rather than read from a clock so every decision rule
    is unit-testable without sleeping or patching time.
    """

    def observe(self, observation: Observation, ctx: RequestContext, now_ms: int) -> object | None: ...


@runtime_checkable
class Interpreter(Protocol):
    """Open-ended semantics: frames plus a question, out comes text.

    Deliberately returns an :class:`Answer`, not a fact — an interpreter result
    answers a person and is then gone. It never enters the control plane.
    """

    name: str
    egress: bool  # does producing this answer send pixels off the owner's machine

    async def ask(self, frames: Sequence[Frame], question: str) -> Answer: ...


@runtime_checkable
class FactSink(Protocol):
    """Where facts go. Compose several to fan out (hub + audit + metrics)."""

    async def emit(self, fact: object) -> bool: ...


@runtime_checkable
class AuditSink(Protocol):
    """Where the record of *having looked* goes.

    Separate from :class:`FactSink` on purpose: facts are a control-plane
    concern, audit is a promise to the owner. An answer that produces no fact
    still produces an audit row.
    """

    async def record(self, ctx: RequestContext, capability: str, **fields: object) -> None: ...

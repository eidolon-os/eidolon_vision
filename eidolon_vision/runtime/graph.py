"""The perception graph: assemble a capability's declared ports and drive them.

Two entry points, because there are genuinely two shapes of work and pretending
otherwise would be over-abstraction:

* :meth:`PerceptionGraph.observe` — the fact path (system-push capabilities).
* :meth:`PerceptionGraph.ask` — the answer path (owner-pull capabilities).

The graph branches on a capability's *declared* ``output``, never on its name.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from loguru import logger

from .ports import AuditSink, CannotAnswer, FactSink, Gate, Interpreter, Perceptor, Tracker
from .registry import CapabilityRegistry
from .spec import CapabilitySpec
from .types import LOOK_INTENTS, Answer, Frame, Observation, RequestContext


class CapabilityUnavailable(LookupError):
    """No enabled capability serves this trigger, or a needed role is unfilled."""


class IntentUnsupported(LookupError):
    """No engine serves the declared intent.

    Distinct from :class:`EgressNotAuthorized`: nothing was withheld for consent
    reasons, there is simply no engine that can do this kind of work. Saying so
    beats letting an engine that ignores the question answer it anyway.
    """


class EgressNotAuthorized(PermissionError):
    """Only a pixel-egressing engine could answer, and the caller did not allow it.

    Not a failure — the intended outcome when a local engine cannot answer and
    the owner has not (yet) authorized sending the frame off their machine.
    """


class PerceptionGraph:
    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        perceptors: dict[str, Perceptor],
        interpreters: Sequence[Interpreter] = (),
        gate: Gate | None = None,
        tracker: Tracker | None = None,
        fact_sinks: Sequence[FactSink] = (),
        audit: AuditSink | None = None,
        clock_ms: Callable[[], int],
    ) -> None:
        self._registry = registry
        self._perceptors = perceptors            # role -> instance
        self._interpreters = tuple(interpreters)  # ordered: local first, egress last
        self._gate = gate
        self._tracker = tracker
        self._fact_sinks = tuple(fact_sinks)
        self._audit = audit
        self._now = clock_ms
        self._aggregators: dict[str, object] = {}

    # -- introspection (health surface; non-sensitive by construction) -----

    def capabilities(self) -> tuple[str, ...]:
        return self._registry.names()

    def triggers(self) -> tuple[str, ...]:
        return self._registry.triggers()

    def bound_roles(self) -> tuple[str, ...]:
        return tuple(sorted(self._perceptors))

    def interpreter_names(self) -> tuple[str, ...]:
        return tuple(i.name for i in self._interpreters)

    async def aclose(self) -> None:
        for sink in self._fact_sinks:
            closer = getattr(sink, "aclose", None)
            if closer is not None:
                await closer()

    # -- resolution -------------------------------------------------------

    def _spec_for(self, trigger: str) -> CapabilitySpec:
        spec = self._registry.route(trigger)
        if spec is None:
            raise CapabilityUnavailable(f"no capability serves trigger {trigger!r}")
        missing = [r for r in spec.needs_roles if r not in self._perceptors]
        if missing:
            raise CapabilityUnavailable(f"{spec.name}: no perceptor bound for {missing}")
        return spec

    def _aggregator_for(self, spec: CapabilitySpec, ctx: RequestContext):
        """One aggregator instance per (capability, owner, device) — the only state."""
        key = f"{spec.name}:{ctx.owner_id}:{ctx.device_id}"
        agg = self._aggregators.get(key)
        if agg is None:
            assert spec.aggregator_factory is not None  # guaranteed by SpecError
            agg = spec.aggregator_factory()
            self._aggregators[key] = agg
        return agg

    def _admit(self, frames: Sequence[Frame], ctx: RequestContext) -> list[Frame]:
        if self._gate is None:
            return list(frames)
        return [f for f in frames if self._gate.admit(f, ctx)]

    # -- fact path --------------------------------------------------------

    async def observe(self, frames: Sequence[Frame], ctx: RequestContext) -> list[object]:
        spec = self._spec_for(ctx.trigger)
        admitted = self._admit(frames, ctx)
        now = self._now()

        observations: list[Observation] = []
        for role in spec.needs_roles:
            observations.extend(self._perceptors[role].infer(admitted, ctx))
        if self._tracker is not None:
            observations = self._tracker.update(observations, now)

        aggregator = self._aggregator_for(spec, ctx)
        facts = [
            fact
            for fact in (aggregator.observe(o, ctx, now) for o in observations)
            if fact is not None
        ]

        emitted = 0
        for fact in facts:
            for sink in self._fact_sinks:
                if await sink.emit(fact):
                    emitted += 1

        if self._audit is not None:
            await self._audit.record(
                ctx,
                spec.name,
                frames_in=len(frames),
                frames_admitted=len(admitted),
                observations=len(observations),
                facts=len(facts),
                facts_emitted=emitted,
                egress=False,          # the fact path never leaves the machine
                pixels_retained_ms=0,
            )
        return facts

    # -- answer path ------------------------------------------------------

    async def ask(
        self,
        frames: Sequence[Frame],
        question: str,
        ctx: RequestContext,
        *,
        intent: str = "read",
        allow_egress: bool = False,
    ) -> Answer:
        """Route to engines that serve the declared intent; local ones first.

        ``intent`` comes from the caller because the caller already knows it —
        the companion's LLM heard the owner ask. Guessing it here from the
        question string would be re-deriving something upstream had for free,
        and getting it wrong means a text extractor confidently transcribing in
        answer to "how many toys are on the desk".

        Ordering within an intent is local-first, so the sovereign path is the
        default and the cloud is what you fall through to.
        """
        spec = self._spec_for(ctx.trigger)
        if not spec.needs_interpreter:
            raise CapabilityUnavailable(f"{spec.name}: not an answering capability")
        if intent not in LOOK_INTENTS:
            raise IntentUnsupported(f"unknown intent {intent!r}; known: {sorted(LOOK_INTENTS)}")

        candidates = [i for i in self._interpreters if intent in i.serves]
        if not candidates:
            if self._audit is not None:
                await self._audit.record(
                    ctx, spec.name, question=question, answer=None, engine=None,
                    egress=False, outcome="intent_unsupported", pixels_retained_ms=0,
                )
            raise IntentUnsupported(f"no engine serves intent {intent!r}")

        started = self._now()
        held_back = False
        for interpreter in candidates:
            if interpreter.egress and not allow_egress:
                held_back = True
                continue
            try:
                answer = await interpreter.ask(frames, question)
            except CannotAnswer as exc:
                logger.debug("{} declined: {}", interpreter.name, exc)
                continue
            if self._audit is not None:
                await self._audit.record(
                    ctx,
                    spec.name,
                    question=question,
                    answer=answer.text,
                    engine=answer.engine,
                    egress=answer.egress,
                    latency_ms=answer.latency_ms,
                    pixels_retained_ms=0,
                )
            return answer

        if self._audit is not None:
            await self._audit.record(
                ctx,
                spec.name,
                question=question,
                answer=None,
                engine=None,
                egress=False,
                latency_ms=self._now() - started,
                outcome="egress_not_authorized" if held_back else "no_engine",
                pixels_retained_ms=0,
            )
        if held_back:
            raise EgressNotAuthorized(
                "no local engine could answer; sending the frame off this machine "
                "needs the owner's explicit approval"
            )
        raise CapabilityUnavailable("no interpreter could answer")

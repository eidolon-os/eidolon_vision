"""Graph tests with fakes — no models, no network, no mock framework.

That these run with mediapipe, rapidocr and litellm all uninstalled is the point:
if the pure paths needed a model, the layering would be wrong.
"""

from __future__ import annotations

import pytest

from eidolon_vision.runtime.graph import (
    CapabilityUnavailable,
    EgressNotAuthorized,
    IntentUnsupported,
    PerceptionGraph,
)
from eidolon_vision.runtime.ports import CannotAnswer
from eidolon_vision.runtime.registry import CapabilityRegistry
from eidolon_vision.runtime.spec import CapabilitySpec
from eidolon_vision.runtime.types import Answer, Frame, Observation, RequestContext

# -- fakes -------------------------------------------------------------------


class FakePresence:
    role = "presence"
    model_id = "fake"
    model_version = "v1"

    def infer(self, frames, ctx):
        return [Observation(role="presence", label="present", confidence=1.0) for _ in frames]


class CountingAggregator:
    """Fires a fact on the second observation, so cooldown logic is observable."""

    def __init__(self) -> None:
        self.seen = 0

    def observe(self, observation, ctx, now_ms):
        self.seen += 1
        return {"fact": "present", "n": self.seen} if self.seen == 2 else None


class RecordingSink:
    def __init__(self) -> None:
        self.facts: list[object] = []

    async def emit(self, fact):
        self.facts.append(fact)
        return True


class RecordingAudit:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def record(self, ctx, capability, **fields):
        self.rows.append({"capability": capability, **fields})


class LocalEngine:
    """Stands in for a text extractor: serves `read` only, ignores the question."""

    name = "local"
    egress = False
    serves = frozenset({"read"})

    def __init__(self, *, answers: bool = True) -> None:
        self._answers = answers

    async def ask(self, frames, question):
        if not self._answers:
            raise CannotAnswer("nothing to read")
        return Answer(text="local answer", engine=self.name, egress=False, latency_ms=1)


class CloudEngine:
    """Stands in for a VLM: reads the question, so it serves both intents."""

    name = "cloud"
    egress = True
    serves = frozenset({"read", "describe"})

    async def ask(self, frames, question):
        return Answer(text="cloud answer", engine=self.name, egress=True, latency_ms=2)


# -- fixtures ----------------------------------------------------------------

FACT_SPEC = CapabilitySpec(
    name="probe_fact",
    serves_triggers=("probe_push",),
    initiative="system-push",
    output="fact",
    authz="standing-lease",
    arbitration=("shared", "safe"),
    needs_roles=("presence",),
    aggregator_factory=CountingAggregator,
)

ANSWER_SPEC = CapabilitySpec(
    name="probe_answer",
    serves_triggers=("probe_pull",),
    initiative="owner-pull",
    output="answer",
    authz="per-request",
    arbitration=("shared", "safe"),
    needs_interpreter=True,
)


def _ctx(trigger: str) -> RequestContext:
    return RequestContext(
        owner_id="o1",
        device_id="d1",
        epoch=1,
        trigger=trigger,
        correlation_id="c1",
        ts_ms=1_000,
    )


def _frames(n: int = 1) -> list[Frame]:
    return [Frame(pixels=None, width=64, height=64, seq=i) for i in range(n)]


def _graph(*, specs, interpreters=(), sink=None, audit=None, perceptors=None):
    registry = CapabilityRegistry()
    for spec in specs:
        registry.register(spec)
    return PerceptionGraph(
        registry=registry,
        perceptors=perceptors if perceptors is not None else {"presence": FakePresence()},
        interpreters=interpreters,
        fact_sinks=[sink] if sink else (),
        audit=audit,
        clock_ms=lambda: 5_000,
    )


# -- fact path ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_fact_path_emits_and_audits():
    sink, audit = RecordingSink(), RecordingAudit()
    graph = _graph(specs=[FACT_SPEC], sink=sink, audit=audit)

    assert await graph.observe(_frames(1), _ctx("probe_push")) == []
    facts = await graph.observe(_frames(1), _ctx("probe_push"))

    assert len(facts) == 1
    assert sink.facts == facts
    assert len(audit.rows) == 2
    assert audit.rows[-1]["egress"] is False
    assert audit.rows[-1]["pixels_retained_ms"] == 0


@pytest.mark.asyncio
async def test_aggregator_state_is_per_owner_device():
    graph = _graph(specs=[FACT_SPEC])
    other = RequestContext(
        owner_id="o2", device_id="d1", epoch=1,
        trigger="probe_push", correlation_id="c1", ts_ms=1_000,
    )
    # One observation each: neither reaches the aggregator's threshold of two,
    # which only holds if the two owners got separate instances.
    assert await graph.observe(_frames(1), _ctx("probe_push")) == []
    assert await graph.observe(_frames(1), other) == []


@pytest.mark.asyncio
async def test_unknown_trigger_is_a_lookup_failure_not_a_crash():
    graph = _graph(specs=[FACT_SPEC])
    with pytest.raises(CapabilityUnavailable):
        await graph.observe(_frames(1), _ctx("nobody_serves_this"))


@pytest.mark.asyncio
async def test_unfilled_role_is_reported_before_inference():
    graph = _graph(specs=[FACT_SPEC], perceptors={})
    with pytest.raises(CapabilityUnavailable, match="presence"):
        await graph.observe(_frames(1), _ctx("probe_push"))


# -- answer path -------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_engine_answers_without_egress():
    audit = RecordingAudit()
    graph = _graph(
        specs=[ANSWER_SPEC], interpreters=[LocalEngine(), CloudEngine()], audit=audit
    )
    answer = await graph.ask(_frames(1), "what does this say?", _ctx("probe_pull"))

    assert answer.engine == "local"
    assert answer.egress is False
    assert audit.rows[-1]["egress"] is False


@pytest.mark.asyncio
async def test_egress_is_refused_by_default_when_local_declines():
    audit = RecordingAudit()
    graph = _graph(
        specs=[ANSWER_SPEC],
        interpreters=[LocalEngine(answers=False), CloudEngine()],
        audit=audit,
    )
    with pytest.raises(EgressNotAuthorized):
        await graph.ask(_frames(1), "what is this?", _ctx("probe_pull"))

    # A refusal is still a look that happened, so it is still audited.
    assert audit.rows[-1]["outcome"] == "egress_not_authorized"
    assert audit.rows[-1]["egress"] is False


@pytest.mark.asyncio
async def test_egress_proceeds_only_with_explicit_authorization():
    graph = _graph(
        specs=[ANSWER_SPEC], interpreters=[LocalEngine(answers=False), CloudEngine()]
    )
    answer = await graph.ask(
        _frames(1), "what is this?", _ctx("probe_pull"), allow_egress=True
    )
    assert (answer.engine, answer.egress) == ("cloud", True)


@pytest.mark.asyncio
async def test_fact_capability_cannot_be_asked():
    graph = _graph(specs=[FACT_SPEC], interpreters=[LocalEngine()])
    with pytest.raises(CapabilityUnavailable, match="not an answering capability"):
        await graph.ask(_frames(1), "?", _ctx("probe_push"))


# -- intent routing ----------------------------------------------------------


@pytest.mark.asyncio
async def test_read_intent_reaches_the_local_text_engine():
    graph = _graph(specs=[ANSWER_SPEC], interpreters=[LocalEngine(), CloudEngine()])
    answer = await graph.ask(
        _frames(1), "这上面写的什么？", _ctx("probe_pull"), intent="read"
    )
    assert answer.engine == "local"


@pytest.mark.asyncio
async def test_describe_intent_never_reaches_a_text_only_engine():
    """The bug a real photo exposed: asking "how many toys" and getting a
    transcription. A text extractor must not be offered a describe question."""
    audit = RecordingAudit()
    graph = _graph(
        specs=[ANSWER_SPEC], interpreters=[LocalEngine(), CloudEngine()], audit=audit
    )
    # Without egress authorization the only describe-capable engine is held back,
    # so the outcome is a refusal — never a transcription dressed up as an answer.
    with pytest.raises(EgressNotAuthorized):
        await graph.ask(
            _frames(1), "桌上有几个玩偶？", _ctx("probe_pull"), intent="describe"
        )
    assert audit.rows[-1]["outcome"] == "egress_not_authorized"


@pytest.mark.asyncio
async def test_describe_intent_reaches_the_vlm_when_authorized():
    graph = _graph(specs=[ANSWER_SPEC], interpreters=[LocalEngine(), CloudEngine()])
    answer = await graph.ask(
        _frames(1), "桌上有几个玩偶？", _ctx("probe_pull"),
        intent="describe", allow_egress=True,
    )
    assert (answer.engine, answer.egress) == ("cloud", True)


@pytest.mark.asyncio
async def test_no_engine_for_intent_is_reported_not_faked():
    audit = RecordingAudit()
    graph = _graph(specs=[ANSWER_SPEC], interpreters=[LocalEngine()], audit=audit)
    with pytest.raises(IntentUnsupported):
        await graph.ask(_frames(1), "这是什么？", _ctx("probe_pull"), intent="describe")
    assert audit.rows[-1]["outcome"] == "intent_unsupported"


@pytest.mark.asyncio
async def test_unknown_intent_is_rejected():
    graph = _graph(specs=[ANSWER_SPEC], interpreters=[LocalEngine()])
    with pytest.raises(IntentUnsupported, match="unknown intent"):
        await graph.ask(_frames(1), "?", _ctx("probe_pull"), intent="telepathy")

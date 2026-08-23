from __future__ import annotations

from eidolon_vision.capabilities.presence_verify.aggregate import PresenceConfig, PresenceWindow
from eidolon_vision.runtime.types import Observation, RequestContext

CFG = PresenceConfig(enter_ms=600, exit_ms=12_000)


def _ctx() -> RequestContext:
    return RequestContext(
        owner_id="owner-1", device_id="atk-1", epoch=3,
        trigger="presence_sample", correlation_id="c1", ts_ms=1_700_000_000_000,
    )


def _obs(present: bool) -> Observation:
    return Observation(
        role="presence",
        label="present" if present else "absent",
        confidence=1.0 if present else 0.0,
    )


def test_arrival_needs_to_persist_past_enter_window() -> None:
    w, ctx = PresenceWindow(config=CFG), _ctx()
    assert w.observe(_obs(True), ctx, 0) is None       # first sight: candidate only
    assert w.observe(_obs(True), ctx, 500) is None     # still inside enter window
    fact = w.observe(_obs(True), ctx, 700)
    assert fact is not None and fact.state == "relaxed"


def test_departure_is_slower_than_arrival() -> None:
    w, ctx = PresenceWindow(config=CFG), _ctx()
    w.observe(_obs(True), ctx, 0)
    w.observe(_obs(True), ctx, 700)                    # now present

    w.observe(_obs(False), ctx, 1_000)
    # 700ms of absence would have been enough to call an *arrival*; a departure
    # must wait far longer, or the companion goes silent while the owner blinks.
    assert w.observe(_obs(False), ctx, 1_700) is None
    fact = w.observe(_obs(False), ctx, 14_000)
    assert fact is not None and fact.state == "away_from_screen"


def test_flicker_never_publishes() -> None:
    w, ctx = PresenceWindow(config=CFG), _ctx()
    for i in range(20):
        assert w.observe(_obs(i % 2 == 0), ctx, i * 300) is None


def test_low_confidence_is_not_treated_as_absence() -> None:
    w, ctx = PresenceWindow(config=CFG), _ctx()
    unsure = Observation(role="presence", label="present", confidence=0.1)
    w.observe(unsure, ctx, 0)
    fact = w.observe(unsure, ctx, 700)
    # Unsure resolves to absent internally, but must not publish a departure
    # before the (long) exit window — no state was ever established.
    assert fact is None


def test_other_roles_are_ignored() -> None:
    w, ctx = PresenceWindow(config=CFG), _ctx()
    assert w.observe(Observation(role="face_metrics", metrics={"mar": 0.9}), ctx, 0) is None

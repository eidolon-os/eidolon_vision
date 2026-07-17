from __future__ import annotations

from eidolon_sdk.biz.sense import SenseFatigue

from eidolon_vision.aggregate.fatigue import FatigueAggregator, FatigueConfig
from eidolon_vision.core.types import BurstContext, Observation


def _ctx() -> BurstContext:
    return BurstContext(
        guard_companion_id="guard-owner-1",
        device_id="atk-1",
        guard_epoch=3,
        trigger="fatigue_sample",
        correlation_id="sn-boot1-r5-e3",
        ts_ms=1_700_000_000_000,
    )


def _agg() -> FatigueAggregator:
    cfg = FatigueConfig(mar_yawn=0.6, window_ms=300_000, min_yawns=3, cooldown_ms=1_200_000)
    return FatigueAggregator(model_id="mediapipe-face-landmarker", model_version="mar-ear-v1", config=cfg)


def _yawn() -> Observation:
    return Observation(kind="face", metrics={"mar": 0.8, "ear": 0.3})


def _neutral() -> Observation:
    return Observation(kind="face", metrics={"mar": 0.2, "ear": 0.3})


def test_no_fact_below_threshold_count() -> None:
    agg, ctx = _agg(), _ctx()
    assert agg.observe(_yawn(), ctx, 1000) is None
    assert agg.observe(_neutral(), ctx, 2000) is None
    assert agg.observe(_yawn(), ctx, 3000) is None  # only 2 yawns


def test_fires_on_reaching_min_yawns() -> None:
    agg, ctx = _agg(), _ctx()
    assert agg.observe(_yawn(), ctx, 1000) is None
    assert agg.observe(_yawn(), ctx, 2000) is None
    fact = agg.observe(_yawn(), ctx, 3000)
    assert isinstance(fact, SenseFatigue)
    assert fact.hint == "yawn"
    assert fact.signals["yawn_count"] == 3
    assert fact.model_id == "mediapipe-face-landmarker"
    assert fact.guard_companion_id == "guard-owner-1"


def test_cooldown_suppresses_second_fact() -> None:
    agg, ctx = _agg(), _ctx()
    for t in (1000, 2000, 3000):
        agg.observe(_yawn(), ctx, t)  # fires at 3000, resets window
    # three more yawns within the cooldown window -> no second fact
    assert agg.observe(_yawn(), ctx, 4000) is None
    assert agg.observe(_yawn(), ctx, 5000) is None
    assert agg.observe(_yawn(), ctx, 6000) is None


def test_stale_yawns_fall_out_of_window() -> None:
    agg, ctx = _agg(), _ctx()
    agg.observe(_yawn(), ctx, 1000)
    agg.observe(_yawn(), ctx, 2000)
    # third yawn arrives after the first has aged out of the 300s window
    assert agg.observe(_yawn(), ctx, 1000 + 300_001) is None

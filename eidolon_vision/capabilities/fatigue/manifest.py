from __future__ import annotations

from ...runtime.spec import CapabilitySpec
from .aggregate import FatigueWindow

SPEC = CapabilitySpec(
    name="fatigue",
    serves_triggers=("fatigue_sample",),
    initiative="system-push",
    output="fact",
    authz="standing-lease",
    arbitration=("shared", "safe"),
    needs_roles=("face_metrics",),
    aggregator_factory=FatigueWindow,
)

from __future__ import annotations

from ...runtime.spec import CapabilitySpec
from .aggregate import PresenceWindow

# Asks for the `presence` role and does not care who provides it — the device's
# ESP-DL judgement and the host's frame-diff judgement are interchangeable here.
SPEC = CapabilitySpec(
    name="presence_verify",
    serves_triggers=("presence_sample",),
    initiative="system-push",
    output="fact",
    authz="standing-lease",
    arbitration=("shared", "safe"),
    needs_roles=("presence",),
    aggregator_factory=PresenceWindow,
)

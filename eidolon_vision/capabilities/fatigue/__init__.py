"""Fatigue capability.

Frozen on purpose: the aspect-ratio signal is noisy (blinking, talking and
looking down all trip it) and "you yawned, take a break" is a low-value
proactive nudge. It stays here as the reference sample for the capability
mould — and as the thing whose deletion proves the framework does not know
any capability's name.
"""

from .manifest import SPEC

__all__ = ["SPEC"]

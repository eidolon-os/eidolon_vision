"""Presence capability: is the owner at the desk.

Its only consumer should be the companion's own decision to speak or stay quiet
— not a notification to the owner. A capability that reduces interruptions costs
no trust, which is why this one is worth building before any that spends trust.
"""

from .manifest import SPEC

__all__ = ["SPEC"]

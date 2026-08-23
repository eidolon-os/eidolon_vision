"""On-demand eye: the owner points at something and asks.

The highest-value vision capability and the cheapest to trust, because the owner
initiated it. Answers locally by default; sending a frame off the machine
requires explicit per-request authorization.
"""

from .manifest import SPEC

__all__ = ["SPEC"]

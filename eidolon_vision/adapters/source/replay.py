"""Replay a directory of JPEGs as frames.

The demo and regression source: same bytes every run, so a latency number or a
decision boundary measured today is comparable to one measured next month. It is
also how the whole graph gets exercised with no device, no Hub and no network.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from ...runtime.types import Frame, RequestContext
from ..codec import decode_jpeg

_SUFFIXES = (".jpg", ".jpeg", ".png")


class ReplaySource:
    name = "replay"

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)

    def paths(self) -> list[Path]:
        return sorted(p for p in self._dir.iterdir() if p.suffix.lower() in _SUFFIXES)

    def load(self, ctx: RequestContext | None = None) -> list[Frame]:
        """Synchronous variant — what tests and one-shot measurements want."""
        frames: list[Frame] = []
        for seq, path in enumerate(self.paths()):
            frames.append(decode_jpeg(path.read_bytes(), seq=seq))
        return frames

    async def frames(self, ctx: RequestContext) -> AsyncIterator[Frame]:
        for frame in self.load(ctx):
            yield frame

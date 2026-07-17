"""Detector port (Frigate-style pluggable backends).

A Detector is stateless: frames in, observations out. Swapping or adding a
model (a future YOLO/ONNX object detector, or a GPU backend) means adding a
Detector — nothing above it changes. The ``model_id`` / ``model_version`` it
reports ride out on every fact for auditability.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from ..core.types import BurstContext, Frame, Observation


class Detector(Protocol):
    model_id: str
    model_version: str

    def infer(self, frames: Sequence[Frame], ctx: BurstContext) -> list[Observation]:
        """Run inference over a burst's frames; return one Observation per finding."""
        ...

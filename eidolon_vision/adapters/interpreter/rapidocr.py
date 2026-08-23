"""Local text engine (T1) — the sovereign default for the highest-value case.

"What does this say" is the most frequent and most valuable thing a desk
companion gets asked to look at: a sticky note, a medicine box, an error
message, a receipt. It is also the one case where a small local model beats a
large cloud one — so local-first here is not a privacy-for-quality trade, it is
both at once. That is why this interpreter sits first in the chain.

Backed by PP-OCR weights running on onnxruntime (``rapidocr-onnxruntime``), which
keeps the install to pip wheels on both arm64 Linux and Apple Silicon.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from ...runtime.ports import CannotAnswer
from ...runtime.types import Answer, Frame

ENGINE = "rapidocr-ppocr"


class RapidOcrInterpreter:
    name = ENGINE
    egress = False

    def __init__(self, *, min_score: float = 0.5, max_chars: int = 2000) -> None:
        from rapidocr_onnxruntime import RapidOCR  # lazy: heavy, optional extra

        self._ocr = RapidOCR()
        self._min_score = min_score
        self._max_chars = max_chars

    async def ask(self, frames: Sequence[Frame], question: str) -> Answer:
        """Read text off the sharpest available frame.

        The question is not interpreted — this engine only reports what is
        written. Deciding whether that answers the question is the caller's job,
        and when it does not, :class:`CannotAnswer` hands off to the next tier.
        """
        if not frames:
            raise CannotAnswer("no frames")

        started = time.perf_counter()
        lines: list[str] = []
        result, _elapsed = self._ocr(frames[-1].pixels)
        for item in result or ():
            # rapidocr returns [box, text, score] per detected line.
            text, score = item[1], float(item[2])
            if score >= self._min_score and text.strip():
                lines.append(text.strip())

        if not lines:
            raise CannotAnswer("no text found")

        joined = "\n".join(lines)[: self._max_chars]
        return Answer(
            text=joined,
            engine=ENGINE,
            egress=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

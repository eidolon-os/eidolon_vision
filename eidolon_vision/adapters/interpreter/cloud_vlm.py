"""Cloud VLM (T3) — the only port in this service that lets pixels leave.

``egress = True`` is not documentation: the graph reads it and refuses to call
this interpreter unless the request carried explicit authorization. That makes
the sovereignty boundary a runtime check rather than a convention someone can
forget.

Last in the interpreter chain by construction: local engines answer first, and
this is what you fall through to — never the default path.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Sequence

from ...runtime.ports import CannotAnswer
from ...runtime.types import Answer, Frame


class CloudVlmInterpreter:
    egress = True

    def __init__(self, *, model: str, temperature: float = 0.2) -> None:
        self._model = model
        self._temperature = temperature
        self.name = f"cloud:{model}"

    async def ask(self, frames: Sequence[Frame], question: str) -> Answer:
        import cv2  # lazy
        import litellm

        if not frames:
            raise CannotAnswer("no frames")

        ok, buf = cv2.imencode(".jpg", frames[-1].pixels)
        if not ok:
            raise CannotAnswer("frame could not be encoded")

        started = time.perf_counter()
        data_url = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
        resp = await litellm.acompletion(
            model=self._model,
            temperature=self._temperature,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        )
        text = resp["choices"][0]["message"]["content"] or ""
        return Answer(
            text=text,
            engine=self.name,
            egress=True,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

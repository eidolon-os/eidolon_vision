"""JPEG decode. Lives in adapters because it needs opencv; the runtime must not.

Lazy import keeps the pure-logic paths (registry, spec, aggregators and their
tests) importable with no vision dependencies installed at all.
"""

from __future__ import annotations

from ..runtime.types import Frame


def decode_jpeg(data: bytes, *, seq: int = 0, ts_ms: int = 0) -> Frame:
    """Decode one JPEG to a BGR :class:`Frame`. Raises ``ValueError`` if undecodable."""
    import cv2
    import numpy as np

    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("undecodable JPEG frame")
    h, w = img.shape[:2]
    return Frame(pixels=img, width=int(w), height=int(h), seq=seq, ts_ms=ts_ms)

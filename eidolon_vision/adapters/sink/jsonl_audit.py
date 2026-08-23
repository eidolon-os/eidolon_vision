"""Append-only audit log — the sovereignty promise made inspectable.

Every time this service looks at anything, one line lands here: who asked, which
engine answered, whether pixels left the machine, how long they were held. The
strict ``sense.*`` contracts already guarantee pixels do not enter the control
plane; this is what lets the *owner* see that, instead of taking it on faith.

Deliberately never records pixels, embeddings, or any frame-derived blob — only
the fact that a look happened and what came of it.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from ...runtime.types import RequestContext

# Anything not on this list is dropped rather than written. An audit log that can
# be extended by its callers is one bad patch away from becoming a media tunnel.
_ALLOWED_FIELDS = frozenset(
    {
        "question",
        "answer",
        "engine",
        "intent",
        "egress",
        "latency_ms",
        "outcome",
        "pixels_retained_ms",
        "frames_in",
        "frames_admitted",
        "observations",
        "facts",
        "facts_emitted",
    }
)


class JsonlAuditSink:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def record(self, ctx: RequestContext, capability: str, **fields: object) -> None:
        dropped = set(fields) - _ALLOWED_FIELDS
        if dropped:
            logger.warning("audit dropped unknown fields: {}", sorted(dropped))

        row = {
            "ts_ms": ctx.ts_ms,
            "owner_id": ctx.owner_id,
            "device_id": ctx.device_id,
            "correlation_id": ctx.correlation_id,
            "capability": capability,
            "trigger": ctx.trigger,
            **{k: v for k, v in fields.items() if k in _ALLOWED_FIELDS},
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

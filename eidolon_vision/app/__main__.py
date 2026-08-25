"""Serve the Vision worker on the address its own settings declare.

``config/default.yaml`` and :class:`Settings` have always carried ``host`` and
``port``, and nothing read them: the server was started through the ``uvicorn``
CLI, so the bind address came from whatever ``--port`` the caller typed, and
with no flag at all uvicorn chose 8000. The declared port was a comment.

That is how this project came to hold 8085 -- the port the workspace registry
assigns to Data's workspace API -- for a day and a half: the README said
``--port 8085``, somebody followed it, and Data then failed to bind on every
supervised restart. Fixing the README fixes one caller. Making the declaration
the thing that binds fixes the next caller too.

``python -m eidolon_vision.app`` therefore serves on ``settings.host:port``, and
``EIDOLON_VISION_PORT`` overrides it like every other setting here.
"""

from __future__ import annotations

import uvicorn

from eidolon_vision.app.config import Settings
from eidolon_vision.app.http import create_app


def main() -> None:
    settings = Settings()
    uvicorn.run(create_app(settings=settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()

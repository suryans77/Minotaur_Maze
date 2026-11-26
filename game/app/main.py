"""FastAPI game server: Phase 0 scaffold.

What exists now:

* ``GET /health``: liveness check for Docker and Kubernetes probes (FR-D-04).
* ``WS /ws``: accepts a connection, tracks it, and cleans up when the client
  disconnects.

What does not exist yet: the game loop, player movement, the Minotaur, and
the WebSocket message protocol. Gameplay messages arrive in a later phase
(Build Plan, Phase 2). Until then the server reads and discards anything a
client sends. The server is authoritative (SRS 2.4): client messages are
inputs only, and nothing a client sends can change server state.

Run from ``game/`` with ``uv run uvicorn app.main:app --reload``.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, WebSocket

from app import __version__

logger = logging.getLogger("game")


class ConnectionRegistry:
    """The WebSocket connections that are currently open on this server."""

    def __init__(self) -> None:
        self._active: set[WebSocket] = set()

    def add(self, websocket: WebSocket) -> None:
        self._active.add(websocket)

    def discard(self, websocket: WebSocket) -> None:
        self._active.discard(websocket)

    def __len__(self) -> int:
        return len(self._active)


def create_app() -> FastAPI:
    app = FastAPI(title="Minotaur Maze game server", version=__version__)
    app.state.connections = ConnectionRegistry()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "game"}

    @app.websocket("/ws")
    async def game_socket(websocket: WebSocket) -> None:
        connections: ConnectionRegistry = websocket.app.state.connections
        # Register before accepting, so the connection is counted by the time
        # the client sees the handshake complete.
        connections.add(websocket)
        try:
            await websocket.accept()
            logger.info("websocket connected (%d open)", len(connections))
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                # Phase 0: no gameplay protocol yet, so client input is discarded.
        finally:
            connections.discard(websocket)
            logger.info("websocket disconnected (%d open)", len(connections))

    return app


app = create_app()

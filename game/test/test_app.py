"""Phase 0 scaffold: the app starts, answers health checks, and accepts and
releases WebSocket connections cleanly."""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest
import uvicorn
import websockets
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app as module_app
from app.main import create_app


def open_connections(client: TestClient) -> int:
    return len(client.app.state.connections)


def test_module_exposes_an_app_for_uvicorn():
    paths = {route.path for route in module_app.routes}
    assert {"/health", "/ws"} <= paths


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "game"}


def test_each_app_instance_has_its_own_connection_registry():
    assert create_app().state.connections is not create_app().state.connections


def test_websocket_connects(client):
    assert open_connections(client) == 0
    with client.websocket_connect("/ws"):
        assert open_connections(client) == 1


def test_client_disconnect_is_cleaned_up(client):
    with client.websocket_connect("/ws") as ws:
        assert open_connections(client) == 1
        ws.close()
    assert open_connections(client) == 0


def test_disconnect_with_non_normal_close_code_is_cleaned_up(client):
    with client.websocket_connect("/ws") as ws:
        ws.close(code=1001)  # "going away", e.g. tab closed
    assert open_connections(client) == 0


def test_client_messages_are_ignored_until_the_protocol_exists(client):
    """Phase 0 has no gameplay protocol. Input of any kind must neither crash
    the server nor close the connection."""
    with client.websocket_connect("/ws") as ws:
        ws.send_text("hello")
        ws.send_json({"type": "move", "dir": "up"})
        ws.send_bytes(b"\x00\x01")
        assert open_connections(client) == 1
    assert open_connections(client) == 0


def test_connections_are_independent(client):
    with client.websocket_connect("/ws") as first:
        with client.websocket_connect("/ws"):
            assert open_connections(client) == 2
        assert open_connections(client) == 1
        first.send_text("still open")
    assert open_connections(client) == 0


def test_unknown_websocket_path_is_rejected(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/nope"):
            pass
    assert open_connections(client) == 0


# --- against a real uvicorn server ---------------------------------------------


@pytest.fixture
def live_server():
    """The app served by uvicorn on a free local port, in a background thread."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.02)
    yield app, port
    server.should_exit = True
    thread.join(timeout=10)


async def _eventually(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached in time"
        await asyncio.sleep(0.01)


def test_real_server_cleans_up_after_clean_and_abrupt_disconnects(live_server):
    """A browser tab can vanish without a close handshake. The server must
    notice and release the connection either way."""
    app, port = live_server
    url = f"ws://127.0.0.1:{port}/ws"

    def count() -> int:
        return len(app.state.connections)

    async def scenario() -> None:
        async with websockets.connect(url) as ws:
            await ws.send("hello")
            await _eventually(lambda: count() == 1)
        await _eventually(lambda: count() == 0)

        ws = await websockets.connect(url)
        await _eventually(lambda: count() == 1)
        ws.transport.abort()  # drop the TCP connection, no close frame
        await _eventually(lambda: count() == 0)

    asyncio.run(scenario())

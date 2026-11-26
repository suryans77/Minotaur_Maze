"""Serve the maze viewer, with the level's start cells, on localhost.

Start cells are not stored in levels/maze.json: the game derives them from the
maze and config/game.yaml (FR-G-17 and the route-complexity rules). This
server asks the game's own code, ``app.maze.load_level``, for them and for
each one's easiest route to every exit, so the viewer shows exactly what the
validator checks. Run it with the game's environment:

    cd game
    uv run python ../frontend/maze-viewer/serve.py      # --port to change 8000

then open http://localhost:8000/frontend/maze-viewer/

It serves only these, read-only, bound to 127.0.0.1:

    /frontend/maze-viewer/<page, .css, .js>   the viewer
    /levels/maze.json                         the maze file, byte for byte
    /api/level                                derived start cells and their routes (JSON)

``/api/level`` is recomputed on every request, so edits to the maze or the
config show up on reload. If the level fails validation it answers 422 with
the violations, and the viewer draws the maze without start cells.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

VIEWER_DIR = Path(__file__).resolve().parent
REPO = VIEWER_DIR.parents[1]
sys.path.insert(0, str(REPO / "game"))

from app.maze import (  # noqa: E402  (needs the path above)
    DEFAULT_CONFIG_PATH,
    DEFAULT_MAZE_PATH,
    LevelValidationError,
    MazeFormatError,
    SettingsError,
    load_level,
)

VIEWER_PREFIX = "/frontend/maze-viewer/"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


def level_payload() -> tuple[HTTPStatus, dict]:
    """The derived start cells, or why they could not be derived."""
    try:
        level = load_level(DEFAULT_MAZE_PATH, DEFAULT_CONFIG_PATH)
    except LevelValidationError as exc:
        return HTTPStatus.UNPROCESSABLE_ENTITY, {
            "error": "the level fails validation",
            "violations": [f"[{v.code}] {v.message}" for v in exc.violations],
        }
    except (MazeFormatError, SettingsError, OSError) as exc:
        return HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc), "violations": []}
    maze = level.maze
    return HTTPStatus.OK, {
        "maze": DEFAULT_MAZE_PATH.relative_to(REPO).as_posix(),
        "config": DEFAULT_CONFIG_PATH.relative_to(REPO).as_posix(),
        "settings": dataclasses.asdict(level.settings),
        "width": maze.width,
        "height": maze.height,
        "eligible_start_cells": len(level.eligible_start_cells),
        "start_cells": [list(c) for c in level.start_cells],
        # Per start cell, in the same order: the easiest route to each exit
        # (other exits blocked): shortest distance, fewest turns, fewest junctions.
        "start_routes": [
            [
                {
                    "exit": e.id,
                    "moves": maze.exit_distances[e.id][c],
                    "turns": maze.route_turns[e.id][c],
                    "junctions": maze.route_decisions[e.id][c],
                }
                for e in maze.exits
            ]
            for c in level.start_cells
        ],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "MazeViewer"

    def do_GET(self) -> None:  # noqa: N802  (http.server's naming)
        path = urlsplit(self.path).path
        if path in ("/", "/frontend/maze-viewer"):
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", VIEWER_PREFIX)
            self.end_headers()
        elif path == "/api/level":
            status, payload = level_payload()
            self.reply(status, "application/json", json.dumps(payload).encode())
        elif path == "/levels/maze.json":
            self.reply(HTTPStatus.OK, "application/json", DEFAULT_MAZE_PATH.read_bytes())
        elif path.startswith(VIEWER_PREFIX):
            name = path[len(VIEWER_PREFIX) :] or "index.html"
            file = (VIEWER_DIR / name).resolve()
            if file.parent == VIEWER_DIR and file.suffix in CONTENT_TYPES and file.is_file():
                self.reply(HTTPStatus.OK, CONTENT_TYPES[file.suffix], file.read_bytes())
            else:
                self.reply(HTTPStatus.NOT_FOUND, "text/plain", b"not found")
        else:
            self.reply(HTTPStatus.NOT_FOUND, "text/plain", b"not found")

    def reply(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the maze viewer on 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Maze viewer: http://localhost:{args.port}{VIEWER_PREFIX}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

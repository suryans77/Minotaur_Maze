# game: Minotaur Maze game server

FastAPI service that will own every game rule and run the 10 Hz game loop
over WebSockets (SRS §3, §5). The server is authoritative. The browser sends
inputs only and never decides an outcome (SRS §2.4).

**Status: Phase 0 scaffold.** The app runs, answers health checks, and
accepts WebSocket connections, cleaning them up on disconnect. It also holds
the level loader and validator. There is no game loop, movement, Minotaur or
message protocol yet. Those arrive in Phases 1–2 of the Build Plan.

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs Python 3.11 (SRS §2.3) by
  itself if needed.

Dependencies are declared in `pyproject.toml` and pinned in `uv.lock`.
The service is self-contained, so it can be built and deployed on its own
(NFR-10).

## Run

```sh
cd game
uv sync                                    # create .venv with runtime + dev deps
uv run uvicorn app.main:app --reload       # http://127.0.0.1:8000
curl http://127.0.0.1:8000/health          # {"status":"ok","service":"game"}
```

## Test

```sh
cd game
uv run pytest                    # whole suite, about 10 s
uv run ruff check . && uv run ruff format --check .
```

## Endpoints

| Endpoint | Behaviour |
|---|---|
| `GET /health` | `200 {"status": "ok", "service": "game"}`. For Docker and Kubernetes probes (FR-D-04) |
| `WS /ws` | Accepts the connection and keeps it open until the client leaves. Clean closes and dropped connections are both released |

**`/ws` has no message protocol yet.** Anything a client sends is read and
discarded, and the server sends nothing. The gameplay messages (player
input in, game state out at 10 ticks/s, FR-G-12) are designed in Phase 2.
Until then, no client message can affect server state.

## The level and its settings

The level comes from two files, each the single source of truth for what
it holds:

- [`../levels/maze.json`](../levels/maze.json): static topology (grid and
  exit coordinates).
- [`../config/game.yaml`](../config/game.yaml), section `level`: the
  tunable settings `safe_zone_radius`, `min_start_distance`,
  `min_route_turns`, `min_route_decisions` and `start_cell_count`.

`app.maze.load_level()` reads both, derives the safe zones and the valid
start cells, and refuses the level unless every requirement holds. Nothing
derived is stored. Exits are terminal endpoints, and every start needs two
distinct routes (they may share cells) to each exit, and no straightforward
one: every route must make enough turns and pass enough junctions. The format,
coordinates, and every definition and check are documented in
[`../levels/README.md`](../levels/README.md).

```sh
uv run python -m app.maze                       # load, validate, print measured properties
uv run python -m app.maze --config my.yaml      # try other settings against the same maze
uv run python -m tools.generate_maze --check    # verify the maze file is reproducible
```

## Layout

```text
game/
├── app/
│   ├── main.py        # FastAPI app: /health, /ws
│   ├── maze.py        # maze + settings loading, derivation, validation (FR-G-01/02/03/05/17)
│   └── graph.py       # BFS, biconnected components, bridges, distinct routes
├── tools/
│   └── generate_maze.py   # deterministic generator for levels/maze.json
└── test/
    ├── test_app.py               # startup, health, WebSocket connect/disconnect
    ├── test_graph.py             # graph algorithms on known graphs
    ├── test_level.py             # the committed level meets every requirement
    ├── test_level_validation.py  # broken levels are rejected
    └── test_settings.py          # config/game.yaml drives the derived level
```

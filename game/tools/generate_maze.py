"""Deterministic generator for the one level, ``levels/maze.json``.

The committed JSON file is the source of truth; this script only documents how
it was made and lets anyone reproduce it byte for byte::

    cd game
    uv run python -m tools.generate_maze           # rewrite levels/maze.json
    uv run python -m tools.generate_maze --check   # fail if the file differs

Algorithm, for one seed:

1. Carve a perfect maze on a 17 x 17 room lattice (a 35 x 35-cell grid)
   with a seeded recursive
   backtracker (long winding corridors, few dead ends).
2. Braid it:
   a. remove every dead end by opening one of its walls, preferring a wall
      that leads to another dead end;
   b. while the walkable graph has an articulation point, open a wall
      between two rooms that share no biconnected component, which merges
      every block on the path between them (so no single cell is a
      bottleneck, SRS 1.3 "braid maze");
   c. open further random walls until the braid ratio reaches 15 %, the
      middle of the 10-20 % band in FR-G-01.
3. Place the three exits at fixed cells on the outer ring and run the full
   level validator from ``app.maze``, with the settings in config/game.yaml.
   That includes the route-complexity rules, so a seed passes only if at
   least ``start_cell_count`` cells have no straightforward way out.

Seeds are tried in order from ``BASE_SEED``; the first one whose level
passes every check is used, and recorded in the file. The file holds only
topology (grid and exits). Safe zones and start cells are derived on load.

``--check`` rebuilds from the seed recorded in the file, so it verifies
determinism independently of the current settings.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from app import graph as g
from app.maze import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_MAZE_PATH,
    EXIT,
    FLOOR,
    FORMAT_VERSION,
    WALL,
    Cell,
    LevelSettings,
    MazeFormatError,
    braid_ratio,
    derive_level,
    load_maze,
    load_settings,
    parse_maze,
    validate_level,
    walkable_graph,
)

BASE_SEED = 816
MAX_ATTEMPTS = 500
ROOMS_X = ROOMS_Y = 17  # 2 * 17 + 1 = 35 cells per side
TARGET_BRAID_RATIO = 0.15
# One exit in the middle of the north edge, one low on each of the west and
# east edges: a wide triangle, so no exit is favoured by the central starts.
EXIT_CELLS: tuple[Cell, ...] = ((17, 1), (1, 27), (33, 27))
LEVEL_NAME = "Labyrinth"
TOOL_PATH = "game/tools/generate_maze.py"


class Grid:
    """Mutable room-lattice grid used while generating."""

    def __init__(self, rooms_x: int, rooms_y: int):
        self.width, self.height = 2 * rooms_x + 1, 2 * rooms_y + 1
        self.rows = [[WALL] * self.width for _ in range(self.height)]
        self.rooms = [(2 * i + 1, 2 * j + 1) for j in range(rooms_y) for i in range(rooms_x)]
        for x, y in self.rooms:
            self.rows[y][x] = FLOOR
        self.slots = sorted(
            ((x, y) for y in range(1, self.height - 1) for x in range(1, self.width - 1) if (x + y) % 2),
            key=lambda c: (c[1], c[0]),
        )

    def is_open(self, cell: Cell) -> bool:
        return self.rows[cell[1]][cell[0]] != WALL

    def open(self, cell: Cell) -> None:
        self.rows[cell[1]][cell[0]] = FLOOR

    def slot_rooms(self, slot: Cell) -> tuple[Cell, Cell]:
        x, y = slot
        return ((x - 1, y), (x + 1, y)) if x % 2 == 0 else ((x, y - 1), (x, y + 1))

    def room_slots(self, room: Cell) -> list[Cell]:
        x, y = room
        cand = [(x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y)]
        return [s for s in cand if 0 < s[0] < self.width - 1 and 0 < s[1] < self.height - 1]

    def closed_slots(self) -> list[Cell]:
        return [s for s in self.slots if not self.is_open(s)]

    def strings(self) -> list[str]:
        return ["".join(row) for row in self.rows]

    def ratio(self) -> float:
        perfect_walls = len(self.slots) - (len(self.rooms) - 1)
        opened = sum(1 for s in self.slots if self.is_open(s))
        return (opened - (len(self.rooms) - 1)) / perfect_walls


def carve_perfect_maze(grid: Grid, rng: random.Random) -> None:
    start = rng.choice(grid.rooms)
    visited = {start}
    stack = [start]
    while stack:
        room = stack[-1]
        options = []
        for slot in grid.room_slots(room):
            a, b = grid.slot_rooms(slot)
            nxt = b if a == room else a
            if nxt not in visited:
                options.append((slot, nxt))
        if not options:
            stack.pop()
            continue
        slot, nxt = rng.choice(options)
        grid.open(slot)
        visited.add(nxt)
        stack.append(nxt)


def remove_dead_ends(grid: Grid, rng: random.Random) -> None:
    def degree(room: Cell) -> int:
        return sum(1 for s in grid.room_slots(room) if grid.is_open(s))

    order = list(grid.rooms)
    rng.shuffle(order)
    for room in order:
        if degree(room) != 1:
            continue
        options = []
        for slot in grid.room_slots(room):
            if grid.is_open(slot):
                continue
            a, b = grid.slot_rooms(slot)
            options.append((slot, b if a == room else a))
        preferred = [s for s, other in options if degree(other) == 1]
        grid.open(rng.choice(preferred or [s for s, _ in options]))


def remove_articulation_points(grid: Grid, rng: random.Random) -> None:
    while True:
        blocks = g.block_index(walkable_graph(grid.strings()))
        if len({i for ids in blocks.values() for i in ids}) <= 1:
            return
        candidates = [
            s
            for s in grid.closed_slots()
            if not (blocks[grid.slot_rooms(s)[0]] & blocks[grid.slot_rooms(s)[1]])
        ]
        grid.open(rng.choice(candidates))


def top_up(grid: Grid, rng: random.Random, target: float) -> None:
    closed = grid.closed_slots()
    rng.shuffle(closed)
    while grid.ratio() < target and closed:
        grid.open(closed.pop())


def build_level(seed: int) -> dict[str, Any]:
    """Generate the maze file contents for one seed. The result may still fail validation."""
    rng = random.Random(seed)
    grid = Grid(ROOMS_X, ROOMS_Y)
    carve_perfect_maze(grid, rng)
    remove_dead_ends(grid, rng)
    remove_articulation_points(grid, rng)
    top_up(grid, rng, TARGET_BRAID_RATIO)
    for x, y in EXIT_CELLS:
        grid.rows[y][x] = EXIT

    data: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "name": LEVEL_NAME,
        "coordinates": "cell = [x, y]; x = column from 0 at the west edge, "
        "y = row from 0 at the north edge; grid[y][x]",
        "legend": {WALL: "wall", FLOOR: "floor", EXIT: "exit (walkable)"},
        "generator": {"tool": TOOL_PATH, "seed": seed},
        "width": grid.width,
        "height": grid.height,
        "exits": [{"id": i, "cell": list(c)} for i, c in enumerate(EXIT_CELLS)],
        "grid": grid.strings(),
    }
    return data


def find_level(
    settings: LevelSettings, base_seed: int = BASE_SEED, attempts: int = MAX_ATTEMPTS
) -> dict[str, Any]:
    """The maze for the first seed, from ``base_seed`` on, whose level passes validation."""
    for seed in range(base_seed, base_seed + attempts):
        data = build_level(seed)
        if not validate_level(derive_level(parse_maze(data), settings)):
            return data
    raise RuntimeError(f"no valid level in seeds {base_seed}..{base_seed + attempts - 1}")


def to_json(data: dict[str, Any]) -> str:
    """Stable, diff-friendly JSON: one grid row and one exit per line."""

    def compact(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    def block(items: list[str]) -> str:
        return "[\n" + ",\n".join(f"    {item}" for item in items) + "\n  ]"

    parts = []
    for key, value in data.items():
        rendered = block([compact(v) for v in value]) if key in ("grid", "exits") else compact(value)
        parts.append(f"  {json.dumps(key)}: {rendered}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_MAZE_PATH)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--seed", type=int, help="build exactly this seed instead of searching")
    parser.add_argument(
        "--check", action="store_true", help="fail if the file differs from its recorded seed's output"
    )
    args = parser.parse_args(argv)

    if args.check:
        try:
            seed = load_maze(args.output).seed
        except (OSError, MazeFormatError) as exc:
            print(f"cannot read {args.output}: {exc}", file=sys.stderr)
            return 1
        if seed is None:
            print(f"{args.output} records no generator seed", file=sys.stderr)
            return 1
        if args.output.read_text(encoding="utf-8") != to_json(build_level(seed)):
            print(f"{args.output} differs from the output for seed {seed}; regenerate it", file=sys.stderr)
            return 1
        print(f"{args.output} matches seed {seed}")
        return 0

    settings = load_settings(args.config)
    data = build_level(args.seed) if args.seed is not None else find_level(settings)
    level = derive_level(parse_maze(data), settings)
    violations = validate_level(level)
    if violations:
        for v in violations:
            print(f"[{v.code}] {v.message}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(to_json(data), encoding="utf-8")
    print(
        f"wrote {args.output}: seed {data['generator']['seed']}, braid ratio "
        f"{braid_ratio(level.maze):.2%}, {len(level.start_cells)} start cells "
        f"chosen from {len(level.eligible_start_cells)} eligible"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

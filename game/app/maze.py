"""The level: maze file, level settings, derived properties and validation.

Two sources, one owner per fact:

* ``levels/maze.json``: the static topology, meaning the grid and the exit
  coordinates. Documented in ``levels/README.md``.
* ``config/game.yaml``, section ``level``: the tunable settings
  ``safe_zone_radius``, ``min_start_distance``, ``min_route_turns``,
  ``min_route_decisions`` and ``start_cell_count``.

Everything else (safe zones, eligible and chosen start cells) is derived from
those two on load and is never stored, so it cannot fall out of step with
either.

Conventions:

* ``grid[y][x]``. ``x`` is the column counted from 0 at the west edge, ``y`` the
  row counted from 0 at the north edge. Cells are ``[x, y]`` in JSON and
  ``(x, y)`` in code.
* ``#`` is a wall, ``.`` is floor, ``E`` is an exit (also walkable). Movement is
  one cell north, south, east or west, onto any walkable cell.
* The grid is a room lattice: rooms at (odd, odd) cells are always walkable,
  pillars at (even, even) cells and the outer border are always wall, and every
  other cell is a *wall slot* between two orthogonally adjacent rooms.

Requirement checks (SRS v2, with the team's endpoint rule for FR-G-02):

==========  ===============================================================
FR-G-01     grid at least 25 x 25 cells; braid ratio within 10-20 %
FR-G-02     at least 2 distinct routes from every start to every exit, with
            the other exits blocked (exits are terminal endpoints)
FR-G-03     exactly 3 exits
FR-G-05     safe zone of ``safe_zone_radius`` (SRS: 2) around every exit
FR-G-17     start cells at least ``min_start_distance`` (SRS: 12) moves, by
            shortest walkable path, from every exit
Team rule   every route from a start cell to every exit makes at least
            ``min_route_turns`` turns and passes at least
            ``min_route_decisions`` junctions; exactly ``start_cell_count``
            start cells, spread out across the maze
==========  ===============================================================

Run ``python -m app.maze`` from ``game/`` to load and validate the level and
print its measured properties.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

from app import graph as g

Cell = tuple[int, int]

FORMAT_VERSION = 2
MAZE_FIELDS = frozenset(
    {"format_version", "name", "coordinates", "legend", "generator", "width", "height", "exits", "grid"}
)
SETTINGS_SECTION = "level"
SETTINGS_FIELDS = frozenset(
    {"safe_zone_radius", "min_start_distance", "min_route_turns", "min_route_decisions", "start_cell_count"}
)
WALL, FLOOR, EXIT = "#", ".", "E"
GRID_CHARS = frozenset({WALL, FLOOR, EXIT})
DIRECTIONS: tuple[Cell, ...] = ((0, -1), (1, 0), (0, 1), (-1, 0))  # N, E, S, W

# Requirement values from SRS v2. A level that does not meet them is invalid.
MIN_GRID_SIDE = 25  # FR-G-01: "a grid of at least 25x25", counted in cells
BRAID_RATIO_MIN = 0.10  # FR-G-01: "10-20% of walls removed"
BRAID_RATIO_MAX = 0.20
EXIT_COUNT = 3  # FR-G-03
MIN_ROUTES = 2  # FR-G-02
# Floors for the tunable settings. Going below them is an SRS change, not a tuning.
SRS_SAFE_ZONE_RADIUS = 2  # FR-G-05: "a safe zone of 2 cells"
SRS_MIN_START_DISTANCE = 12  # FR-G-17: "at least 12 cells from every exit"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAZE_PATH = REPO_ROOT / "levels" / "maze.json"
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "game.yaml"


class MazeFormatError(ValueError):
    """The maze file is not well-formed (missing fields, wrong types, ragged grid)."""


class SettingsError(ValueError):
    """The ``level`` section of the game config is missing or malformed."""


class LevelValidationError(ValueError):
    """The level is well-formed but breaks one or more requirements."""

    def __init__(self, violations: list[Violation]):
        self.violations = violations
        lines = "\n".join(f"  [{v.code}] {v.message}" for v in violations)
        super().__init__(f"level violates {len(violations)} requirement(s):\n{lines}")


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


@dataclass(frozen=True)
class Exit:
    id: int
    cell: Cell


@dataclass(frozen=True)
class LevelSettings:
    safe_zone_radius: int
    min_start_distance: int
    min_route_turns: int
    min_route_decisions: int
    start_cell_count: int


@dataclass(frozen=True)
class Maze:
    """The static topology from ``levels/maze.json``."""

    name: str
    width: int
    height: int
    grid: tuple[str, ...]
    exits: tuple[Exit, ...]
    seed: int | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    # --- cell geometry -----------------------------------------------------

    def in_bounds(self, cell: Cell) -> bool:
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height

    def char(self, cell: Cell) -> str:
        x, y = cell
        return self.grid[y][x]

    def is_walkable(self, cell: Cell) -> bool:
        return self.in_bounds(cell) and self.char(cell) != WALL

    def is_border(self, cell: Cell) -> bool:
        x, y = cell
        return x in (0, self.width - 1) or y in (0, self.height - 1)

    @staticmethod
    def is_room(cell: Cell) -> bool:
        return cell[0] % 2 == 1 and cell[1] % 2 == 1

    @staticmethod
    def is_pillar(cell: Cell) -> bool:
        return cell[0] % 2 == 0 and cell[1] % 2 == 0

    def is_wall_slot(self, cell: Cell) -> bool:
        return (cell[0] + cell[1]) % 2 == 1 and not self.is_border(cell)

    def cells(self) -> list[Cell]:
        return [(x, y) for y in range(self.height) for x in range(self.width)]

    @property
    def rooms_x(self) -> int:
        return (self.width - 1) // 2

    @property
    def rooms_y(self) -> int:
        return (self.height - 1) // 2

    # --- derived graph data ------------------------------------------------

    @cached_property
    def walkable(self) -> frozenset[Cell]:
        return frozenset(c for c in self.cells() if self.is_walkable(c))

    @cached_property
    def graph(self) -> dict[Cell, list[Cell]]:
        """Walkable cells, each linked to its walkable N/E/S/W neighbours."""
        return walkable_graph(self.grid)

    @property
    def exit_cells(self) -> tuple[Cell, ...]:
        return tuple(e.cell for e in self.exits)

    @cached_property
    def exit_distances(self) -> dict[int, dict[Cell, int]]:
        """Per exit id: shortest walkable-path distance from that exit to each cell."""
        return {e.id: g.bfs_distances(self.graph, e.cell) for e in self.exits}

    def route_graph(self, exit_id: int) -> dict[Cell, list[Cell]]:
        """The graph routes to ``exit_id`` are counted in: the walkable graph
        with every *other* exit removed. Exits are terminal endpoints, so a
        route may never pass through one on the way to another."""
        others = [e.cell for e in self.exits if e.id != exit_id]
        return g.induced_subgraph(self.graph, others)

    @cached_property
    def junctions(self) -> frozenset[Cell]:
        """Decision points: walkable cells with three or more walkable neighbours,
        where a player arriving along one corridor has to choose between two others."""
        return frozenset(c for c, nbrs in self.graph.items() if len(nbrs) >= 3)

    @cached_property
    def route_turns(self) -> dict[int, dict[Cell, int]]:
        """Per exit id: the fewest turns any route from each cell to that exit
        makes, under the endpoint rule (other exits blocked)."""
        return {e.id: g.fewest_turns(self.route_graph(e.id), e.cell) for e in self.exits}

    @cached_property
    def route_decisions(self) -> dict[int, dict[Cell, int]]:
        """Per exit id: the fewest junctions any route from each cell to that
        exit passes through (not counting the start or the exit), under the
        endpoint rule."""
        return {e.id: g.fewest_marked(self.route_graph(e.id), e.cell, self.junctions) for e in self.exits}


@dataclass(frozen=True)
class Level:
    """A maze plus its settings, with everything derived from the two."""

    maze: Maze
    settings: LevelSettings
    safe_zones: Mapping[int, frozenset[Cell]]
    start_cells: tuple[Cell, ...]
    eligible_start_cells: tuple[Cell, ...] = ()

    @property
    def all_safe_cells(self) -> frozenset[Cell]:
        return frozenset().union(*self.safe_zones.values())

    def minotaur_graph(self) -> dict[Cell, list[Cell]]:
        """The cells the Minotaur may occupy: walkable cells outside every safe zone."""
        return g.induced_subgraph(self.maze.graph, self.all_safe_cells)


# --- loading -------------------------------------------------------------------


def walkable_graph(grid: list[str] | tuple[str, ...]) -> dict[Cell, list[Cell]]:
    rows = list(grid)
    height, width = len(rows), len(rows[0]) if rows else 0

    def walkable(x: int, y: int) -> bool:
        return 0 <= x < width and 0 <= y < height and rows[y][x] != WALL

    return {
        (x, y): [(x + dx, y + dy) for dx, dy in DIRECTIONS if walkable(x + dx, y + dy)]
        for y in range(height)
        for x in range(width)
        if walkable(x, y)
    }


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _cell(value: Any, where: str) -> Cell:
    if not isinstance(value, list) or len(value) != 2 or not all(_is_int(v) for v in value):
        raise MazeFormatError(f"{where}: expected a cell [x, y] of two integers, got {value!r}")
    return (value[0], value[1])


def _require(data: Mapping[str, Any], key: str, kind: type | tuple[type, ...]) -> Any:
    if key not in data:
        raise MazeFormatError(f"missing field {key!r}")
    value = data[key]
    if not isinstance(value, kind) or isinstance(value, bool):
        raise MazeFormatError(f"field {key!r} has the wrong type: {type(value).__name__}")
    return value


def parse_maze(data: Mapping[str, Any]) -> Maze:
    """Build a ``Maze`` from decoded JSON. Checks form only, not the SRS rules."""
    if not isinstance(data, Mapping):
        raise MazeFormatError("maze file must contain a JSON object")
    unknown = set(data) - MAZE_FIELDS
    if unknown:
        raise MazeFormatError(
            f"unknown fields {sorted(unknown)}; the maze file holds topology only. "
            f"Tunable settings belong in config/game.yaml, and safe zones and start "
            f"cells are derived"
        )
    version = _require(data, "format_version", int)
    if version != FORMAT_VERSION:
        raise MazeFormatError(f"unsupported format_version {version}, expected {FORMAT_VERSION}")

    width = _require(data, "width", int)
    height = _require(data, "height", int)
    grid = _require(data, "grid", list)
    if len(grid) != height:
        raise MazeFormatError(f"grid has {len(grid)} rows but height is {height}")
    for y, row in enumerate(grid):
        if not isinstance(row, str) or len(row) != width:
            raise MazeFormatError(f"grid row {y} must be a string of exactly {width} characters")
        bad = set(row) - GRID_CHARS
        if bad:
            raise MazeFormatError(f"grid row {y} has unknown characters {sorted(bad)}")

    exits = []
    for i, entry in enumerate(_require(data, "exits", list)):
        if not isinstance(entry, Mapping):
            raise MazeFormatError(f"exits[{i}] must be an object")
        exits.append(Exit(id=_require(entry, "id", int), cell=_cell(entry.get("cell"), f"exits[{i}].cell")))

    generator = data.get("generator")
    seed = generator.get("seed") if isinstance(generator, Mapping) else None
    return Maze(
        name=str(data.get("name", "")),
        width=width,
        height=height,
        grid=tuple(grid),
        exits=tuple(exits),
        seed=seed if _is_int(seed) else None,
        raw=data,
    )


def load_maze(path: Path | str = DEFAULT_MAZE_PATH) -> Maze:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MazeFormatError(f"{path}: invalid JSON: {exc}") from exc
    return parse_maze(data)


def parse_settings(config: Any) -> LevelSettings:
    """Read the ``level`` section of the decoded game config."""
    if not isinstance(config, Mapping) or not isinstance(config.get(SETTINGS_SECTION), Mapping):
        raise SettingsError(f"game config needs a {SETTINGS_SECTION!r} section")
    section = config[SETTINGS_SECTION]
    missing = SETTINGS_FIELDS - set(section)
    unknown = set(section) - SETTINGS_FIELDS
    if missing or unknown:
        raise SettingsError(
            f"{SETTINGS_SECTION!r} section: missing {sorted(missing)}, unknown {sorted(unknown)}"
        )
    for key in sorted(SETTINGS_FIELDS):
        if not _is_int(section[key]) or section[key] < 0:
            raise SettingsError(f"{SETTINGS_SECTION}.{key} must be a non-negative integer")
    return LevelSettings(**{key: section[key] for key in SETTINGS_FIELDS})


def load_settings(path: Path | str = DEFAULT_CONFIG_PATH) -> LevelSettings:
    try:
        config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SettingsError(f"{path}: invalid YAML: {exc}") from exc
    return parse_settings(config)


def load_level(
    maze_path: Path | str = DEFAULT_MAZE_PATH,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    *,
    validate: bool = True,
) -> Level:
    """Load the maze and the settings, derive the level, and by default refuse
    it unless every requirement holds."""
    level = derive_level(load_maze(maze_path), load_settings(config_path))
    if validate:
        violations = validate_level(level)
        if violations:
            raise LevelValidationError(violations)
    return level


# --- derived properties --------------------------------------------------------


def braid_ratio(maze: Maze) -> float:
    """Fraction of the walls of a perfect maze that this level has removed.

    On an ``Rx x Ry`` room lattice there are ``S = Rx*(Ry-1) + Ry*(Rx-1)`` wall
    slots. Any perfect maze (exactly one route between any two rooms) is a
    spanning tree of the ``R = Rx*Ry`` rooms, so it opens exactly ``R - 1``
    slots and keeps ``S - (R - 1)`` walls. With ``O`` slots open::

        braid ratio = (O - (R - 1)) / (S - (R - 1))

    It is computed from the grid alone and is only meaningful when the rooms
    are connected, which ``validate_level`` checks separately.
    """
    rooms = maze.rooms_x * maze.rooms_y
    slots = [c for c in maze.cells() if maze.is_wall_slot(c)]
    opened = sum(1 for c in slots if maze.is_walkable(c))
    perfect_walls = len(slots) - (rooms - 1)
    if perfect_walls <= 0:
        return 0.0
    return (opened - (rooms - 1)) / perfect_walls


def derive_safe_zones(maze: Maze, settings: LevelSettings) -> dict[int, frozenset[Cell]]:
    """Per exit: every walkable cell within ``safe_zone_radius`` steps of it,
    by shortest walkable path, including the exit cell itself."""
    return {e.id: frozenset(g.ball(maze.graph, e.cell, settings.safe_zone_radius)) for e in maze.exits}


def route_reach(maze: Maze, exit_id: int) -> tuple[frozenset[Cell], frozenset[Cell]]:
    """For one exit, under the endpoint rule: the cells that have at least one
    route to it, and the cells that have at least two distinct routes."""
    exit_cell = next(e.cell for e in maze.exits if e.id == exit_id)
    graph = maze.route_graph(exit_id)
    reach = frozenset(g.bfs_distances(graph, exit_cell)) - {exit_cell}
    return reach, frozenset(g.nodes_with_two_routes(graph, exit_cell))


def _row_major(cell: Cell) -> tuple[int, int]:
    return (cell[1], cell[0])


def route_complexity(maze: Maze, cell: Cell) -> tuple[int, int, int]:
    """How hard the easiest way out of ``cell`` is: over all three exits, the
    fewest turns, the fewest junctions and the shortest distance of any route.
    Cells that cannot reach an exit score -1."""
    return (
        min(maze.route_turns[e.id].get(cell, -1) for e in maze.exits),
        min(maze.route_decisions[e.id].get(cell, -1) for e in maze.exits),
        min(maze.exit_distances[e.id].get(cell, -1) for e in maze.exits),
    )


def derive_eligible_start_cells(
    maze: Maze, settings: LevelSettings, safe_zones: Mapping[int, frozenset[Cell]]
) -> tuple[Cell, ...]:
    """Every cell that may be a start cell, sorted by (y, x).

    An eligible cell is walkable, is not an exit and not in any safe zone, and
    for every exit:

    * is at least ``min_start_distance`` moves away by shortest walkable path;
    * has at least two distinct routes to it under the endpoint rule;
    * has no route to it with fewer than ``min_route_turns`` turns or fewer
      than ``min_route_decisions`` junctions, so no way out is straightforward.
    """
    excluded = set(maze.exit_cells).union(*safe_zones.values())
    two_routes = [route_reach(maze, e.id)[1] for e in maze.exits]
    candidates = [
        cell
        for cell in maze.walkable - excluded
        if all(maze.exit_distances[e.id].get(cell, -1) >= settings.min_start_distance for e in maze.exits)
        and all(cell in ok for ok in two_routes)
        and all(maze.route_turns[e.id].get(cell, -1) >= settings.min_route_turns for e in maze.exits)
        and all(maze.route_decisions[e.id].get(cell, -1) >= settings.min_route_decisions for e in maze.exits)
    ]
    return tuple(sorted(candidates, key=_row_major))


def select_start_cells(maze: Maze, eligible: Sequence[Cell], count: int) -> tuple[Cell, ...]:
    """Choose ``count`` of the eligible cells, spread across the maze, sorted by (y, x).

    Farthest-point selection by walking distance: first the cell whose
    easiest way out is hardest (``route_complexity``), then repeatedly the
    cell farthest from every cell chosen so far. Ties go to the more complex
    cell, then to the first in row-major order, so the choice is
    deterministic. If fewer than ``count`` cells are eligible, all of them
    are returned (and ``validate_level`` reports the shortfall).
    """
    order = sorted(eligible, key=_row_major)
    if count <= 0:
        return ()
    if len(order) <= count:
        return tuple(order)
    complexity = {c: route_complexity(maze, c) for c in order}
    chosen = [max(order, key=lambda c: complexity[c])]  # max() keeps the first of equals
    nearest = g.bfs_distances(maze.graph, chosen[0])
    gap = {c: nearest[c] for c in order}
    while len(chosen) < count:
        nxt = max((c for c in order if c not in chosen), key=lambda c: (gap[c], complexity[c]))
        chosen.append(nxt)
        dist = g.bfs_distances(maze.graph, nxt)
        for c in order:
            gap[c] = min(gap[c], dist[c])
    return tuple(sorted(chosen, key=_row_major))


def derive_start_cells(
    maze: Maze, settings: LevelSettings, safe_zones: Mapping[int, frozenset[Cell]]
) -> tuple[Cell, ...]:
    """The ``start_cell_count`` start cells the game picks from (FR-G-17)."""
    eligible = derive_eligible_start_cells(maze, settings, safe_zones)
    return select_start_cells(maze, eligible, settings.start_cell_count)


def derive_level(maze: Maze, settings: LevelSettings) -> Level:
    """The level for this maze and these settings. Never raises for a parsed
    maze; whether the result is acceptable is ``validate_level``'s job."""
    safe_zones = derive_safe_zones(maze, settings)
    eligible = derive_eligible_start_cells(maze, settings, safe_zones)
    return Level(
        maze=maze,
        settings=settings,
        safe_zones=safe_zones,
        start_cells=select_start_cells(maze, eligible, settings.start_cell_count),
        eligible_start_cells=eligible,
    )


# --- validation ------------------------------------------------------------------


def validate_level(level: Level) -> list[Violation]:
    """Check the level against every requirement. Returns all violations."""
    maze, settings = level.maze, level.settings
    out: list[Violation] = []

    def fail(code: str, message: str) -> None:
        out.append(Violation(code, message))

    # FR-G-01: size and room-lattice structure.
    if maze.width % 2 == 0 or maze.height % 2 == 0:
        fail("grid-structure", f"width and height must be odd, got {maze.width}x{maze.height}")
        return out
    if maze.width < MIN_GRID_SIDE or maze.height < MIN_GRID_SIDE:
        fail(
            "grid-size",
            f"grid is {maze.width}x{maze.height} cells, needs at least {MIN_GRID_SIDE}x{MIN_GRID_SIDE}",
        )
    for cell in maze.cells():
        if (maze.is_border(cell) or maze.is_pillar(cell)) and maze.char(cell) != WALL:
            fail("grid-structure", f"border and pillar cells must be wall, {list(cell)} is not")
        elif maze.is_room(cell) and not maze.is_walkable(cell):
            fail("grid-structure", f"room cell {list(cell)} must be walkable")
        elif maze.char(cell) == EXIT and not maze.is_room(cell):
            fail("grid-structure", f"exit marker at {list(cell)} is not on a room cell")
    if out:
        return out  # later checks assume the lattice structure

    # FR-G-03: exactly three exits, consistent between grid and list.
    grid_exits = {c for c in maze.cells() if maze.char(c) == EXIT}
    listed = [e.cell for e in maze.exits]
    if len(grid_exits) != EXIT_COUNT:
        fail("exit-count", f"grid has {len(grid_exits)} exit cells, needs exactly {EXIT_COUNT}")
    if len(maze.exits) != EXIT_COUNT:
        fail("exit-count", f"exits lists {len(maze.exits)} exits, needs exactly {EXIT_COUNT}")
    if sorted(e.id for e in maze.exits) != list(range(len(maze.exits))):
        fail("exit-ids", "exit ids must be 0, 1, 2, ... with no gaps or repeats")
    if len(set(listed)) != len(listed) or set(listed) != grid_exits:
        fail("exit-mismatch", f"exits list {sorted(listed)} does not match grid exits {sorted(grid_exits)}")
    for e in maze.exits:
        x, y = e.cell
        if not (x in (1, maze.width - 2) or y in (1, maze.height - 2)):
            fail("exit-position", f"exit {e.id} at {[x, y]} is not on the outer ring of rooms")
    if out:
        return out  # safe zones and starts are defined relative to the exits

    # FR-G-01: one connected maze, braided within the required band.
    if not g.is_connected(maze.graph):
        fail("disconnected", "not every walkable cell is reachable from every other")
        return out
    ratio = braid_ratio(maze)
    if not BRAID_RATIO_MIN <= ratio <= BRAID_RATIO_MAX:
        fail(
            "braid-ratio",
            f"braid ratio {ratio:.2%} is outside {BRAID_RATIO_MIN:.0%}-{BRAID_RATIO_MAX:.0%}",
        )

    # Tunable settings may not go below the SRS values.
    if settings.safe_zone_radius < SRS_SAFE_ZONE_RADIUS:
        fail(
            "settings",
            f"safe_zone_radius is {settings.safe_zone_radius}, "
            f"SRS FR-G-05 requires >= {SRS_SAFE_ZONE_RADIUS}",
        )
    if settings.min_start_distance < SRS_MIN_START_DISTANCE:
        fail(
            "settings",
            f"min_start_distance is {settings.min_start_distance}, "
            f"SRS FR-G-17 requires >= {SRS_MIN_START_DISTANCE}",
        )
    if settings.start_cell_count < 1:
        fail("settings", "start_cell_count must be at least 1")

    # FR-G-05: safe zones, and they must not break the maze for either side.
    expected_zones = derive_safe_zones(maze, settings)
    if set(level.safe_zones) != set(expected_zones):
        fail("safe-zone-mismatch", f"safe zones given for exits {sorted(level.safe_zones)}")
    for exit_id, expected in expected_zones.items():
        actual = level.safe_zones.get(exit_id, frozenset())
        if actual != expected:
            fail(
                "safe-zone-mismatch",
                f"safe zone of exit {exit_id} must be the {len(expected)} cells within "
                f"{settings.safe_zone_radius} steps; missing {sorted(expected - actual)}, "
                f"extra {sorted(actual - expected)}",
            )
    zones = sorted(level.safe_zones.items())
    for i, (a, zone_a) in enumerate(zones):
        for b, zone_b in zones[i + 1 :]:
            if zone_a & zone_b:
                fail("safe-zone-overlap", f"safe zones of exits {a} and {b} overlap")
    if not g.is_connected(level.minotaur_graph()):
        fail(
            "minotaur-region",
            "walkable cells outside the safe zones are not one connected region, "
            "so the Minotaur could not reach all of the maze",
        )

    # FR-G-17 and FR-G-02: start cells.
    if not level.start_cells:
        fail("start-empty", "no valid start cells")
    elif len(level.start_cells) != settings.start_cell_count:
        fail(
            "start-count",
            f"{len(level.start_cells)} start cells, start_cell_count requires exactly "
            f"{settings.start_cell_count}; too few cells meet the start rules",
        )
    if len(set(level.start_cells)) != len(level.start_cells):
        fail("start-duplicate", "start_cells contains duplicates")
    safe = level.all_safe_cells
    routes = {e.id: route_reach(maze, e.id) for e in maze.exits}
    for cell in level.start_cells:
        where = f"start cell {list(cell)}"
        if not maze.is_walkable(cell):
            fail("start-not-walkable", f"{where} is a wall or outside the grid")
            continue
        if cell in maze.exit_cells:
            fail("start-on-exit", f"{where} is an exit")
            continue
        if cell in safe:
            fail("start-in-safe-zone", f"{where} is inside a safe zone")
        for e in maze.exits:
            dist = maze.exit_distances[e.id][cell]
            if dist < settings.min_start_distance:
                fail(
                    "start-too-close",
                    f"{where} is {dist} steps from exit {e.id}, needs >= {settings.min_start_distance}",
                )
            reach, two = routes[e.id]
            if cell not in reach:
                fail("start-unreachable", f"{where} cannot reach exit {e.id} without crossing another exit")
            elif cell not in two:
                fail(
                    "start-routes",
                    f"{where} has only one route to exit {e.id} that avoids the other exits, "
                    f"needs at least {MIN_ROUTES} distinct routes",
                )
            if cell in reach:
                turns = maze.route_turns[e.id][cell]
                if turns < settings.min_route_turns:
                    fail(
                        "start-route-turns",
                        f"{where} has a route to exit {e.id} with only {turns} turns, "
                        f"every route needs >= {settings.min_route_turns}",
                    )
                decisions = maze.route_decisions[e.id][cell]
                if decisions < settings.min_route_decisions:
                    fail(
                        "start-route-decisions",
                        f"{where} has a route to exit {e.id} through only {decisions} junctions, "
                        f"every route needs >= {settings.min_route_decisions}",
                    )

    derived = set(derive_start_cells(maze, settings, level.safe_zones))
    stored = set(level.start_cells)
    if derived != stored:
        fail(
            "start-set-mismatch",
            f"start_cells must be the {len(derived)} cells chosen from the eligible ones: "
            f"{len(derived - stored)} missing, {len(stored - derived)} extra",
        )
    return out


def summary(level: Level) -> dict[str, Any]:
    """Measured properties of the level, for reports and the CLI."""
    maze = level.maze

    def lowest(table: dict[int, dict[Cell, int]]) -> int | None:
        values = [table[e.id][c] for e in maze.exits for c in level.start_cells if c in table[e.id]]
        return min(values) if values else None

    return {
        "name": maze.name,
        "grid": f"{maze.width}x{maze.height} cells",
        "room_lattice": f"{maze.rooms_x}x{maze.rooms_y} rooms",
        "walkable_cells": len(maze.walkable),
        "exits": {e.id: list(e.cell) for e in maze.exits},
        "braid_ratio": round(braid_ratio(maze), 4),
        "junctions": len(maze.junctions),
        "settings": {key: getattr(level.settings, key) for key in sorted(SETTINGS_FIELDS)},
        "safe_zone_sizes": {k: len(v) for k, v in sorted(level.safe_zones.items())},
        "eligible_start_cells": len(level.eligible_start_cells),
        "start_cells": [list(c) for c in level.start_cells],
        "over_all_starts_and_exits": {
            "min_distance": lowest(maze.exit_distances),
            "min_route_turns": lowest(maze.route_turns),
            "min_route_decisions": lowest(maze.route_decisions),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load and validate the level.")
    parser.add_argument("--maze", default=str(DEFAULT_MAZE_PATH), help="maze file (topology)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="game config (settings)")
    args = parser.parse_args(argv)
    try:
        level = load_level(args.maze, args.config)
    except (MazeFormatError, SettingsError, LevelValidationError, OSError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary(level), indent=2))
    print("OK: level satisfies FR-G-01, FR-G-02, FR-G-03, FR-G-05, FR-G-17 and the route-complexity rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())

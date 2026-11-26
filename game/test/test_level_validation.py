"""The validator rejects levels that break a requirement.

Every test starts from the committed level, breaks one thing, and checks that
the matching violation is reported. These are what stop a bad level edit in
the pipeline (SRS 6.2 step 5).
"""

from __future__ import annotations

import dataclasses
import json
import random

import pytest

from app import graph as g
from app.maze import (
    EXIT,
    FLOOR,
    WALL,
    LevelValidationError,
    MazeFormatError,
    braid_ratio,
    derive_level,
    load_level,
    main,
    parse_maze,
    validate_level,
)
from tools.generate_maze import EXIT_CELLS, ROOMS_X, ROOMS_Y, Grid, carve_perfect_maze


def violations(data: dict, settings) -> list:
    return validate_level(derive_level(parse_maze(data), settings))


def codes(data: dict, settings) -> set[str]:
    return {v.code for v in violations(data, settings)}


def level_codes(level) -> set[str]:
    return {v.code for v in validate_level(level)}


def messages(level, code: str) -> list[str]:
    return [v.message for v in validate_level(level) if v.code == code]


def set_cells(data: dict, changes: dict[tuple[int, int], str]) -> None:
    rows = [list(row) for row in data["grid"]]
    for (x, y), char in changes.items():
        rows[y][x] = char
    data["grid"] = ["".join(row) for row in rows]


def test_unmodified_copy_is_valid(maze_data, settings):
    assert codes(maze_data, settings) == set()


# --- FR-G-03: exits -----------------------------------------------------------------


def test_removing_an_exit_fails(maze_data, settings):
    removed = maze_data["exits"].pop()
    set_cells(maze_data, {tuple(removed["cell"]): FLOOR})
    assert "exit-count" in codes(maze_data, settings)


def test_exit_missing_from_the_exit_list_fails(maze_data, settings):
    maze_data["exits"].pop()
    assert {"exit-count", "exit-mismatch"} <= codes(maze_data, settings)


def test_exit_missing_from_the_grid_fails(maze_data, settings):
    set_cells(maze_data, {tuple(maze_data["exits"][0]["cell"]): FLOOR})
    assert {"exit-count", "exit-mismatch"} <= codes(maze_data, settings)


def test_a_fourth_exit_fails(maze_data, settings):
    set_cells(maze_data, {(1, 1): EXIT})
    maze_data["exits"].append({"id": 3, "cell": [1, 1]})
    assert "exit-count" in codes(maze_data, settings)


def test_exit_away_from_the_edge_fails(maze_data, settings):
    set_cells(maze_data, {tuple(maze_data["exits"][0]["cell"]): FLOOR, (13, 13): EXIT})
    maze_data["exits"][0]["cell"] = [13, 13]
    assert "exit-position" in codes(maze_data, settings)


# --- FR-G-02: routes, with exits as terminal endpoints -------------------------------


def _perfect_maze_data(seed: int = 3) -> dict:
    """A perfect maze (exactly one route between any two cells) the size of the
    level, with its three exits. Not a valid level, but a controlled one."""
    grid = Grid(ROOMS_X, ROOMS_Y)
    carve_perfect_maze(grid, random.Random(seed))
    for x, y in EXIT_CELLS:
        grid.rows[y][x] = EXIT
    return {
        "format_version": 2,
        "width": grid.width,
        "height": grid.height,
        "grid": grid.strings(),
        "exits": [{"id": i, "cell": list(c)} for i, c in enumerate(EXIT_CELLS)],
    }


def _far_cells(level):
    maze = level.maze
    return sorted(
        c
        for c in maze.walkable - set(maze.exit_cells) - level.all_safe_cells
        if all(maze.exit_distances[e.id][c] >= level.settings.min_start_distance for e in maze.exits)
    )


def test_start_with_only_one_route_to_an_exit_is_rejected(settings):
    level = derive_level(parse_maze(_perfect_maze_data()), settings)
    assert level.start_cells == ()  # in a perfect maze no cell qualifies
    # A far cell whose one path to each exit avoids the other exits, so every
    # exit is reachable and the only fault is the missing second route.
    reach = [g.bfs_distances(level.maze.route_graph(e.id), e.cell) for e in level.maze.exits]
    start = next(c for c in _far_cells(level) if all(c in r for r in reach))
    for e in level.maze.exits:
        assert len(g.two_distinct_routes(level.maze.route_graph(e.id), start, e.cell)) == 1
    tampered = dataclasses.replace(level, start_cells=(start,))
    found = messages(tampered, "start-routes")
    assert {m.rsplit("exit ", 1)[1].split(" ")[0] for m in found} == {"0", "1", "2"}
    assert all(m.startswith(f"start cell {list(start)} has only one route") for m in found)


def test_start_whose_second_route_passes_through_another_exit_is_rejected(settings):
    """Open one wall of a perfect maze so that exactly one loop exists, and it
    runs through another exit. Cells on that loop have two routes to exit 0 if
    exits were ordinary cells, but only one under the endpoint rule."""
    data = _perfect_maze_data()
    base = parse_maze(data)
    exit0, other_exits = base.exit_cells[0], set(base.exit_cells[1:])
    for slot in (c for c in base.cells() if base.is_wall_slot(c) and not base.is_walkable(c)):
        trial = json.loads(json.dumps(data))
        set_cells(trial, {slot: FLOOR})
        level = derive_level(parse_maze(trial), settings)
        maze = level.maze
        routes_graph = maze.route_graph(0)
        loop_cells = g.nodes_with_two_routes(maze.graph, exit0) - g.nodes_with_two_routes(routes_graph, exit0)
        still_reachable = g.bfs_distances(routes_graph, exit0)
        found = [c for c in _far_cells(level) if c in loop_cells and c in still_reachable]
        if found:
            start = found[0]
            break
    else:
        pytest.fail("no wall creates a loop through another exit")

    # Treating the other exits as ordinary cells, two routes exist, and one
    # of them crosses another exit.
    open_routes = g.two_distinct_routes(maze.graph, start, exit0)
    assert len(open_routes) == 2 and any(other_exits & set(r) for r in open_routes)
    # Under the endpoint rule only one remains, and it touches no other exit.
    blocked_routes = g.two_distinct_routes(maze.route_graph(0), start, exit0)
    assert len(blocked_routes) == 1 and not other_exits & set(blocked_routes[0])
    assert start not in level.start_cells
    tampered = dataclasses.replace(level, start_cells=(start,))
    assert any(
        m.endswith("exit 0 that avoids the other exits, needs at least 2 distinct routes")
        for m in messages(tampered, "start-routes")
    )


def test_single_entrance_exit_is_accepted_because_routes_may_share_cells(level, maze_data, settings):
    """Walling off one side of exit 0 leaves one way in. Every route to it now
    shares that last cell, which is allowed: the level stays valid."""
    exit0 = level.maze.exits[0].cell
    set_cells(maze_data, {level.maze.graph[exit0][0]: WALL})
    changed = derive_level(parse_maze(maze_data), settings)
    assert validate_level(changed) == []
    (entrance,) = changed.maze.graph[exit0]
    for start in changed.start_cells[:: max(1, len(changed.start_cells) // 50)]:
        routes = g.two_distinct_routes(changed.maze.route_graph(0), start, exit0)
        assert len(routes) == 2 and all(r[-2] == entrance for r in routes)


def test_cutting_an_exit_off_fails(level, maze_data, settings):
    exit0 = level.maze.exits[0].cell
    set_cells(maze_data, {n: WALL for n in level.maze.graph[exit0]})
    assert "disconnected" in codes(maze_data, settings)


# --- FR-G-17: invalid start cells --------------------------------------------------


def _cell_at_distance(level, exit_id: int, distance: int) -> tuple[int, int]:
    dist = level.maze.exit_distances[exit_id]
    return min(c for c, d in dist.items() if d == distance)


def _with_start(level, cell):
    return dataclasses.replace(level, start_cells=level.start_cells + (cell,))


def test_start_cell_too_close_to_an_exit_fails(level):
    close = _cell_at_distance(level, 0, 6)
    assert {"start-too-close", "start-set-mismatch"} <= level_codes(_with_start(level, close))


def test_start_cell_one_step_short_of_the_minimum_fails(level):
    close = _cell_at_distance(level, 0, level.settings.min_start_distance - 1)
    assert "start-too-close" in level_codes(_with_start(level, close))


@pytest.mark.parametrize(
    ("cell", "code"), [((0, 0), "start-not-walkable"), ((500, 500), "start-not-walkable")]
)
def test_start_cell_on_a_wall_or_outside_the_grid_fails(level, cell, code):
    assert code in level_codes(_with_start(level, cell))


def test_start_cell_in_a_safe_zone_fails(level):
    zone_cell = min(level.safe_zones[1] - {level.maze.exits[1].cell})
    assert "start-in-safe-zone" in level_codes(_with_start(level, zone_cell))


def test_start_cell_on_an_exit_fails(level):
    assert "start-on-exit" in level_codes(_with_start(level, level.maze.exits[2].cell))


def test_duplicate_start_cell_fails(level):
    assert "start-duplicate" in level_codes(_with_start(level, level.start_cells[0]))


def test_empty_start_set_fails(level):
    assert "start-empty" in level_codes(dataclasses.replace(level, start_cells=()))


def test_dropping_a_chosen_start_cell_fails(level):
    assert level_codes(dataclasses.replace(level, start_cells=level.start_cells[:-1])) == {
        "start-set-mismatch",
        "start-count",
    }


def test_swapping_a_chosen_start_for_another_eligible_cell_fails(level):
    """Any eligible cell would be a fair start, but the set is the one the
    selection rule picks, so the game and every report agree on it."""
    spare = next(c for c in level.eligible_start_cells if c not in level.start_cells)
    swapped = dataclasses.replace(level, start_cells=level.start_cells[:-1] + (spare,))
    assert level_codes(swapped) == {"start-set-mismatch"}


# --- route complexity: no straightforward way out ---------------------------------------


def _straightforward_cell(level, table: str, threshold: str):
    """A cell that meets the distance, safe-zone and two-route rules but has a
    route to some exit with fewer turns (or junctions) than the threshold."""
    maze, settings = level.maze, level.settings
    relaxed = derive_level(maze, dataclasses.replace(settings, min_route_turns=0, min_route_decisions=0))
    per_exit = getattr(maze, table)
    return min(
        c
        for c in relaxed.eligible_start_cells
        if min(per_exit[e.id][c] for e in maze.exits) < getattr(settings, threshold)
    )


def test_start_with_a_route_of_too_few_turns_fails(level):
    cell = _straightforward_cell(level, "route_turns", "min_route_turns")
    found = messages(_with_start(level, cell), "start-route-turns")
    assert found and all(m.startswith(f"start cell {list(cell)} has a route to exit") for m in found)


def test_start_with_a_route_through_too_few_junctions_fails(level):
    cell = _straightforward_cell(level, "route_decisions", "min_route_decisions")
    found = messages(_with_start(level, cell), "start-route-decisions")
    assert found and all(m.startswith(f"start cell {list(cell)} has a route to exit") for m in found)


def test_too_few_eligible_cells_for_the_start_count_fails(level):
    short = dataclasses.replace(level.settings, start_cell_count=len(level.eligible_start_cells) + 1)
    assert "start-count" in level_codes(derive_level(level.maze, short))


# --- FR-G-05: safe zones --------------------------------------------------------------


def test_safe_zone_missing_a_cell_fails(level):
    zones = dict(level.safe_zones)
    zones[0] = frozenset(sorted(zones[0])[1:])
    assert "safe-zone-mismatch" in level_codes(dataclasses.replace(level, safe_zones=zones))


def test_safe_zone_that_cuts_off_part_of_the_maze_from_the_minotaur_fails(level, maze_data, settings):
    """A room reachable only through a safe zone is a pocket the Minotaur can
    never reach, so the zone would change the game rather than just protect the exit."""
    maze, zone = level.maze, level.safe_zones[0]
    for room in sorted(c for c in maze.walkable if maze.is_room(c) and c not in zone):
        to_zone = [n for n in maze.graph[room] if any(m in zone for m in maze.graph[n])]
        others = [n for n in maze.graph[room] if n not in to_zone]
        if to_zone and others:
            break
    set_cells(maze_data, {n: WALL for n in others})
    assert g.is_connected(parse_maze(maze_data).graph), "player can still reach the pocket"
    assert "minotaur-region" in codes(maze_data, settings)


# --- FR-G-01: size, structure and braid ratio -------------------------------------------


def test_perfect_maze_without_braiding_fails(settings):
    data = _perfect_maze_data()
    assert braid_ratio(parse_maze(data)) == 0.0
    assert "braid-ratio" in codes(data, settings)


def test_over_braided_maze_fails(level, maze_data, settings):
    maze = level.maze
    closed = [c for c in maze.cells() if maze.is_wall_slot(c) and not maze.is_walkable(c)]
    set_cells(maze_data, {c: FLOOR for c in closed[: len(closed) // 2]})
    assert braid_ratio(parse_maze(maze_data)) > 0.20
    assert "braid-ratio" in codes(maze_data, settings)


def test_grid_smaller_than_25_by_25_fails(settings):
    grid = Grid(11, 11)  # 23 x 23 cells
    carve_perfect_maze(grid, random.Random(3))
    exits = [(11, 1), (1, 17), (21, 17)]
    for x, y in exits:
        grid.rows[y][x] = EXIT
    data = {
        "format_version": 2,
        "width": grid.width,
        "height": grid.height,
        "grid": grid.strings(),
        "exits": [{"id": i, "cell": list(c)} for i, c in enumerate(exits)],
    }
    assert "grid-size" in codes(data, settings)


@pytest.mark.parametrize(
    ("cell", "char"),
    [((0, 5), FLOOR), ((2, 2), FLOOR), ((3, 3), WALL)],
    ids=["open-border", "open-pillar", "walled-room"],
)
def test_broken_room_lattice_fails(maze_data, settings, cell, char):
    set_cells(maze_data, {cell: char})
    assert "grid-structure" in codes(maze_data, settings)


# --- file format and loading ------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("grid"),
        lambda d: d.__setitem__("format_version", 1),
        lambda d: d["grid"].__setitem__(3, d["grid"][3][:-1]),
        lambda d: d["grid"].__setitem__(3, "X" + d["grid"][3][1:]),
        lambda d: d["exits"][0].__setitem__("cell", "north"),
        lambda d: d.__setitem__("rules", {"safe_zone_radius": 2, "min_start_distance": 12}),
        lambda d: d.__setitem__("start_cells", [[25, 25]]),
        lambda d: d.__setitem__("safe_zones", []),
    ],
    ids=[
        "missing-grid",
        "old-version",
        "ragged-row",
        "unknown-char",
        "bad-exit-cell",
        "settings-in-maze-file",
        "stored-start-cells",
        "stored-safe-zones",
    ],
)
def test_malformed_maze_file_is_rejected(maze_data, mutate):
    mutate(maze_data)
    with pytest.raises(MazeFormatError):
        parse_maze(maze_data)


def test_load_level_refuses_an_invalid_level(maze_data, tmp_path):
    maze_data["exits"].pop()
    path = tmp_path / "maze.json"
    path.write_text(json.dumps(maze_data))
    with pytest.raises(LevelValidationError) as err:
        load_level(path)
    assert any(v.code == "exit-count" for v in err.value.violations)
    assert load_level(path, validate=False).maze.exits  # loads when asked not to validate


def test_cli_exit_status(maze_data, tmp_path, capsys):
    assert main([]) == 0
    maze_data["exits"].pop()
    path = tmp_path / "maze.json"
    path.write_text(json.dumps(maze_data))
    assert main(["--maze", str(path)]) == 1
    assert "exit-count" in capsys.readouterr().err

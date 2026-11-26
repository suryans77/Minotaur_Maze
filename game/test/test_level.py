"""The committed level (levels/maze.json + config/game.yaml) meets every requirement.

Each test checks one requirement independently of ``validate_level`` where it
can, so a bug in the validator cannot hide a bad level.
"""

from __future__ import annotations

import heapq
import random
from collections import deque

from app import graph as g
from app.maze import (
    BRAID_RATIO_MAX,
    BRAID_RATIO_MIN,
    DEFAULT_MAZE_PATH,
    EXIT,
    MAZE_FIELDS,
    MIN_GRID_SIDE,
    MIN_ROUTES,
    WALL,
    braid_ratio,
    derive_level,
    load_settings,
    parse_maze,
    validate_level,
)
from tools.generate_maze import Grid, build_level, carve_perfect_maze, to_json


def test_level_loads_and_passes_the_validator(level):
    assert validate_level(level) == []


def test_settings_come_from_the_game_config_only(level, maze_data):
    assert level.settings == load_settings()
    assert set(maze_data) <= MAZE_FIELDS  # no settings, zones or starts in the maze file


def test_fr_g_01_grid_is_at_least_25_by_25(level):
    maze = level.maze
    assert maze.width >= MIN_GRID_SIDE and maze.height >= MIN_GRID_SIDE
    assert (maze.width, maze.height) == (35, 35)
    assert (maze.rooms_x, maze.rooms_y) == (17, 17)
    assert all(len(row) == maze.width for row in maze.grid)


def test_fr_g_01_braid_ratio_is_within_10_to_20_percent(level):
    assert BRAID_RATIO_MIN <= braid_ratio(level.maze) <= BRAID_RATIO_MAX


def test_braid_ratio_definition_endpoints():
    """0 for a perfect maze, 1 when every wall slot is open."""
    grid = Grid(12, 12)
    carve_perfect_maze(grid, random.Random(1))
    assert braid_ratio(parse_maze(_bare(grid))) == 0.0
    for slot in grid.slots:
        grid.open(slot)
    assert braid_ratio(parse_maze(_bare(grid))) == 1.0


def test_level_is_a_braid_maze_without_dead_ends(level):
    maze = level.maze
    assert g.is_connected(maze.graph)
    rooms = [c for c in maze.walkable if maze.is_room(c)]
    assert all(len(maze.graph[c]) >= 2 for c in rooms)


def test_fr_g_03_exactly_three_exits_at_the_designed_cells(level):
    maze = level.maze
    assert {c for c in maze.cells() if maze.char(c) == EXIT} == set(maze.exit_cells)
    assert maze.exit_cells == ((17, 1), (1, 27), (33, 27))
    assert [e.id for e in maze.exits] == [0, 1, 2]


def test_fr_g_05_safe_zones_are_derived_from_the_configured_radius(level):
    radius = level.settings.safe_zone_radius
    for e in level.maze.exits:
        dist = g.bfs_distances(level.maze.graph, e.cell)  # independent BFS
        assert level.safe_zones[e.id] == {c for c, d in dist.items() if d <= radius}


def test_safe_zones_do_not_break_the_maze(level):
    maze = level.maze
    zones = list(level.safe_zones.values())
    assert sum(len(z) for z in zones) == len(level.all_safe_cells)  # pairwise disjoint
    # The Minotaur's region is one connected piece touching every zone, so it
    # can patrol between all three exits (FR-M-03).
    minotaur = level.minotaur_graph()
    assert g.is_connected(minotaur)
    for zone in zones:
        border = {n for c in zone for n in maze.graph[c] if n not in zone}
        assert border and border <= minotaur.keys()
    assert not set(level.start_cells) & level.all_safe_cells


def test_fr_g_17_start_cells_are_far_enough_from_every_exit(level):
    assert level.start_cells
    assert len(set(level.start_cells)) == len(level.start_cells)
    for e in level.maze.exits:
        dist = g.bfs_distances(level.maze.graph, e.cell)  # independent BFS
        assert min(dist[s] for s in level.start_cells) >= level.settings.min_start_distance


def test_distance_is_shortest_walkable_path_not_straight_line(level):
    """Documented choice: distance is counted in moves through walkable
    cells, so some start cells are closer than 12 as the crow flies."""
    assert any(
        abs(s[0] - e.cell[0]) + abs(s[1] - e.cell[1]) < level.settings.min_start_distance
        for s in level.start_cells
        for e in level.maze.exits
    )


def _segment_turns(maze, blocked, source, target):
    """Fewest turns from source to target, by a different method than the game's:
    breadth-first search over straight runs. Each step slides any distance in one
    direction, so the fewest runs minus one is the fewest turns."""
    runs = {source: 0}
    queue = deque([source])
    while queue:
        cell = queue.popleft()
        if cell == target:
            return runs[cell] - 1
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            x, y = cell
            while True:
                x, y = x + dx, y + dy
                nxt = (x, y)
                if not maze.in_bounds(nxt) or maze.char(nxt) == WALL or nxt in blocked:
                    break
                if nxt not in runs:
                    runs[nxt] = runs[cell] + 1
                    queue.append(nxt)
                if nxt == target:
                    break  # a route ends at its exit; it never slides through it
    return None


def _heap_junctions(maze, blocked, source, target):
    """Fewest junctions strictly between source and target, by Dijkstra with a
    heap, searching from the start side, with junctions counted from the grid."""

    def open_neighbours(cell):
        x, y = cell
        return [
            (x + dx, y + dy)
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0))
            if maze.in_bounds((x + dx, y + dy)) and maze.char((x + dx, y + dy)) != WALL
        ]

    def is_junction(cell):
        return len(open_neighbours(cell)) >= 3  # all walkable neighbours, exits included

    best = {source: 0}
    heap = [(0, source)]
    while heap:
        cost, cell = heapq.heappop(heap)
        if cell == target:
            return cost
        if cost > best[cell]:
            continue
        for nxt in open_neighbours(cell):
            if nxt in blocked:
                continue
            new = cost + (nxt != target and is_junction(nxt))
            if new < best.get(nxt, new + 1):
                best[nxt] = new
                heapq.heappush(heap, (new, nxt))
    return None


def test_eligible_start_set_is_exactly_the_cells_meeting_every_start_rule(level):
    """Exhaustive and constructive. For every walkable cell far enough from
    every exit, and for each exit with the other two blocked:

    * build two routes explicitly and check each one independently (FR-G-02);
    * recompute the fewest turns and the fewest junctions of any route with
      algorithms that share no code with the game's.

    A cell must be eligible exactly when it passes all of them for all three exits."""
    maze, settings = level.maze, level.settings
    candidates = [
        c
        for c in maze.walkable - set(maze.exit_cells) - level.all_safe_cells
        if all(maze.exit_distances[e.id][c] >= settings.min_start_distance for e in maze.exits)
    ]
    expected = set()
    shared = 0
    for cell in candidates:
        ok = True
        for e in maze.exits:
            others = set(maze.exit_cells) - {e.cell}
            routes = g.two_distinct_routes(maze.route_graph(e.id), cell, e.cell)
            for route in routes:
                # A real walk on the full maze, ending at the first arrival at
                # its exit, never touching another exit.
                assert g.is_route(maze.graph, route, cell, e.cell)
                assert route.count(e.cell) == 1 and not others & set(route)
            if len(routes) == MIN_ROUTES:
                assert routes[0] != routes[1]
                shared += bool(set(routes[0][1:-1]) & set(routes[1][1:-1]))
            turns = _segment_turns(maze, others, cell, e.cell)
            junctions = _heap_junctions(maze, others, cell, e.cell)
            assert turns == maze.route_turns[e.id].get(cell)  # two methods agree
            assert junctions == maze.route_decisions[e.id].get(cell)
            ok = (
                ok
                and len(routes) >= MIN_ROUTES
                and turns >= settings.min_route_turns
                and junctions >= settings.min_route_decisions
            )
        if ok:
            expected.add(cell)
    assert set(level.eligible_start_cells) == expected
    assert shared > 0  # routes sharing intermediate cells are counted as distinct


def test_no_start_has_a_straightforward_way_out(level):
    """For each of the 10 starts and each exit (the other two blocked), the
    independent searches confirm that even the easiest route is long, winding
    and full of decisions."""
    maze, settings = level.maze, level.settings
    for start in level.start_cells:
        for e in maze.exits:
            others = set(maze.exit_cells) - {e.cell}
            fewest = _segment_turns(maze, others, start, e.cell)
            assert fewest >= settings.min_route_turns
            assert _heap_junctions(maze, others, start, e.cell) >= settings.min_route_decisions
            assert maze.exit_distances[e.id][start] >= settings.min_start_distance


def test_exactly_the_configured_number_of_start_cells_are_chosen(level):
    assert len(level.start_cells) == level.settings.start_cell_count == 10
    assert set(level.start_cells) <= set(level.eligible_start_cells)
    assert list(level.start_cells) == sorted(level.start_cells, key=lambda c: (c[1], c[0]))
    assert derive_level(level.maze, level.settings).start_cells == level.start_cells  # deterministic


def test_start_cells_are_spread_out(level):
    """Farthest-point selection: the chosen cells are at least as far apart
    (walking) as any unchosen eligible cell is from its nearest chosen one."""
    maze = level.maze
    dist = {s: g.bfs_distances(maze.graph, s) for s in level.start_cells}
    closest_pair = min(dist[a][b] for a in level.start_cells for b in level.start_cells if a != b)
    unchosen = set(level.eligible_start_cells) - set(level.start_cells)
    farthest_left_out = max(min(dist[s][c] for s in level.start_cells) for c in unchosen)
    assert closest_pair >= farthest_left_out


def test_all_three_exits_are_reachable_from_every_start_as_endpoints(level):
    for e in level.maze.exits:
        reach = g.bfs_distances(level.maze.route_graph(e.id), e.cell)
        assert all(s in reach for s in level.start_cells)
        assert not set(level.maze.exit_cells) - {e.cell} & reach.keys()


def test_level_is_reproducible_from_its_seed(level):
    """The committed file is exactly what the generator produces for its seed."""
    assert level.maze.seed == 818
    assert to_json(build_level(level.maze.seed)) == DEFAULT_MAZE_PATH.read_text(encoding="utf-8")


def _bare(grid: Grid) -> dict:
    """Minimal maze data around a generator grid (no exits needed)."""
    return {
        "format_version": 2,
        "width": grid.width,
        "height": grid.height,
        "grid": grid.strings(),
        "exits": [],
    }

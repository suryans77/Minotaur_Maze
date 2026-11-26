"""Unit tests for the generic graph algorithms, on graphs whose answers are known."""

from __future__ import annotations

import itertools
import random

import pytest

from app import graph as g


def undirected(edges, nodes=()):
    adj = {n: [] for n in nodes}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    return {n: sorted(v) for n, v in adj.items()}


def cycle(n):
    return undirected([(i, (i + 1) % n) for i in range(n)])


def path(n):
    return undirected([(i, i + 1) for i in range(n - 1)])


def all_routes(graph, source, target):
    """Brute force: every simple path from source that stops at target."""
    found = []

    def extend(route):
        if route[-1] == target:
            found.append(list(route))
            return
        for nbr in graph[route[-1]]:
            if nbr not in route:
                extend(route + [nbr])

    extend([source])
    return found


# Two 4-cycles sharing node 0: a "figure eight" whose only cut vertex is 0.
FIGURE_EIGHT = undirected([(0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (4, 5), (5, 6), (6, 0)])
# s - a, then a diamond a-b-d / a-c-d, then d - t. Two routes, sharing a and d.
SHARED = undirected([("s", "a"), ("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"), ("d", "t")])


def test_bfs_distances_follow_edges_not_labels():
    assert g.bfs_distances(cycle(6), 0) == {0: 0, 1: 1, 5: 1, 2: 2, 4: 2, 3: 3}
    assert g.bfs_distances(cycle(6), 99) == {}


def test_ball_includes_centre_and_radius():
    assert g.ball(path(5), 2, 1) == {1, 2, 3}


def test_is_connected():
    assert g.is_connected(cycle(5))
    assert not g.is_connected(undirected([(0, 1), (2, 3)]))
    assert not g.is_connected({})


def test_biconnected_components_and_articulation_points():
    assert g.biconnected_components(cycle(7)) == [frozenset(range(7))]
    assert sorted(sorted(b) for b in g.biconnected_components(FIGURE_EIGHT)) == [[0, 1, 2, 3], [0, 4, 5, 6]]
    assert g.articulation_points(FIGURE_EIGHT) == {0}
    assert frozenset([9]) in g.biconnected_components(undirected([(0, 1)], nodes=[9]))


def test_bridges():
    assert g.bridges(cycle(5)) == set()
    assert g.bridges(path(4)) == {frozenset({0, 1}), frozenset({1, 2}), frozenset({2, 3})}
    assert g.bridges(SHARED) == {frozenset({"s", "a"}), frozenset({"d", "t"})}


def test_shortest_route_and_edge_avoidance():
    assert g.shortest_route(cycle(6), 0, 2) == [0, 1, 2]
    assert g.shortest_route(cycle(6), 0, 2, avoid_edge=frozenset({0, 1})) == [0, 5, 4, 3, 2]
    assert g.shortest_route(path(3), 0, 2, avoid_edge=frozenset({1, 2})) is None


# --- the four route semantics the level depends on --------------------------------


def test_two_routes_sharing_intermediate_cells_are_accepted():
    routes = g.two_distinct_routes(SHARED, "s", "t")
    assert len(routes) == 2 and routes[0] != routes[1]
    assert all(g.is_route(SHARED, r, "s", "t") for r in routes)
    assert {"a", "d"} <= set(routes[0][1:-1]) & set(routes[1][1:-1])  # shared cells
    assert "s" in g.nodes_with_two_routes(SHARED, "t")
    # A vertex-disjoint requirement would reject this: "a" is a cut vertex.
    assert "a" in g.articulation_points(SHARED)


def test_route_through_a_blocked_node_does_not_count():
    # Two routes from s to t, but one of them passes through x (another exit).
    graph = undirected([("s", "a"), ("a", "t"), ("s", "x"), ("x", "t")])
    assert len(g.two_distinct_routes(graph, "s", "t")) == 2
    blocked = g.induced_subgraph(graph, ["x"])
    routes = g.two_distinct_routes(blocked, "s", "t")
    assert routes == [["s", "a", "t"]]
    assert "s" not in g.nodes_with_two_routes(blocked, "t")


def test_single_route_is_rejected():
    tree = undirected([(0, 1), (1, 2), (2, 3), (1, 4), (4, 5)])
    assert g.two_distinct_routes(tree, 0, 3) == [[0, 1, 2, 3]]
    assert g.nodes_with_two_routes(tree, 3) == set()


def test_route_ends_at_the_first_arrival_at_the_target():
    # Going 0-1-2-3 and on around the cycle back to 2 would revisit 2;
    # a route stops the moment it reaches the target.
    for route in all_routes(cycle(6), 0, 2):
        assert route.count(2) == 1 and route[-1] == 2
    assert sorted(map(tuple, g.two_distinct_routes(cycle(6), 0, 2))) == [(0, 1, 2), (0, 5, 4, 3, 2)]


def test_unreachable_target_has_no_routes():
    graph = undirected([(0, 1), (2, 3)])
    assert g.two_distinct_routes(graph, 0, 3) == []
    assert g.nodes_with_two_routes(graph, 3) == set()


def test_route_checker_rejects_bad_routes():
    graph = cycle(6)
    assert g.is_route(graph, [0, 1, 2, 3], 0, 3)
    assert not g.is_route(graph, [0, 2, 3], 0, 3)  # 0-2 is not an edge
    assert not g.is_route(graph, [1, 2, 3], 0, 3)  # wrong start
    assert not g.is_route(graph, [0, 1, 0, 5, 4, 3], 0, 3)  # not simple


@pytest.mark.parametrize("seed", range(30))
def test_route_counting_agrees_with_brute_force(seed):
    """On random graphs, both fast methods agree with enumerating every
    simple path: no length cutoff, no false accepts, no false rejects."""
    rng = random.Random(seed)
    nodes = list(range(9))
    graph = undirected([e for e in itertools.combinations(nodes, 2) if rng.random() < 0.3], nodes=nodes)
    for target in nodes:
        multi = g.nodes_with_two_routes(graph, target)
        for source in nodes:
            if source == target:
                continue
            every = all_routes(graph, source, target)
            built = g.two_distinct_routes(graph, source, target)
            assert len(built) == min(len(every), 2), (seed, source, target)
            assert all(r in every for r in built)
            assert (source in multi) == (len(every) >= 2), (seed, source, target)


# --- route complexity: fewest turns, fewest marked nodes ------------------------------


def grid_graph(width, height, rng, keep=0.75):
    """A random subgraph of the width x height grid: nodes are (x, y), each
    grid edge kept with probability ``keep``."""
    cells = [(x, y) for y in range(height) for x in range(width)]
    edges = [
        (a, b)
        for a in cells
        for b in ((a[0] + 1, a[1]), (a[0], a[1] + 1))
        if b[0] < width and b[1] < height and rng.random() < keep
    ]
    return undirected(edges, nodes=cells)


def test_turns_counts_direction_changes():
    assert g.turns([(0, 0), (1, 0), (2, 0)]) == 0
    assert g.turns([(0, 0), (1, 0), (1, 1), (2, 1)]) == 2
    assert g.turns([(0, 0), (0, 1)]) == 0


def test_fewest_turns_prefers_a_longer_straighter_route():
    # From (0,0) to (2,2): the staircase is shortest (4 moves, 3 turns); the
    # route around the edge is just as short with 1 turn.
    graph = undirected(
        [
            ((0, 0), (1, 0)),
            ((1, 0), (2, 0)),
            ((2, 0), (2, 1)),
            ((2, 1), (2, 2)),
            ((1, 0), (1, 1)),
            ((1, 1), (2, 1)),
            ((1, 1), (1, 2)),
            ((1, 2), (2, 2)),
        ]
    )
    assert g.fewest_turns(graph, (0, 0))[(2, 2)] == 1
    assert g.fewest_turns(g.induced_subgraph(graph, [(2, 0)]), (0, 0))[(2, 2)] == 2


def test_fewest_marked_skips_marked_nodes_when_it_can():
    graph = undirected([("s", "a"), ("a", "t"), ("s", "b"), ("b", "c"), ("c", "t")])
    assert g.fewest_marked(graph, "s", {"a"})["t"] == 0  # around through b, c
    assert g.fewest_marked(graph, "s", {"a", "b"})["t"] == 1
    assert g.fewest_marked(graph, "s", {"s", "t"})["t"] == 0  # the two ends never count
    assert g.fewest_marked(graph, "x", {"a"}) == {}


@pytest.mark.parametrize("seed", range(25))
def test_complexity_measures_agree_with_brute_force(seed):
    """Every simple path is enumerated on a small random grid graph: the
    fewest turns and fewest marked nodes over all of them match the fast
    searches, which minimise over walks. No path at all: absent from both."""
    rng = random.Random(seed)
    graph = grid_graph(4, 3, rng)
    marked = {c for c in graph if rng.random() < 0.4}
    for source in graph:
        fast_turns = g.fewest_turns(graph, source)
        fast_marked = g.fewest_marked(graph, source, marked)
        assert set(fast_turns) == set(fast_marked) == set(g.bfs_distances(graph, source))
        for target in graph:
            if target == source:
                continue
            every = all_routes(graph, source, target)
            if not every:
                assert target not in fast_turns
                continue
            assert fast_turns[target] == min(g.turns(r) for r in every), (seed, source, target)
            assert fast_marked[target] == min(sum(c in marked for c in r[1:-1]) for r in every), (
                seed,
                source,
                target,
            )

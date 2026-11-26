"""Graph algorithms used to validate the level (SRS FR-G-01, FR-G-02, FR-G-05, FR-G-17),
plus the two route-complexity measures used to choose start cells.

Graphs are undirected and simple, given as a mapping ``node -> sequence of
neighbours``. Adjacency must be symmetric. Nodes must be hashable and
orderable (maze cells are ``(x, y)`` tuples) so that iteration order, and
therefore every result, is deterministic.

Nothing here knows about mazes; the functions are tested on small hand-built
graphs in ``test/test_graph.py``.

Routes
------
A *route* from ``s`` to ``t`` is a simple path: a sequence of distinct nodes,
each adjacent to the next, starting at ``s`` and ending at ``t``. Because it is
simple, a route reaches ``t`` exactly once, at its end. Two routes are
*distinct* when their node sequences differ; they may share any number of
nodes. Callers that must keep routes away from some nodes (the other exits)
remove those nodes from the graph first.

The key fact used below: let ``P`` be any route from ``s`` to ``t``. A second,
distinct route exists if and only if some edge of ``P`` is not a bridge.

* If edge ``e`` of ``P`` is not a bridge, its endpoints stay connected without
  it, so ``s`` and ``t`` do too; any route in the graph minus ``e`` differs
  from ``P``, which uses ``e``.
* If every edge of ``P`` is a bridge, each one separates ``s`` from ``t``, so
  every route crosses each of them exactly once, in order, with nothing in
  between: every route equals ``P``.

There is no length cutoff anywhere: each search explores the whole component.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Collection, Hashable, Mapping, Sequence
from typing import TypeVar

N = TypeVar("N", bound=Hashable)
Graph = Mapping[N, Sequence[N]]


def induced_subgraph(graph: Graph[N], removed: Collection[N]) -> dict[N, list[N]]:
    """Return ``graph`` with the ``removed`` nodes and their edges deleted."""
    removed = set(removed)
    return {
        node: [nbr for nbr in nbrs if nbr not in removed]
        for node, nbrs in graph.items()
        if node not in removed
    }


def bfs_distances(graph: Graph[N], source: N) -> dict[N, int]:
    """Shortest-path distance, in edges, from ``source`` to every reachable node."""
    if source not in graph:
        return {}
    dist = {source: 0}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for nbr in graph[node]:
            if nbr not in dist:
                dist[nbr] = dist[node] + 1
                queue.append(nbr)
    return dist


def ball(graph: Graph[N], centre: N, radius: int) -> set[N]:
    """All nodes whose shortest-path distance from ``centre`` is at most ``radius``."""
    return {node for node, d in bfs_distances(graph, centre).items() if d <= radius}


def is_connected(graph: Graph[N]) -> bool:
    """True if every node is reachable from every other. An empty graph is not connected."""
    if not graph:
        return False
    first = min(graph)
    return len(bfs_distances(graph, first)) == len(graph)


def biconnected_components(graph: Graph[N]) -> list[frozenset[N]]:
    """Vertex sets of the biconnected components (blocks) of ``graph``.

    Iterative Hopcroft-Tarjan, O(V + E). An articulation point belongs to
    every block it joins; a bridge is a block of two nodes; an isolated node is
    a block of one.
    """
    disc: dict[N, int] = {}
    low: dict[N, int] = {}
    blocks: list[frozenset[N]] = []
    counter = 0

    for root in sorted(graph):
        if root in disc:
            continue
        disc[root] = low[root] = counter
        counter += 1
        if not graph[root]:
            blocks.append(frozenset([root]))
            continue

        node_stack: list[N] = [root]
        # Each frame: (node, parent, iterator over the node's neighbours).
        frames = [(root, None, iter(graph[root]))]
        while frames:
            node, parent, nbrs = frames[-1]
            descended = False
            for nbr in nbrs:
                if nbr not in disc:
                    disc[nbr] = low[nbr] = counter
                    counter += 1
                    node_stack.append(nbr)
                    frames.append((nbr, node, iter(graph[nbr])))
                    descended = True
                    break
                if nbr != parent:
                    low[node] = min(low[node], disc[nbr])
            if descended:
                continue

            frames.pop()
            if not frames:
                continue
            up = frames[-1][0]
            low[up] = min(low[up], low[node])
            if low[node] >= disc[up]:
                # ``up`` separates the subtree rooted at ``node``: pop one block.
                block = [up]
                while True:
                    popped = node_stack.pop()
                    block.append(popped)
                    if popped == node:
                        break
                blocks.append(frozenset(block))
    return blocks


def articulation_points(graph: Graph[N]) -> set[N]:
    """Nodes whose removal increases the number of connected components."""
    seen: set[N] = set()
    cut: set[N] = set()
    for block in biconnected_components(graph):
        cut |= seen & block
        seen |= block
    return cut


def block_index(graph: Graph[N]) -> dict[N, frozenset[int]]:
    """Map each node to the ids of the blocks that contain it."""
    index: dict[N, set[int]] = {node: set() for node in graph}
    for i, block in enumerate(biconnected_components(graph)):
        for node in block:
            index[node].add(i)
    return {node: frozenset(ids) for node, ids in index.items()}


def bridges(graph: Graph[N]) -> set[frozenset[N]]:
    """Edges whose removal disconnects their endpoints, as ``{u, v}`` sets.

    In a simple graph these are exactly the biconnected components of two nodes.
    """
    return {block for block in biconnected_components(graph) if len(block) == 2}


def shortest_route(
    graph: Graph[N], source: N, target: N, avoid_edge: frozenset[N] | None = None
) -> list[N] | None:
    """A shortest route from ``source`` to ``target``, optionally never using
    the edge ``avoid_edge``, or ``None`` if there is none."""
    if source not in graph or target not in graph:
        return None
    parent: dict[N, N | None] = {source: None}
    queue = deque([source])
    while queue and target not in parent:
        node = queue.popleft()
        for nbr in graph[node]:
            if nbr in parent or (avoid_edge is not None and frozenset((node, nbr)) == avoid_edge):
                continue
            parent[nbr] = node
            queue.append(nbr)
    if target not in parent:
        return None
    route = [target]
    while (prev := parent[route[-1]]) is not None:
        route.append(prev)
    return route[::-1]


def two_distinct_routes(graph: Graph[N], source: N, target: N) -> list[list[N]]:
    """Up to two distinct routes from ``source`` to ``target``, constructed explicitly.

    Returns ``[]`` if ``target`` is unreachable, one route if it is the only
    one, otherwise two. Finds a shortest route ``P``, then for each edge of
    ``P`` in turn looks for a route that avoids that edge; by the fact in the
    module docstring, one exists for some edge exactly when ``P`` is not the
    only route.
    """
    if source == target:
        raise ValueError("source and target must differ")
    first = shortest_route(graph, source, target)
    if first is None:
        return []
    for u, v in zip(first, first[1:], strict=False):
        second = shortest_route(graph, source, target, avoid_edge=frozenset((u, v)))
        if second is not None:
            return [first, second]
    return [first]


def nodes_with_two_routes(graph: Graph[N], target: N) -> set[N]:
    """Every node with at least two distinct routes to ``target``. O(V + E).

    Takes one route per node from a breadth-first tree rooted at ``target``
    and keeps the node when that route has a non-bridge edge.
    """
    if target not in graph:
        return set()
    bridge_set = bridges(graph)
    has_choice: dict[N, bool] = {target: False}
    queue = deque([target])
    while queue:
        node = queue.popleft()
        for nbr in graph[node]:
            if nbr not in has_choice:
                has_choice[nbr] = has_choice[node] or frozenset((node, nbr)) not in bridge_set
                queue.append(nbr)
    return {node for node, ok in has_choice.items() if ok}


def is_route(graph: Graph[N], route: Sequence[N], source: N, target: N) -> bool:
    """Independently check that ``route`` is a simple path from ``source`` to
    ``target`` along edges of ``graph``."""
    return (
        len(route) >= 2
        and route[0] == source
        and route[-1] == target
        and len(set(route)) == len(route)
        and all(b in graph.get(a, ()) for a, b in zip(route, route[1:], strict=False))
    )


# --- route complexity ---------------------------------------------------------------
#
# Both measures below are minimums over *every* route, not properties of one
# chosen route: "at least k" means no route at all gets away with fewer. Each
# is a 0-1 breadth-first search, so it is exact and has no length cutoff.
#
# The searches minimise over walks, which may revisit nodes. That gives the
# same minimum as over routes (simple paths): cutting a loop out of a walk
# never adds a marked node, and never adds a turn, because a loop that leaves
# a cell and comes back to it must turn at least once. The brute-force tests
# in test/test_graph.py check this on random graphs.


def turns(route: Sequence[tuple[int, int]]) -> int:
    """Number of direction changes along a route of grid cells ``(x, y)``."""
    steps = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(route, route[1:], strict=False)]
    return sum(1 for a, b in zip(steps, steps[1:], strict=False) if a != b)


def fewest_turns(graph: Graph[tuple[int, int]], source: tuple[int, int]) -> dict[tuple[int, int], int]:
    """For every node reachable from ``source``: the fewest direction changes
    on any route between the two. Nodes must be grid cells ``(x, y)``; the
    first step from ``source`` costs nothing. The count is symmetric, so this
    is also the fewest turns on any route *to* ``source``."""
    if source not in graph:
        return {}
    best_state: dict[tuple[tuple[int, int], tuple[int, int] | None], int] = {(source, None): 0}
    best: dict[tuple[int, int], int] = {}
    queue = deque([(0, source, None)])
    while queue:
        cost, node, heading = queue.popleft()
        if cost > best_state[(node, heading)]:
            continue  # a cheaper copy of this state was already expanded
        best[node] = min(best.get(node, cost), cost)
        for nbr in graph[node]:
            step = (nbr[0] - node[0], nbr[1] - node[1])
            new = cost + (heading is not None and step != heading)
            if new < best_state.get((nbr, step), new + 1):
                best_state[(nbr, step)] = new
                if new == cost:
                    queue.appendleft((new, nbr, step))
                else:
                    queue.append((new, nbr, step))
    return best


def fewest_marked(graph: Graph[N], source: N, marked: Collection[N]) -> dict[N, int]:
    """For every node reachable from ``source``: the fewest ``marked`` nodes
    on any route between the two, counting neither ``source`` nor the node
    itself (only the nodes passed through on the way)."""
    if source not in graph:
        return {}
    marked = set(marked)
    entered = {source: 0}  # marked nodes entered after leaving source, endpoint included
    done: set[N] = set()
    queue = deque([(0, source)])
    while queue:
        cost, node = queue.popleft()
        if node in done:
            continue
        done.add(node)
        for nbr in graph[node]:
            new = cost + (nbr in marked)
            if new < entered.get(nbr, new + 1):
                entered[nbr] = new
                if new == cost:
                    queue.appendleft((new, nbr))
                else:
                    queue.append((new, nbr))
    return {node: k - (node in marked and node != source) for node, k in entered.items()}

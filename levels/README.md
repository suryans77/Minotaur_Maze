# The level: `levels/maze.json` + `config/game.yaml`

The game has one fixed level (SRS FR-G-01). It is defined by two files,
each the only source of truth for what it holds:

| File | Holds | Changes when |
|---|---|---|
| [`levels/maze.json`](maze.json) | Static topology: the grid and the three exit coordinates | The maze itself is redesigned |
| [`config/game.yaml`](../config/game.yaml), section `level` | Tunable settings: `safe_zone_radius`, `min_start_distance`, `min_route_turns`, `min_route_decisions`, `start_cell_count` | Balance is tuned (SRS §3.2) |

**Safe zones** and **start cells** appear in neither file. They are
derived from the two every time the level is loaded, so they can never fall
out of step with the maze or with the settings. The maze loader rejects a
maze file that tries to carry settings, safe zones or start cells.

Current level, with the committed settings (safe-zone radius 2; every route
from a start at least 20 moves, 10 turns and 5 junctions; 10 start cells):

| | |
|---|---|
| Grid | 35 × 35 cells, a 17 × 17 room lattice |
| Exits | 3, at `[17, 1]` (north), `[1, 27]` (west), `[33, 27]` (east) |
| Braid ratio | 15.23 % (39 of 256 walls removed) |
| Safe zones | 5, 7 and 5 cells |
| Junctions | 71 of 616 walkable cells |
| Eligible start cells | 37 |
| Start cells | 10, labelled A–J in the viewer |
| Easiest way out of any start | at least 31 moves, 10 turns and 5 junctions |
| Generator seed | 818 |

Validate it from `game/`:

```sh
uv run python -m app.maze                      # prints the measured properties; exit status 0/1
uv run python -m app.maze --config other.yaml  # the same maze under other settings
uv run pytest test/test_level.py test/test_level_validation.py test/test_settings.py
```

To see it, with the start cells marked, run the maze viewer:
[`frontend/maze-viewer/`](../frontend/maze-viewer/README.md).

## `levels/maze.json` format

UTF-8 JSON, `format_version` 2. Field order is fixed by the generator so
diffs stay readable. Unknown fields are rejected.

| Field | Meaning |
|---|---|
| `format_version` | Always `2`. The loader refuses other values |
| `name` | Display name |
| `coordinates`, `legend` | Reminders of the conventions below. Not read by code |
| `generator` | The tool and the seed that produced this file |
| `width`, `height` | Grid size in cells |
| `exits` | `[{"id": 0, "cell": [x, y]}, ...]`, ids `0, 1, 2` |
| `grid` | `height` strings of `width` characters, `grid[y][x]` |

### Coordinates

A cell is `[x, y]` in JSON and `(x, y)` in Python. `x` is the column,
counted from 0 at the west edge. `y` is the row, counted from 0 at the north
edge. Row `y` of the grid is `grid[y]`, and the cell's character is
`grid[y][x]`. North is up on screen, so moving north means `y - 1`.

### Cells

| Char | Kind | Walkable |
|---|---|---|
| `#` | Wall | No |
| `.` | Floor | Yes |
| `E` | Exit | Yes, as a route's final cell only. See [Exits are endpoints](#exits-are-endpoints) |

Movement is one cell north, east, south or west onto a walkable cell. There
are no diagonal moves. Every distance and route below is measured on this
4-neighbour graph.

The grid is a **room lattice**, which is what makes "walls removed" countable:

- **Rooms** are at cells where `x` and `y` are both odd. There are 17 × 17 of
  them, and they are always walkable.
- **Pillars** are at cells where `x` and `y` are both even. They and the
  outer border are always wall.
- **Wall slots** are every other interior cell. Each sits between two
  orthogonally adjacent rooms and is either a wall (`#`) or opened (`.`).

An **exit** is a room on the outermost ring of rooms (`x` = 1 or 33, or
`y` = 1 or 33), marked `E` and listed in `exits`. The border wall beside it is
kept intact, so the exit is a cell the player steps onto, not a hole in the
map.

## `config/game.yaml`, section `level`

```yaml
level:
  safe_zone_radius: 2      # FR-G-05
  min_start_distance: 12   # FR-G-17
```

Both are required non-negative integers, and other keys in the section are
rejected. The SRS values are floors: validation fails if `safe_zone_radius`
is below 2 or `min_start_distance` is below 12, because going lower changes
the SRS rather than tuning within it. Raising either is a normal balance
change. The derived level follows automatically, and the tests prove it
(`test/test_settings.py`).

Other sections of `config/game.yaml` (Minotaur speed and so on) belong to
later phases and are ignored by the level loader.

## Definitions and checks

All checks live in [`game/app/maze.py`](../game/app/maze.py). The graph
algorithms are in [`game/app/graph.py`](../game/app/graph.py).

### Size: FR-G-01, at least 25 × 25

The grid must be at least 25 × 25 **cells**, which is how this level reads
FR-G-01's "a grid of at least 25×25". The level is 35 × 35 cells, a
17 × 17 room lattice. (The floor used to be a 25 × 25 room lattice, a
51 × 51-cell grid, which met the requirement under either reading. The team
chose a smaller maze.)

### Braid ratio: FR-G-01, 10–20 % of walls removed

On an `Rx × Ry` room lattice there are `S = Rx(Ry−1) + Ry(Rx−1)` wall slots.
A perfect maze, with exactly one route between any two rooms, is a spanning
tree of the `R = Rx·Ry` rooms. So any perfect maze opens exactly `R − 1`
slots and keeps `S − (R − 1)` walls. With `O` slots open:

```
braid ratio = (O − (R − 1)) / (S − (R − 1))
            = walls removed beyond a perfect maze / walls a perfect maze has
```

Here `S = 544` and `R = 289`, so a perfect maze has 256 walls. This level
opens `O = 327` slots, which removes 39 of them: **15.23 %**. The ratio is
computed from the grid alone. It doesn't matter how the level was made. It
is 0 for a perfect maze and 1 when every slot is open, and both endpoints
are tested.

### Exits: FR-G-03, exactly 3

The grid must have exactly three `E` cells, and `exits` must list the same
three cells with ids 0, 1 and 2.

### Distance

Every distance is the **shortest walkable path**, counted in moves,
computed by breadth-first search from each exit over the full walkable
graph. That is how far the player actually has to travel, which is why it
was chosen over straight-line distance. Because walls force detours, some
start cells are closer than `min_start_distance` as the crow flies, and a
test asserts that this happens. Start I, `[30, 23]`, is 7 cells from exit 2
in a straight line but 45 moves away on foot. The other exits are not blocked when measuring distance.
Blocking them could only make distances longer, so this is the stricter of
the two choices for a minimum distance.

### Safe zones: FR-G-05, derived

The safe zone of an exit is every walkable cell whose distance (as above)
from that exit is at most `safe_zone_radius`, including the exit itself. With
radius 2, each zone in this level is the exit plus 2 cells either way along
the outer corridor, 5 cells in all. The Minotaur may never occupy a zone
cell. The player may. Enforcing this belongs to the movement rules in a
later phase.

Validation also makes sure the zones cannot make the maze unsolvable:

- the zones are pairwise disjoint;
- no start cell is in a zone;
- the cells outside all zones form one connected region. The Minotaur can
  therefore reach every part of the maze it is allowed in, and patrol
  between exits (FR-M-03). A zone that walls off a pocket fails;
- the player's routes may pass through zones.

### Exits are endpoints

An exit is a terminal endpoint. A route to exit `t`:

- **ends at `t`**: it reaches `t` exactly once, as its last cell, and never
  continues past it;
- **never passes through another exit**: during route validation, the
  other two exits are treated as blocked cells. Routes to `t` are counted
  in the walkable graph with those two cells removed.

This applies to every exit equally. Each of the three is a destination for
its own routes and an obstacle for the routes to the other two.

### Two distinct routes: FR-G-02

A **route** is a simple path: a sequence of distinct cells, each a
neighbour of the next, from the start cell to the exit, obeying the endpoint
rule above. Two routes are **distinct** if their cell sequences differ.
They **may share** any number of intermediate cells. Even sharing every cell
but one is allowed, as long as the sequences differ. Routes do *not* have to
be vertex-disjoint.

Every valid start cell must have **at least two distinct routes to each of
the three exits**. A start with only one route to any exit, or no route at
all, is rejected.

> SRS FR-G-02 reads "two disjoint routes". The team has decided on the
> distinct-route definition above. The SRS text should be updated to match
> (see the Build Plan: contracts change together with the SRS).

How it is decided, exactly and with no length cutoff:

- **The fact used.** Let `P` be any route from `s` to `t`. A second,
  distinct route exists **if and only if some step of `P` is not a bridge**.
  A bridge is a connection whose removal disconnects the graph.
  - If a step of `P` is not a bridge, `s` and `t` stay connected without
    it. Any route found then differs from `P`, because `P` uses that step.
  - If every step of `P` is a bridge, every route must cross each of them,
    in order, with nothing in between. So every route equals `P`.
- **Validator (all cells at once, O(V+E)).** For each exit, it builds the
  graph with the other exits removed and finds the bridges. It then takes
  one route per cell from a breadth-first tree rooted at the exit, and keeps
  the cells whose route has a non-bridge step.
- **Tests (constructive, exhaustive).** For every walkable cell far enough
  from every exit, and for each exit, the tests build the routes
  explicitly. First a shortest route `P`, then, for each step of `P`, a route
  that avoids that step. Each route is checked independently: a real walk on
  the maze, ending at the first arrival at its exit, touching no other exit.
  The two routes must differ. The resulting set must equal the validator's
  start set. On small random graphs, both methods are also compared with
  brute-force enumeration of every simple path.

### Route complexity: no straightforward way out

FR-G-17's distance rule alone lets in starts with an easy way out: in a
braid maze, loops often offer a long but nearly straight run to an exit. So
the team added two measures, each a minimum over **every** route under the
endpoint rule, not over one chosen route:

- **Turns**: the number of direction changes along a route. The fewest
  turns of any route to an exit must be at least `min_route_turns`.
- **Decisions**: junctions passed on the way. A junction is a walkable cell
  with three or more walkable neighbours, where the player has to choose. The
  start and the exit themselves don't count. The fewest junctions of any
  route to an exit must be at least `min_route_decisions`.

Both are exact 0-1 breadth-first searches in
[`game/app/graph.py`](../game/app/graph.py) (`fewest_turns`,
`fewest_marked`), with no length cutoff. They minimise over walks. That gives
the same answer as over simple paths, because cutting a loop out of a walk
never adds a junction and never adds a turn: a loop must turn at least once
to come back. How they are tested:

- On small random grid graphs, both are compared with brute-force
  enumeration of every simple path.
- On the level, the turns are recomputed by a different algorithm, a
  breadth-first search over straight runs.
- The junctions are recomputed by a heap-based search from the start side.

With the committed thresholds, turns do the real filtering. Of the 348
cells that meet the other rules, 37 need 10 or more turns, and every one of
those also passes 5 or more junctions. The junction rule is still checked,
so a regenerated maze cannot slip through on turns alone.

### Start cells: FR-G-17, derived

A cell is **eligible** when all of these hold:

1. it is walkable, is not an exit, and is not in any safe zone;
2. its distance (as above) to every exit is at least `min_start_distance`;
3. it has at least two distinct routes to every exit under the endpoint
   rule;
4. every route to every exit makes at least `min_route_turns` turns and
   passes at least `min_route_decisions` junctions.

With the committed settings, 37 cells are eligible. The game uses
`start_cell_count` (10) of them, chosen to be spread across the maze by
**farthest-point selection** on walking distance:

- It starts with the cell whose easiest way out is hardest (most turns,
  then most junctions, then farthest).
- Then it repeatedly adds the eligible cell farthest from every cell chosen
  so far.
- Ties go to the more complex cell, then to row-major order.

So the set is deterministic, and every eligible cell left out is no farther
from a chosen start than the chosen starts are from each other (a test
checks this). The start cells are listed by row, then column; the viewer
labels them A–J in that order. The game will pick one at random each game
(FR-G-17, later phase). If fewer than `start_cell_count` cells are eligible,
the level is rejected (`start-count`).

## Regenerating

The maze is deterministic.
[`game/tools/generate_maze.py`](../game/tools/generate_maze.py) rebuilds it
byte for byte from the seed recorded in the file, and a test fails if the
file and the generator ever disagree.

```sh
cd game
uv run python -m tools.generate_maze --check   # verify the committed file against its seed
uv run python -m tools.generate_maze           # search seeds from 816 and rewrite the file
```

The generator carves a perfect maze with a seeded recursive backtracker,
then braids it in three passes. First it removes every dead end. Next, while
any articulation point remains, it opens a wall between two rooms that share
no biconnected component. Last, it opens random walls until the ratio
reaches 15 %, the middle of the band. It places the exits and keeps the
first seed from 816 upward whose level, derived with the settings in
`config/game.yaml`, passes the full validator, including the route-complexity
rules. Seed 818 is the first to pass. Seeds 816 and 817 make valid mazes,
but fewer than 10 of their cells have no straightforward way out.

`--check` uses only the recorded seed, not the settings, so changing a
setting never makes it fail. If a settings change makes the current maze
invalid, `python -m app.maze` and the tests fail instead.

Changing the maze changes the game for every model and every Kibana chart
(SRS §8.2 catch heatmap), so treat it like a contract.

# Maze viewer

A read-only browser view of the level. It draws every cell of
`levels/maze.json` exactly as stored, marks the exits and the valid start
cells, and lets you zoom and pan. It is a development aid, not the game page:
no gameplay, no WebSocket. The Phase 1 canvas game page will live in
`frontend/` separately.

The page is plain HTML, CSS and JavaScript with no build step. `serve.py` uses
only the Python standard library plus the game's own `app.maze`.

## Run it

From the repository root (in WSL):

```sh
cd game
uv run python ../frontend/maze-viewer/serve.py
```

Then open <http://localhost:8000/frontend/maze-viewer/>. Stop it with Ctrl+C.
Add `--port 8001` if 8000 is taken.

`serve.py` listens on 127.0.0.1 only and serves exactly three things:

- the viewer's page, stylesheet and script;
- `/levels/maze.json`, byte for byte;
- `/api/level`, the derived start cells and their easiest routes.

Nothing else in the repository (such as `.env`) is reachable through it.

## Start cells

Start cells are **not stored** in `maze.json`. The game derives them from the
maze and `config/game.yaml` (FR-G-17 and the route-complexity rules, see
`levels/README.md`). For `/api/level`, `serve.py` calls the game's own
`app.maze.load_level`, so the viewer shows exactly the set the validator
checks. It recomputes them on every request, so a reload picks up edits to
the maze or the settings.

Each start cell gets a green disc lettered A, B, C… in row order (a filled
cell at very small zoom). Hovering over one shows its easiest way out to
each exit: the fewest moves, turns and junctions of any route there. For
example: `start A · exit 0: at least 47 moves, 14 turns, 9 junctions · …`.
The **Start cells** checkbox, or the `S` key, shows and hides them. Hover
over the legend entry to see the rules.

If the start cells cannot be shown, the maze is still drawn, and the footer
says why. That happens in three cases:

- the page is served some other way, for example `python3 -m http.server`;
- the level fails validation;
- a file was opened with the file picker.

## What it shows

| | |
|---|---|
| Wall `#` | slate cell |
| Walkable `.` | near-black cell |
| Exit `E` | amber cell, labelled with its exit id once cells are large enough |
| Start cell | green disc with its letter, on a walkable cell |

The header shows the maze name, size, exit count, start-cell count,
generator seed and source file. The footer lists each exit's `[x, y]` and, on
hover, the cell under the pointer. Coordinates follow the format: `x` is the
column from the west edge, `y` the row from the north edge, `grid[y][x]`.

Before drawing, the viewer checks the parts of format version 2 it relies on:

- the grid is `height` rows of `width` characters from `#`, `.` and `E`;
- every exit sits on an `E` cell;
- every `E` is a listed exit;
- every start cell is a walkable, non-exit cell of this grid.

A file that fails these checks is reported, not drawn. The level rules
themselves (routes, safe zones, start cells) are checked by
`cd game && uv run python -m app.maze`, not here.

If the page is opened straight from disk (`file://`), it cannot fetch the
JSON. It then shows the launch command and offers a file picker.

## Controls

| Action | Control |
|---|---|
| Zoom in / out | `+` / `−` buttons, `+` / `-` keys, or Ctrl + mouse wheel (zooms at the pointer) |
| Reset view (fit the whole maze) | **Reset view** button or `0` |
| Show / hide start cells | **Start cells** checkbox or `S` |
| Pan when zoomed | Drag with the mouse, scroll, or swipe on touch screens |

Zoom runs from 2 to 64 screen pixels per cell. 100% is the size that fits the
window. Cells are drawn as whole device pixels, so edges stay sharp at any
zoom and display scale.

## Colours

The colours are CSS custom properties at the top of `viewer.css`: `--wall`,
`--floor`, `--exit` and `--start`. The canvas reads them from there, so the
legend and the drawing cannot disagree.

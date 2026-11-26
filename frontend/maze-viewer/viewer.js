// Read-only viewer for levels/maze.json (format_version 2, documented in
// levels/README.md). It draws the grid exactly as stored and changes nothing.
// Start cells are not in the maze file: the game derives them from the maze
// and config/game.yaml. serve.py answers /api/level with that derived set.
"use strict";

(() => {
  // Relative to this page, so the repository root must be what is served.
  const MAZE_URL = "../../levels/maze.json";
  const LEVEL_URL = "../../api/level"; // served by serve.py only
  const SUPPORTED_FORMAT = 2;
  // The format's legend: '#' wall, '.' floor, 'E' exit (walkable).
  const TILES = { "#": "wall", ".": "floor", E: "exit" };

  const ZOOM_STEP = 1.25;
  const MIN_CELL = 2; // CSS pixels per cell
  const MAX_CELL = 64;
  const GRID_MIN_PX = 6; // device pixels per cell before cell lines are drawn
  const LABEL_MIN_PX = 12; // ... before exit ids are drawn
  const DOT_MIN_PX = 14; // ... before start cells get a disc (below it, a filled cell)
  const START_LABEL_MIN_PX = 16; // ... before the discs carry their letter
  const MAX_PROBLEMS = 20;

  const $ = (id) => document.getElementById(id);
  const ui = {
    name: $("maze-name"),
    meta: $("maze-meta"),
    viewport: $("viewport"),
    canvas: $("maze"),
    zoomIn: $("zoom-in"),
    zoomOut: $("zoom-out"),
    zoomLevel: $("zoom-level"),
    reset: $("reset-view"),
    hover: $("hover"),
    exitList: $("exit-list"),
    notice: $("notice"),
    problems: $("notice-problems"),
    fileInput: $("file-input"),
    showStarts: $("show-starts"),
    legendStart: $("legend-start"),
    startNote: $("start-note"),
  };
  const ctx = ui.canvas.getContext("2d");

  let maze = null;
  // Derived start cells, or null:
  // { cells: Map of y * width + x -> { label, x, y, routes }, settings, eligible }.
  let starts = null;
  // cell: CSS px per cell. fit: true while the view tracks the window size.
  const view = { cell: 0, fitCell: 0, fit: true };

  class MazeError extends Error {
    constructor(problems) {
      super(problems.join("; "));
      this.problems = problems;
    }
  }

  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

  // ---- Reading and checking the file -------------------------------------

  // Checks the parts of the format the viewer relies on, so that a malformed
  // file is reported instead of being drawn wrongly. Level rules (routes, safe
  // zones, starts) are the Python validator's job: python -m app.maze.
  function parseMaze(data, source) {
    if (data === null || typeof data !== "object" || Array.isArray(data)) {
      throw new MazeError(["the file is not a JSON object"]);
    }
    const problems = [];
    const { width, height, grid, exits } = data;

    if (data.format_version !== SUPPORTED_FORMAT) {
      problems.push(
        `format_version is ${JSON.stringify(data.format_version)}; this viewer reads format ${SUPPORTED_FORMAT}`,
      );
    }
    if (!Number.isInteger(width) || width < 1) problems.push("width must be a positive integer");
    if (!Number.isInteger(height) || height < 1) problems.push("height must be a positive integer");
    if (!Array.isArray(grid)) problems.push("grid must be a list of row strings");
    if (!Array.isArray(exits)) problems.push("exits must be a list");
    if (problems.length) throw new MazeError(problems);

    if (grid.length !== height) problems.push(`grid has ${grid.length} rows but height is ${height}`);
    grid.forEach((row, y) => {
      if (typeof row !== "string" || row.length !== width) {
        problems.push(`grid row ${y} is not a string of ${width} characters`);
        return;
      }
      for (let x = 0; x < width; x++) {
        if (!Object.hasOwn(TILES, row[x])) {
          problems.push(`unknown character ${JSON.stringify(row[x])} at [${x}, ${y}]`);
        }
      }
    });
    if (problems.length) throw new MazeError(problems.slice(0, MAX_PROBLEMS));

    const ids = new Set();
    const exitAt = new Map(); // y * width + x -> exit id
    exits.forEach((exit, i) => {
      const cell = exit?.cell;
      if (!Number.isInteger(exit?.id) || !Array.isArray(cell) || cell.length !== 2 ||
          !cell.every(Number.isInteger)) {
        problems.push(`exits[${i}] is not {"id": <int>, "cell": [x, y]}`);
        return;
      }
      const [x, y] = cell;
      if (ids.has(exit.id)) problems.push(`exit id ${exit.id} appears twice`);
      ids.add(exit.id);
      if (x < 0 || y < 0 || x >= width || y >= height) {
        problems.push(`exit ${exit.id} at [${x}, ${y}] is outside the grid`);
      } else if (grid[y][x] !== "E") {
        problems.push(`exit ${exit.id} at [${x}, ${y}] is ${JSON.stringify(grid[y][x])} in the grid, not "E"`);
      } else {
        exitAt.set(y * width + x, exit.id);
      }
    });
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        if (grid[y][x] === "E" && !exitAt.has(y * width + x)) {
          problems.push(`grid has an "E" at [${x}, ${y}] that is not listed in exits`);
        }
      }
    }
    if (problems.length) throw new MazeError(problems.slice(0, MAX_PROBLEMS));

    return {
      name: typeof data.name === "string" && data.name ? data.name : "Maze",
      seed: data.generator?.seed,
      width,
      height,
      grid,
      exits: exits.map((e) => ({ id: e.id, x: e.cell[0], y: e.cell[1] })),
      exitAt,
      source,
    };
  }

  // Checks that the derived start cells belong to this maze: same size, and
  // every start a walkable, non-exit cell.
  function parseStarts(data, m) {
    if (!Array.isArray(data?.start_cells)) throw new Error("the response has no start_cells list");
    if (data.width !== m.width || data.height !== m.height) {
      throw new Error(`start cells are for a ${data.width} × ${data.height} grid, not this maze`);
    }
    const cells = new Map();
    data.start_cells.forEach((cell, i) => {
      if (!Array.isArray(cell) || cell.length !== 2 || !cell.every(Number.isInteger)) {
        throw new Error(`start cell ${JSON.stringify(cell)} is not [x, y]`);
      }
      const [x, y] = cell;
      if (x < 0 || y < 0 || x >= m.width || y >= m.height || m.grid[y][x] !== ".") {
        throw new Error(`start cell [${x}, ${y}] is not a walkable, non-exit cell of this maze`);
      }
      // Starts come sorted by row, then column, so A is the northernmost.
      const label = i < 26 ? String.fromCharCode(65 + i) : `S${i + 1}`;
      const routes = Array.isArray(data.start_routes?.[i]) ? data.start_routes[i] : [];
      cells.set(y * m.width + x, { label, x, y, routes });
    });
    return { cells, settings: data.settings ?? {}, eligible: data.eligible_start_cells };
  }

  function startRange(s) {
    const labels = [...s.cells.values()].map((c) => c.label);
    return labels.length > 1 ? `${labels[0]}–${labels.at(-1)}` : labels[0] ?? "";
  }

  async function fetchStarts(request, m) {
    const res = await request;
    if (res.status === 404) throw new Error("not served here. Start the viewer with serve.py to see them");
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      const why = body?.violations?.length ? `: ${body.violations.join("; ")}` : "";
      throw new Error(`${body?.error ?? `HTTP ${res.status}`}${why}`);
    }
    return parseStarts(body, m);
  }

  async function loadDefault() {
    const startsRequest = fetch(LEVEL_URL, { cache: "no-store" });
    startsRequest.catch(() => {}); // a failure is reported below, once the maze is in
    let m;
    try {
      const res = await fetch(MAZE_URL, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status} for ${res.url}`);
      m = parseMaze(await res.json(), "levels/maze.json");
    } catch (err) {
      fail(err, "levels/maze.json");
      return;
    }
    try {
      show(m, await fetchStarts(startsRequest, m), "");
    } catch (err) {
      show(m, null, err.message);
    }
  }

  async function loadFile(file) {
    try {
      const m = parseMaze(JSON.parse(await file.text()), file.name);
      show(m, null, `derived only for levels/maze.json, not ${file.name}`);
    } catch (err) {
      fail(err, file.name);
    }
  }

  function fail(err, source) {
    maze = null;
    starts = null;
    ui.canvas.hidden = true;
    ui.startNote.hidden = true;
    ui.notice.hidden = false;
    ui.name.textContent = "Maze viewer";
    ui.meta.textContent = `Could not load ${source}`;
    ui.exitList.textContent = "";
    ui.problems.replaceChildren(
      ...(err instanceof MazeError ? err.problems : [`${source}: ${err.message}`]).map((text) => {
        const li = document.createElement("li");
        li.textContent = text;
        return li;
      }),
    );
    setControls(false);
  }

  function show(m, startInfo, startProblem) {
    maze = m;
    starts = startInfo;
    ui.notice.hidden = true;
    ui.canvas.hidden = false;

    const exitText = m.exits.map((e) => `${e.id} [${e.x}, ${e.y}]`).join(" · ");
    const seed = m.seed === undefined ? "" : ` · seed ${m.seed}`;
    const startText = starts
      ? `${plural(starts.cells.size, "start cell")} (${startRange(starts)})`
      : "start cells unavailable";
    ui.name.textContent = m.name;
    ui.meta.textContent =
      `${m.width} × ${m.height} cells · ${plural(m.exits.length, "exit")} · ${startText}${seed} · ${m.source}`;
    ui.startNote.hidden = Boolean(starts);
    ui.startNote.textContent = starts ? "" : `Start cells unavailable: ${startProblem}`;
    const s = starts?.settings ?? {};
    ui.legendStart.title = starts
      ? `Start cells (FR-G-17), derived from config/game.yaml. Every route from each one to every exit ` +
        `is at least ${s.min_route_turns} turns and ${s.min_route_decisions} junctions long, and at least ` +
        `${s.min_start_distance} moves; outside the ${s.safe_zone_radius}-cell safe zones; two routes ` +
        `to every exit. ${starts.cells.size} chosen, spread out, from ${starts.eligible ?? "?"} cells ` +
        `that qualify. Hover over a start for its routes.`
      : `Start cells unavailable: ${startProblem}`;
    ui.exitList.textContent = `Exits: ${exitText}`;
    ui.canvas.setAttribute(
      "aria-label",
      `${m.name}: ${m.width} by ${m.height} cells, ${plural(m.exits.length, "exit")} at ${exitText}`,
    );

    setControls(true);
    ui.showStarts.disabled = !starts;
    resetView();
  }

  // ---- Drawing -------------------------------------------------------------

  function colours() {
    const css = getComputedStyle(document.documentElement);
    const v = (name) => css.getPropertyValue(name).trim();
    return {
      wall: v("--wall"), floor: v("--floor"), exit: v("--exit"), exitText: v("--exit-text"),
      start: v("--start"), startText: v("--start-text"), grid: v("--grid"),
    };
  }

  // Each cell is a whole number of device pixels, so every cell edge lands on
  // a pixel boundary and the grid stays sharp at any zoom or display scale.
  function draw() {
    const { width: W, height: H, grid } = maze;
    const dpr = window.devicePixelRatio || 1;
    const d = Math.max(1, Math.floor(view.cell * dpr));
    const c = ui.canvas;
    const col = colours();

    c.width = d * W;
    c.height = d * H;
    c.style.width = `${(d * W) / dpr}px`;
    c.style.height = `${(d * H) / dpr}px`;

    ctx.fillStyle = col.floor;
    ctx.fillRect(0, 0, c.width, c.height);
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const t = grid[y][x];
        if (t === "#" || t === "E") {
          ctx.fillStyle = t === "#" ? col.wall : col.exit;
          ctx.fillRect(x * d, y * d, d, d);
        }
      }
    }

    // Start cells: a lettered disc in the middle of the cell, or the whole
    // cell when cells are too small for a disc to read.
    if (starts && ui.showStarts.checked) {
      for (const { label, x, y } of starts.cells.values()) {
        ctx.fillStyle = col.start;
        if (d >= DOT_MIN_PX) {
          ctx.beginPath();
          ctx.arc((x + 0.5) * d, (y + 0.5) * d, d * 0.36, 0, 2 * Math.PI);
          ctx.fill();
        } else {
          ctx.fillRect(x * d, y * d, d, d);
        }
        if (d >= START_LABEL_MIN_PX) {
          ctx.fillStyle = col.startText;
          ctx.font = `700 ${Math.floor(d * 0.5)}px system-ui, sans-serif`;
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(label, (x + 0.5) * d, (y + 0.5) * d + 1);
        }
      }
    }

    if (d >= GRID_MIN_PX) {
      ctx.fillStyle = col.grid;
      for (let x = 1; x < W; x++) ctx.fillRect(x * d, 0, 1, H * d);
      for (let y = 1; y < H; y++) ctx.fillRect(0, y * d, W * d, 1);
    }

    if (d >= LABEL_MIN_PX) {
      ctx.fillStyle = col.exitText;
      ctx.font = `700 ${Math.floor(d * 0.75)}px system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      for (const e of maze.exits) ctx.fillText(String(e.id), (e.x + 0.5) * d, (e.y + 0.5) * d + 1);
    }

    updateControls();
  }

  // ---- View: fit, zoom, pan ------------------------------------------------

  function computeFitCell() {
    const vp = ui.viewport;
    const css = getComputedStyle(vp);
    const w = vp.clientWidth - parseFloat(css.paddingLeft) - parseFloat(css.paddingRight);
    const h = vp.clientHeight - parseFloat(css.paddingTop) - parseFloat(css.paddingBottom);
    return clamp(Math.floor(Math.min(w / maze.width, h / maze.height)), MIN_CELL, MAX_CELL);
  }

  function resetView() {
    if (!maze) return;
    view.fitCell = computeFitCell();
    view.cell = view.fitCell;
    view.fit = true;
    draw();
    ui.viewport.scrollTo(0, 0);
  }

  // Zooms so that the maze point under `anchor` (client coordinates; the
  // middle of the view by default) stays where it is on screen.
  function zoomTo(next, anchor) {
    next = clamp(next, MIN_CELL, MAX_CELL);
    if (!maze || next === view.cell) return;
    const vp = ui.viewport;
    if (!anchor) {
      const r = vp.getBoundingClientRect();
      anchor = { x: r.left + vp.clientWidth / 2, y: r.top + vp.clientHeight / 2 };
    }
    const before = ui.canvas.getBoundingClientRect();
    const fx = (anchor.x - before.left) / before.width;
    const fy = (anchor.y - before.top) / before.height;

    view.cell = next;
    view.fit = next === view.fitCell;
    draw();

    const after = ui.canvas.getBoundingClientRect();
    vp.scrollLeft += after.left + fx * after.width - anchor.x;
    vp.scrollTop += after.top + fy * after.height - anchor.y;
  }

  function zoomStep(direction, anchor) {
    const c = view.cell;
    const next = direction > 0
      ? Math.max(c + 1, Math.round(c * ZOOM_STEP))
      : Math.min(c - 1, Math.round(c / ZOOM_STEP));
    zoomTo(next, anchor);
  }

  function setControls(enabled) {
    for (const b of [ui.zoomIn, ui.zoomOut, ui.reset]) b.disabled = !enabled;
    if (!enabled) {
      ui.zoomLevel.textContent = "";
      ui.showStarts.disabled = true;
    }
  }

  function updateControls() {
    ui.zoomLevel.textContent = `${Math.round((view.cell / view.fitCell) * 100)}%`;
    ui.zoomIn.disabled = view.cell >= MAX_CELL;
    ui.zoomOut.disabled = view.cell <= MIN_CELL;
    const vp = ui.viewport;
    vp.classList.toggle("pannable", vp.scrollWidth > vp.clientWidth || vp.scrollHeight > vp.clientHeight);
  }

  // ---- Input ---------------------------------------------------------------

  ui.zoomIn.addEventListener("click", () => zoomStep(+1));
  ui.zoomOut.addEventListener("click", () => zoomStep(-1));
  ui.reset.addEventListener("click", resetView);
  ui.showStarts.addEventListener("change", () => maze && draw());
  ui.fileInput.addEventListener("change", () => {
    if (ui.fileInput.files.length) loadFile(ui.fileInput.files[0]);
  });

  document.addEventListener("keydown", (e) => {
    if (!maze || e.ctrlKey || e.metaKey || e.altKey || e.target instanceof HTMLInputElement) return;
    if (e.key === "+" || e.key === "=") zoomStep(+1);
    else if (e.key === "-" || e.key === "_") zoomStep(-1);
    else if (e.key === "0") resetView();
    else if ((e.key === "s" || e.key === "S") && starts) {
      ui.showStarts.checked = !ui.showStarts.checked;
      draw();
    } else return;
    e.preventDefault();
  });

  // Ctrl/Cmd + wheel zooms at the pointer; a plain wheel scrolls as usual.
  ui.viewport.addEventListener("wheel", (e) => {
    if (!maze || !(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    zoomStep(e.deltaY < 0 ? +1 : -1, { x: e.clientX, y: e.clientY });
  }, { passive: false });

  // Drag with the mouse to pan when zoomed in. Touch scrolls natively.
  let drag = null;
  ui.viewport.addEventListener("pointerdown", (e) => {
    if (e.pointerType !== "mouse" || e.button !== 0 || !ui.viewport.classList.contains("pannable")) return;
    drag = { x: e.clientX, y: e.clientY, left: ui.viewport.scrollLeft, top: ui.viewport.scrollTop };
    ui.viewport.setPointerCapture(e.pointerId);
    ui.viewport.classList.add("dragging");
  });
  ui.viewport.addEventListener("pointermove", (e) => {
    if (!drag) return;
    ui.viewport.scrollLeft = drag.left - (e.clientX - drag.x);
    ui.viewport.scrollTop = drag.top - (e.clientY - drag.y);
  });
  const endDrag = () => {
    drag = null;
    ui.viewport.classList.remove("dragging");
  };
  ui.viewport.addEventListener("pointerup", endDrag);
  ui.viewport.addEventListener("pointercancel", endDrag);

  ui.canvas.addEventListener("pointermove", (e) => {
    if (!maze) return;
    const r = ui.canvas.getBoundingClientRect();
    const x = Math.floor(((e.clientX - r.left) / r.width) * maze.width);
    const y = Math.floor(((e.clientY - r.top) / r.height) * maze.height);
    if (x < 0 || y < 0 || x >= maze.width || y >= maze.height) return;
    const tile = TILES[maze.grid[y][x]];
    const i = y * maze.width + x;
    const start = starts?.cells.get(i);
    ui.hover.textContent =
      tile === "exit" ? `[${x}, ${y}] exit ${maze.exitAt.get(i)}`
      : tile === "wall" ? `[${x}, ${y}] wall`
      : start ? `[${x}, ${y}] start ${start.label}${describeRoutes(start.routes)}`
      : `[${x}, ${y}] walkable`;
  });
  // The easiest route to each exit: every route is at least this long, turns
  // at least this often and passes at least this many junctions.
  function describeRoutes(routes) {
    return routes
      .map((r) => ` · exit ${r.exit}: at least ${r.moves} moves, ${r.turns} turns, ${r.junctions} junctions`)
      .join("");
  }

  ui.canvas.addEventListener("pointerleave", () => {
    ui.hover.textContent = "Hover over a cell to see its [x, y]";
  });

  // Refit while the view is in fit mode; otherwise just redraw, which also
  // picks up a change of display scale (browser zoom, another monitor).
  new ResizeObserver(() => {
    if (!maze) return;
    view.fitCell = computeFitCell();
    if (view.fit) view.cell = view.fitCell;
    draw();
  }).observe(ui.viewport);

  loadDefault();
})();

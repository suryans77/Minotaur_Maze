"""config/game.yaml is the single source of the tunable level settings, and
changing a setting changes the derived level and its validation correctly."""

from __future__ import annotations

import dataclasses

import pytest
import yaml

from app.maze import (
    DEFAULT_CONFIG_PATH,
    SRS_MIN_START_DISTANCE,
    SRS_SAFE_ZONE_RADIUS,
    LevelSettings,
    SettingsError,
    derive_level,
    load_level,
    load_settings,
    main,
    parse_settings,
    validate_level,
)

COMMITTED = {
    "safe_zone_radius": 2,
    "min_start_distance": 20,
    "min_route_turns": 10,
    "min_route_decisions": 5,
    "start_cell_count": 10,
}


def with_settings(level, **changes):
    """The committed maze re-derived under changed settings."""
    return derive_level(level.maze, dataclasses.replace(level.settings, **changes))


def codes(level) -> set[str]:
    return {v.code for v in validate_level(level)}


def write_config(tmp_path, **changes):
    path = tmp_path / "game.yaml"
    path.write_text(yaml.safe_dump({"level": {**COMMITTED, **changes}}))
    return path


def test_committed_config_holds_the_expected_values():
    assert load_settings(DEFAULT_CONFIG_PATH) == LevelSettings(**COMMITTED)


def test_loader_reads_settings_from_the_config_file(tmp_path, level):
    path = write_config(tmp_path, min_start_distance=36)
    loaded = load_level(config_path=path)
    assert loaded.settings.min_start_distance == 36
    assert loaded.eligible_start_cells == with_settings(level, min_start_distance=36).eligible_start_cells
    assert len(loaded.eligible_start_cells) < len(level.eligible_start_cells)


# --- min_start_distance ------------------------------------------------------------


def test_raising_min_start_distance_shrinks_the_eligible_set(level):
    farther = with_settings(level, min_start_distance=36)
    assert codes(farther) == set()
    assert set(farther.eligible_start_cells) < set(level.eligible_start_cells)
    maze = level.maze
    assert all(maze.exit_distances[e.id][s] >= 36 for s in farther.eligible_start_cells for e in maze.exits)
    # The cells that dropped out are exactly those now too close to some exit.
    dropped = set(level.eligible_start_cells) - set(farther.eligible_start_cells)
    assert all(min(maze.exit_distances[e.id][s] for e in maze.exits) < 36 for s in dropped)


def test_min_start_distance_too_large_for_the_maze_leaves_no_start(level):
    assert "start-empty" in codes(with_settings(level, min_start_distance=500))


def test_min_start_distance_below_the_srs_value_fails(level):
    # With the complexity rules off, distance is the only thing that limits the set.
    plain = {"min_route_turns": 0, "min_route_decisions": 0}
    at_floor = with_settings(level, min_start_distance=SRS_MIN_START_DISTANCE, **plain)
    closer = with_settings(level, min_start_distance=SRS_MIN_START_DISTANCE - 1, **plain)
    assert set(closer.eligible_start_cells) > set(at_floor.eligible_start_cells)  # follows the setting
    assert "settings" in codes(closer)


# --- route complexity ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "table"), [("min_route_turns", "route_turns"), ("min_route_decisions", "route_decisions")]
)
def test_raising_a_complexity_threshold_drops_exactly_the_cells_below_it(level, key, table):
    stricter = with_settings(level, **{key: getattr(level.settings, key) + 1})
    assert codes(stricter) == set()  # 12 cells remain, enough for 10 starts
    assert set(stricter.eligible_start_cells) < set(level.eligible_start_cells)
    per_exit = getattr(level.maze, table)
    threshold = getattr(level.settings, key)
    dropped = set(level.eligible_start_cells) - set(stricter.eligible_start_cells)
    assert all(min(per_exit[e.id][s] for e in level.maze.exits) == threshold for s in dropped)


def test_relaxing_the_complexity_rules_admits_straightforward_cells(level):
    relaxed = with_settings(level, min_route_turns=0, min_route_decisions=0)
    assert set(relaxed.eligible_start_cells) > set(level.eligible_start_cells)
    extra = set(relaxed.eligible_start_cells) - set(level.eligible_start_cells)
    maze = level.maze
    assert all(
        min(maze.route_turns[e.id][c] for e in maze.exits) < level.settings.min_route_turns
        or min(maze.route_decisions[e.id][c] for e in maze.exits) < level.settings.min_route_decisions
        for c in extra
    )


def test_complexity_thresholds_too_high_for_the_maze_leave_no_start(level):
    assert "start-empty" in codes(with_settings(level, min_route_turns=200))
    assert "start-empty" in codes(with_settings(level, min_route_decisions=200))


# --- start_cell_count ----------------------------------------------------------------------


def test_start_cell_count_sets_how_many_starts_are_chosen(level):
    for count in (1, 5, len(level.eligible_start_cells)):
        changed = with_settings(level, start_cell_count=count)
        assert len(changed.start_cells) == count
        assert codes(changed) == set()
    assert set(with_settings(level, start_cell_count=len(level.eligible_start_cells)).start_cells) == set(
        level.eligible_start_cells
    )


def test_start_cell_count_above_the_eligible_cells_fails(level):
    greedy = with_settings(level, start_cell_count=len(level.eligible_start_cells) + 1)
    assert set(greedy.start_cells) == set(level.eligible_start_cells)  # all of them, still too few
    assert "start-count" in codes(greedy)


def test_start_cell_count_of_zero_fails(level):
    assert {"settings", "start-empty"} <= codes(with_settings(level, start_cell_count=0))


# --- safe_zone_radius --------------------------------------------------------------------


def test_raising_safe_zone_radius_grows_the_zones(level):
    wider = with_settings(level, safe_zone_radius=3)
    assert codes(wider) == set()
    for exit_id, zone in level.safe_zones.items():
        assert wider.safe_zones[exit_id] > zone
    assert not set(wider.eligible_start_cells) & wider.all_safe_cells


def test_oversized_safe_zones_fail(level):
    huge = with_settings(level, safe_zone_radius=60)
    assert {"safe-zone-overlap", "minotaur-region"} <= codes(huge)
    assert len(huge.eligible_start_cells) < len(level.eligible_start_cells)  # zone cells are never starts


def test_safe_zone_radius_below_the_srs_value_fails(level):
    narrower = with_settings(level, safe_zone_radius=SRS_SAFE_ZONE_RADIUS - 1)
    assert all(len(z) < len(level.safe_zones[i]) for i, z in narrower.safe_zones.items())
    assert "settings" in codes(narrower)


# --- config file format ----------------------------------------------------------------------


def _without(key):
    return {k: v for k, v in COMMITTED.items() if k != key}


@pytest.mark.parametrize(
    "config",
    [
        None,
        {},
        {"level": None},
        {"level": _without("min_route_turns")},
        {"level": {**COMMITTED, "minotaur_speed": 1}},
        {"level": {**COMMITTED, "safe_zone_radius": "2"}},
        {"level": {**COMMITTED, "start_cell_count": True}},
        {"level": {**COMMITTED, "min_route_decisions": -1}},
    ],
    ids=[
        "empty-file",
        "no-section",
        "null-section",
        "missing-key",
        "unknown-key",
        "string",
        "bool",
        "negative",
    ],
)
def test_malformed_settings_are_rejected(config):
    with pytest.raises(SettingsError):
        parse_settings(config)


def test_complete_settings_are_accepted():
    assert parse_settings({"level": COMMITTED}) == LevelSettings(**COMMITTED)


def test_invalid_yaml_is_rejected(tmp_path):
    path = tmp_path / "game.yaml"
    path.write_text("level: [unclosed\n")
    with pytest.raises(SettingsError):
        load_settings(path)


def test_cli_rejects_settings_below_the_srs_values(tmp_path, capsys):
    path = write_config(tmp_path, min_start_distance=5)
    assert main(["--config", str(path)]) == 1
    assert "[settings]" in capsys.readouterr().err

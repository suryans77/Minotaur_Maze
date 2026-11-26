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


def with_settings(level, **changes):
    """The committed maze re-derived under changed settings."""
    return derive_level(level.maze, dataclasses.replace(level.settings, **changes))


def codes(level) -> set[str]:
    return {v.code for v in validate_level(level)}


def write_config(tmp_path, **level_section):
    path = tmp_path / "game.yaml"
    path.write_text(yaml.safe_dump({"level": level_section}))
    return path


def test_committed_config_holds_the_srs_values():
    assert load_settings(DEFAULT_CONFIG_PATH) == LevelSettings(safe_zone_radius=2, min_start_distance=12)


def test_loader_reads_settings_from_the_config_file(tmp_path, level):
    path = write_config(tmp_path, safe_zone_radius=2, min_start_distance=20)
    loaded = load_level(config_path=path)
    assert loaded.settings.min_start_distance == 20
    assert loaded.start_cells == with_settings(level, min_start_distance=20).start_cells
    assert len(loaded.start_cells) < len(level.start_cells)


# --- min_start_distance ------------------------------------------------------------


def test_raising_min_start_distance_shrinks_the_start_set(level):
    farther = with_settings(level, min_start_distance=20)
    assert codes(farther) == set()
    assert set(farther.start_cells) < set(level.start_cells)
    maze = level.maze
    assert all(maze.exit_distances[e.id][s] >= 20 for s in farther.start_cells for e in maze.exits)
    # The cells that dropped out are exactly those now too close to some exit.
    dropped = set(level.start_cells) - set(farther.start_cells)
    assert all(min(maze.exit_distances[e.id][s] for e in maze.exits) < 20 for s in dropped)


def test_min_start_distance_too_large_for_the_maze_leaves_no_start(level):
    assert "start-empty" in codes(with_settings(level, min_start_distance=500))


def test_min_start_distance_below_the_srs_value_fails(level):
    closer = with_settings(level, min_start_distance=SRS_MIN_START_DISTANCE - 1)
    assert set(closer.start_cells) > set(level.start_cells)  # derivation follows the setting
    assert "settings" in codes(closer)


# --- safe_zone_radius --------------------------------------------------------------------


def test_raising_safe_zone_radius_grows_the_zones(level):
    wider = with_settings(level, safe_zone_radius=3)
    assert codes(wider) == set()
    for exit_id, zone in level.safe_zones.items():
        assert wider.safe_zones[exit_id] > zone
    assert not set(wider.start_cells) & wider.all_safe_cells


def test_oversized_safe_zones_fail(level):
    huge = with_settings(level, safe_zone_radius=60)
    assert {"safe-zone-overlap", "minotaur-region"} <= codes(huge)
    assert len(huge.start_cells) < len(level.start_cells)  # zone cells are never starts


def test_safe_zone_radius_below_the_srs_value_fails(level):
    narrower = with_settings(level, safe_zone_radius=SRS_SAFE_ZONE_RADIUS - 1)
    assert all(len(z) < len(level.safe_zones[i]) for i, z in narrower.safe_zones.items())
    assert "settings" in codes(narrower)


# --- config file format ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "config",
    [
        None,
        {},
        {"level": None},
        {"level": {"safe_zone_radius": 2}},
        {"level": {"safe_zone_radius": 2, "min_start_distance": 12, "minotaur_speed": 1}},
        {"level": {"safe_zone_radius": "2", "min_start_distance": 12}},
        {"level": {"safe_zone_radius": True, "min_start_distance": 12}},
        {"level": {"safe_zone_radius": 2, "min_start_distance": -1}},
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


def test_invalid_yaml_is_rejected(tmp_path):
    path = tmp_path / "game.yaml"
    path.write_text("level: [unclosed\n")
    with pytest.raises(SettingsError):
        load_settings(path)


def test_cli_rejects_settings_below_the_srs_values(tmp_path, capsys):
    path = write_config(tmp_path, safe_zone_radius=2, min_start_distance=5)
    assert main(["--config", str(path)]) == 1
    assert "[settings]" in capsys.readouterr().err

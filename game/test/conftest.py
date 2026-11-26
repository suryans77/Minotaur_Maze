from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.maze import DEFAULT_MAZE_PATH, Level, LevelSettings, load_level, load_settings


@pytest.fixture(scope="session")
def _maze_data() -> dict:
    return json.loads(DEFAULT_MAZE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def maze_data(_maze_data: dict) -> dict:
    """A private, mutable copy of the committed maze file's JSON."""
    return copy.deepcopy(_maze_data)


@pytest.fixture(scope="session")
def settings() -> LevelSettings:
    """The committed settings from config/game.yaml."""
    return load_settings()


@pytest.fixture(scope="session")
def level() -> Level:
    """The committed maze and settings, loaded with full validation."""
    return load_level()


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:  # runs startup and shutdown
        yield test_client

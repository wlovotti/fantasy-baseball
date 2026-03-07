"""Tests for replacement level calculation."""

import pandas as pd
import pytest

from config.positions import Position
from valuation.replacement import calculate_replacement_levels, _find_best_position


@pytest.fixture
def simple_player_pool():
    """Create a small player pool for testing replacement level logic."""
    players = []

    # 20 catchers with descending points
    for i in range(20):
        players.append({
            "name": f"Catcher {i}",
            "positions": [Position.C, Position.UTIL],
            "points": 300 - i * 10,
            "player_type": "hitter",
        })

    # 20 first basemen
    for i in range(20):
        players.append({
            "name": f"First Baseman {i}",
            "positions": [Position.FIRST, Position.UTIL],
            "points": 400 - i * 10,
            "player_type": "hitter",
        })

    # 40 outfielders
    for i in range(40):
        players.append({
            "name": f"Outfielder {i}",
            "positions": [Position.OF, Position.UTIL],
            "points": 350 - i * 5,
            "player_type": "hitter",
        })

    # 60 pitchers
    for i in range(60):
        players.append({
            "name": f"Pitcher {i}",
            "positions": [Position.P],
            "points": 300 - i * 3,
            "player_type": "pitcher",
        })

    return pd.DataFrame(players)


class TestReplacementLevels:
    """Tests for replacement level calculation."""

    def test_returns_all_positions(self, simple_player_pool):
        """Should return replacement levels for all positions."""
        levels = calculate_replacement_levels(simple_player_pool)
        for pos in Position:
            assert pos in levels

    def test_replacement_levels_are_reasonable(self, simple_player_pool):
        """Replacement levels should be between min and max player points."""
        levels = calculate_replacement_levels(simple_player_pool)
        max_pts = simple_player_pool["points"].max()
        min_pts = simple_player_pool["points"].min()

        for pos, level in levels.items():
            assert level >= 0, f"{pos} has negative replacement level"
            assert level <= max_pts, f"{pos} replacement level exceeds max"

    def test_replacement_level_below_best_player(self, simple_player_pool):
        """Replacement level at each position should be below the best player there.

        The best catcher (300 pts) and best outfielder (350 pts) should both
        be above their respective replacement levels.
        """
        levels = calculate_replacement_levels(simple_player_pool)
        assert levels[Position.C] < 300, "Replacement C should be below best catcher"
        assert levels[Position.OF] < 350, "Replacement OF should be below best OF"
        assert levels[Position.P] < 300, "Replacement P should be below best pitcher"


class TestFindBestPosition:
    """Tests for the greedy position assignment helper."""

    def test_prefers_scarce_position(self):
        """Should assign to the position with fewer remaining slots."""
        remaining = {Position.C: 1, Position.FIRST: 5, Position.UTIL: 10}
        eligible = [Position.C, Position.FIRST, Position.UTIL]
        assert _find_best_position(eligible, remaining) == Position.C

    def test_deprioritizes_util(self):
        """Util should only be used when specific positions are full."""
        remaining = {Position.FIRST: 0, Position.UTIL: 5}
        eligible = [Position.FIRST, Position.UTIL]
        assert _find_best_position(eligible, remaining) == Position.UTIL

    def test_returns_none_when_no_slots(self):
        """Should return None when all eligible positions are full."""
        remaining = {Position.C: 0, Position.UTIL: 0}
        eligible = [Position.C, Position.UTIL]
        assert _find_best_position(eligible, remaining) is None

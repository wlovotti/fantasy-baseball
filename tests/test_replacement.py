"""Tests for replacement level calculation."""

import pandas as pd
import pytest

from config.league import LeagueSettings
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


class TestReplacementLevelValidation:
    """Tests for the Util-only validation guard."""

    def test_raises_on_all_util_hitters(self):
        """Should raise ValueError when most hitters have only [Util] positions."""
        players = []
        for i in range(20):
            players.append({
                "name": f"Hitter {i}",
                "positions": [Position.UTIL],
                "points": 300 - i * 10,
                "player_type": "hitter",
            })
        for i in range(10):
            players.append({
                "name": f"Pitcher {i}",
                "positions": [Position.P],
                "points": 250 - i * 10,
                "player_type": "pitcher",
            })
        df = pd.DataFrame(players)
        with pytest.raises(ValueError, match="positions"):
            calculate_replacement_levels(df)


class TestLeagueSettingsBenchHitters:
    """Tests for the bench_hitters override on LeagueSettings."""

    def test_default_bench_hitters_is_one(self):
        """Default LeagueSettings should use calibrated bench_hitters=1."""
        league = LeagueSettings()
        assert league.bench_hitters == 1

    def test_bench_hitting_estimate_with_override(self):
        """Setting bench_hitters should override proportional calculation."""
        league = LeagueSettings(bench_hitters=1)
        assert league.bench_hitting_estimate == 1 * league.num_teams

    def test_bench_pitching_estimate_with_override(self):
        """Bench pitching should be the remainder after bench hitters."""
        league = LeagueSettings(bench_hitters=1)
        total_bench = league.bench * league.num_teams
        assert league.bench_pitching_estimate == total_bench - league.bench_hitting_estimate

    def test_bench_hitters_zero(self):
        """bench_hitters=0 should allocate all bench to pitchers."""
        league = LeagueSettings(bench_hitters=0)
        assert league.bench_hitting_estimate == 0
        assert league.bench_pitching_estimate == league.bench * league.num_teams

    def test_bench_hitters_equals_bench(self):
        """bench_hitters=bench should allocate all bench to hitters."""
        league = LeagueSettings(bench_hitters=4)
        assert league.bench_hitting_estimate == 4 * league.num_teams
        assert league.bench_pitching_estimate == 0

    def test_bench_hitters_too_high_raises(self):
        """bench_hitters > bench should raise ValueError."""
        with pytest.raises(ValueError, match="bench_hitters must be between"):
            LeagueSettings(bench_hitters=5)

    def test_bench_hitters_negative_raises(self):
        """Negative bench_hitters should raise ValueError."""
        with pytest.raises(ValueError, match="bench_hitters must be between"):
            LeagueSettings(bench_hitters=-1)


class TestReplacementLevelsWithCustomLeague:
    """Tests that calculate_replacement_levels respects a custom league param."""

    @pytest.fixture
    def large_player_pool(self):
        """Player pool large enough that bench allocation affects P replacement.

        With 14 teams * 8 P slots = 112 starting pitchers + up to 56 bench,
        we need >168 pitchers so bench allocation matters.
        """
        players = []
        for i in range(30):
            players.append({
                "name": f"Catcher {i}",
                "positions": [Position.C, Position.UTIL],
                "points": 300 - i * 5,
                "player_type": "hitter",
            })
        for i in range(30):
            players.append({
                "name": f"First Baseman {i}",
                "positions": [Position.FIRST, Position.UTIL],
                "points": 400 - i * 5,
                "player_type": "hitter",
            })
        for i in range(60):
            players.append({
                "name": f"Outfielder {i}",
                "positions": [Position.OF, Position.UTIL],
                "points": 350 - i * 3,
                "player_type": "hitter",
            })
        for i in range(200):
            players.append({
                "name": f"Pitcher {i}",
                "positions": [Position.P],
                "points": 300 - i * 1,
                "player_type": "pitcher",
            })
        return pd.DataFrame(players)

    def test_custom_league_changes_replacement_levels(self, large_player_pool):
        """Replacement levels should differ with different bench allocations."""
        all_bench_hitting = LeagueSettings(bench_hitters=4)
        no_bench_hitting = LeagueSettings(bench_hitters=0)

        levels_all_h = calculate_replacement_levels(
            large_player_pool, league=all_bench_hitting
        )
        levels_no_h = calculate_replacement_levels(
            large_player_pool, league=no_bench_hitting
        )

        # All bench to pitchers gives more P slots → lower P replacement level
        assert levels_no_h[Position.P] < levels_all_h[Position.P]

    def test_zero_bench_hitters_raises_pitcher_replacement(self, large_player_pool):
        """Zero bench hitters means more pitcher bench → lower P replacement."""
        default_levels = calculate_replacement_levels(large_player_pool)

        no_bench_hitting = LeagueSettings(bench_hitters=0)
        custom_levels = calculate_replacement_levels(
            large_player_pool, league=no_bench_hitting
        )

        # More pitcher bench slots → replacement pitcher is worse (lower points)
        assert custom_levels[Position.P] <= default_levels[Position.P]

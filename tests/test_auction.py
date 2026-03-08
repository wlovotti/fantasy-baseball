"""Tests for auction dollar value calculation."""

import pandas as pd
import pytest

from config.league import LEAGUE, LeagueSettings
from config.positions import Position
from valuation.auction import calculate_auction_values, format_positions


@pytest.fixture
def valued_pool():
    """Create a player pool with pre-calculated points."""
    players = []
    # 50 hitters
    for i in range(50):
        players.append({
            "name": f"Hitter {i}",
            "positions": [Position.OF, Position.UTIL],
            "points": 400 - i * 5,
            "player_type": "hitter",
        })
    # 50 pitchers
    for i in range(50):
        players.append({
            "name": f"Pitcher {i}",
            "positions": [Position.P],
            "points": 350 - i * 5,
            "player_type": "pitcher",
        })
    return pd.DataFrame(players)


@pytest.fixture
def mixed_position_pool():
    """Create a player pool with varied positions to exercise position scarcity."""
    players = []
    # 5 catchers (scarce position)
    for i in range(5):
        players.append({
            "name": f"Catcher {i}",
            "positions": [Position.C, Position.UTIL],
            "points": 300 - i * 10,
            "player_type": "hitter",
        })
    # 8 shortstops
    for i in range(8):
        players.append({
            "name": f"Shortstop {i}",
            "positions": [Position.SS, Position.UTIL],
            "points": 350 - i * 10,
            "player_type": "hitter",
        })
    # 15 first basemen (deep position)
    for i in range(15):
        players.append({
            "name": f"First Base {i}",
            "positions": [Position.FIRST, Position.UTIL],
            "points": 380 - i * 8,
            "player_type": "hitter",
        })
    # 25 outfielders (deep position)
    for i in range(25):
        players.append({
            "name": f"Outfielder {i}",
            "positions": [Position.OF, Position.UTIL],
            "points": 370 - i * 6,
            "player_type": "hitter",
        })
    # 50 pitchers
    for i in range(50):
        players.append({
            "name": f"Pitcher {i}",
            "positions": [Position.P],
            "points": 350 - i * 5,
            "player_type": "pitcher",
        })
    return pd.DataFrame(players)


class TestAuctionValues:
    """Tests for the auction value calculation."""

    def test_total_values_sum_to_budget(self, valued_pool):
        """Dollar values should sum to exactly the total league budget."""
        result = calculate_auction_values(valued_pool)
        draftable = result[result["dollar_value"] > 0]
        total = draftable["dollar_value"].sum()
        assert total == LEAGUE.total_budget

    def test_values_are_integers(self, valued_pool):
        """Dollar values should be whole numbers for auction bidding."""
        result = calculate_auction_values(valued_pool)
        draftable = result[result["dollar_value"] > 0]
        assert (draftable["dollar_value"] == draftable["dollar_value"].astype(int)).all()

    def test_higher_points_means_higher_value(self, valued_pool):
        """Players with more points should have higher or equal dollar values."""
        result = calculate_auction_values(valued_pool)
        draftable = result[result["dollar_value"] > 0].head(20)
        # Top players should be in non-increasing value order
        values = draftable["dollar_value"].tolist()
        assert values == sorted(values, reverse=True)

    def test_minimum_dollar_value_is_one(self, valued_pool):
        """Draftable players should have at least $1 value."""
        result = calculate_auction_values(valued_pool)
        draftable = result[result["dollar_value"] > 0]
        assert (draftable["dollar_value"] >= 1).all()

    def test_non_draftable_players_have_zero(self, valued_pool):
        """Players below replacement should have $0 value."""
        result = calculate_auction_values(valued_pool)
        non_draftable = result[result["var"] <= 0]
        assert (non_draftable["dollar_value"] == 0).all()

    def test_var_column_exists(self, valued_pool):
        """Output should include value-above-replacement column."""
        result = calculate_auction_values(valued_pool)
        assert "var" in result.columns

    def test_util_value_column_exists(self, valued_pool):
        """Output should include util_value column."""
        result = calculate_auction_values(valued_pool)
        assert "util_value" in result.columns

    def test_util_value_zero_for_pitchers(self, valued_pool):
        """Pitchers should have util_value == 0."""
        result = calculate_auction_values(valued_pool)
        pitchers = result[result["player_type"] == "pitcher"]
        assert (pitchers["util_value"] == 0).all()

    def test_util_value_leq_dollar_value(self, valued_pool):
        """For hitters with scarce positions, util_value <= dollar_value."""
        result = calculate_auction_values(valued_pool)
        hitters = result[
            (result["player_type"] == "hitter") & (result["dollar_value"] > 0)
        ]
        assert (hitters["util_value"] <= hitters["dollar_value"]).all()

    def test_util_value_positive_for_top_hitters(self, valued_pool):
        """Top hitters should have positive util_value."""
        result = calculate_auction_values(valued_pool)
        top_hitters = result[result["player_type"] == "hitter"].head(10)
        assert (top_hitters["util_value"] > 0).all()

    def test_util_value_ordered_by_points_mixed(self, mixed_position_pool):
        """Util_value should follow points order (position-blind)."""
        result = calculate_auction_values(mixed_position_pool)
        hitters = result[
            (result["player_type"] == "hitter") & (result["util_value"] > 0)
        ].sort_values("points", ascending=False)
        values = hitters["util_value"].tolist()
        # Non-increasing order (ties allowed due to rounding)
        assert values == sorted(values, reverse=True)

    def test_allocation_var_equals_var(self, mixed_position_pool):
        """Under projected-draft, allocation_var should equal var for all players."""
        result = calculate_auction_values(mixed_position_pool)
        draftable = result[result["dollar_value"] > 0]
        assert (draftable["allocation_var"] == draftable["var"]).all()

    def test_position_scarcity_affects_replacement_level(self, mixed_position_pool):
        """Different positions should have different replacement levels, not all Util."""
        result = calculate_auction_values(mixed_position_pool)
        hitters = result[result["player_type"] == "hitter"]
        # With position scarcity, not all hitters should share the same
        # replacement level (which would happen if Util dominated)
        unique_levels = hitters["replacement_level"].nunique()
        assert unique_levels > 1

    def test_allocation_var_column_exists(self, valued_pool):
        """Output should include allocation_var column."""
        result = calculate_auction_values(valued_pool)
        assert "allocation_var" in result.columns

    def test_util_only_not_inflated(self, mixed_position_pool):
        """A Util-only player's dollar_value should be reasonable, not wildly inflated."""
        # Add a Util-only hitter with high points
        util_only = pd.DataFrame([{
            "name": "Util Star",
            "positions": [Position.UTIL],
            "points": 370,
            "player_type": "hitter",
        }])
        pool = pd.concat([mixed_position_pool, util_only], ignore_index=True)
        result = calculate_auction_values(pool)

        player = result[result["name"] == "Util Star"].iloc[0]
        # Util replacement = worst drafted hitter's points.
        # dollar_value and util_value may differ modestly due to different
        # VAR denominators, but should be in the same ballpark.
        assert player["dollar_value"] <= player["util_value"] * 1.5

    def test_scarce_position_gets_premium(self, mixed_position_pool):
        """A catcher should get higher dollar_value than an equally-pointed deep-position player."""
        # Add a catcher and a 1B with the same points
        extra = pd.DataFrame([
            {
                "name": "Equal Catcher",
                "positions": [Position.C, Position.UTIL],
                "points": 320,
                "player_type": "hitter",
            },
            {
                "name": "Equal First Base",
                "positions": [Position.FIRST, Position.UTIL],
                "points": 320,
                "player_type": "hitter",
            },
        ])
        pool = pd.concat([mixed_position_pool, extra], ignore_index=True)
        result = calculate_auction_values(pool)

        catcher = result[result["name"] == "Equal Catcher"].iloc[0]
        first_base = result[result["name"] == "Equal First Base"].iloc[0]
        assert catcher["dollar_value"] > first_base["dollar_value"]

    def test_multi_position_uses_scarcest(self, mixed_position_pool):
        """A multi-position player should use their scarcest position's replacement level."""
        # Add a C/1B eligible player — should get C's (lower) replacement level
        dual = pd.DataFrame([{
            "name": "Dual C/1B",
            "positions": [Position.C, Position.FIRST, Position.UTIL],
            "points": 310,
            "player_type": "hitter",
        }])
        pool = pd.concat([mixed_position_pool, dual], ignore_index=True)
        result = calculate_auction_values(pool)

        player = result[result["name"] == "Dual C/1B"].iloc[0]
        # The replacement level should come from C (scarcest), not 1B or Util
        catchers = result[
            result["positions"].apply(
                lambda ps: Position.C in ps and Position.FIRST not in ps
            )
        ]
        # Player's replacement_level should match catcher replacement level
        catcher_repl = catchers["replacement_level"].iloc[0]
        assert player["replacement_level"] == catcher_repl


    def test_draftable_count_capped_to_roster_spots(self):
        """Draftable players should never exceed roster_size * num_teams."""
        league = LeagueSettings(num_teams=2, roster_size=5, bench=0, bench_hitters=0)
        # Create more players than roster spots (10 spots, 20 players)
        players = []
        for i in range(12):
            players.append({
                "name": f"Hitter {i}",
                "positions": [Position.OF, Position.UTIL],
                "points": 400 - i * 10,
                "player_type": "hitter",
            })
        for i in range(12):
            players.append({
                "name": f"Pitcher {i}",
                "positions": [Position.P],
                "points": 350 - i * 10,
                "player_type": "pitcher",
            })
        df = pd.DataFrame(players)
        result = calculate_auction_values(df, league=league)

        draftable = result[result["dollar_value"] > 0]
        max_draftable = league.roster_size * league.num_teams
        assert len(draftable) <= max_draftable
        assert draftable["dollar_value"].sum() == league.total_budget

    def test_cap_does_not_apply_when_under_limit(self, valued_pool):
        """When fewer players have positive VAR than roster spots, all are kept."""
        # Small pool — 100 players is well under 336 roster spots
        result = calculate_auction_values(valued_pool)
        draftable = result[result["dollar_value"] > 0]
        # All players with positive allocation_var should still be draftable
        assert len(draftable) > 0
        assert draftable["dollar_value"].sum() == LEAGUE.total_budget


class TestFormatPositions:
    """Tests for position formatting."""

    def test_single_position(self):
        """Single position formats correctly."""
        assert format_positions([Position.SS]) == "SS"

    def test_multi_position_excludes_util(self):
        """Util should be excluded when other positions exist."""
        positions = [Position.SECOND, Position.SS, Position.UTIL]
        result = format_positions(positions)
        assert result == "2B,SS"

    def test_util_only(self):
        """Util-only players should show Util."""
        assert format_positions([Position.UTIL]) == "Util"

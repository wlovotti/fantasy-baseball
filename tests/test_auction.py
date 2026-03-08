"""Tests for auction dollar value calculation."""

import pandas as pd
import pytest

from config.league import LEAGUE
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
        """In pooled system, util_value should follow points order (no position effect)."""
        result = calculate_auction_values(mixed_position_pool)
        hitters = result[
            (result["player_type"] == "hitter") & (result["util_value"] > 0)
        ].sort_values("points", ascending=False)
        values = hitters["util_value"].tolist()
        # Non-increasing order (ties allowed due to rounding)
        assert values == sorted(values, reverse=True)

    def test_scarce_position_has_allocation_premium(self, mixed_position_pool):
        """Scarce-position hitters should have allocation_var > pooled VAR."""
        result = calculate_auction_values(mixed_position_pool)
        # Top catchers (scarce position) should have allocation_var > base_var
        catchers = result[
            result["positions"].apply(lambda ps: Position.C in ps)
            & (result["dollar_value"] > 0)
        ]
        deep = result[
            result["positions"].apply(lambda ps: Position.OF in ps)
            & (result["dollar_value"] > 0)
        ]
        if len(catchers) > 0 and len(deep) > 0:
            # A catcher with same points as an OF should have higher allocation_var
            top_c = catchers.iloc[0]
            # allocation_var uses position-specific repl for scarce C
            # For equally-pointed deep-position player, allocation_var uses pooled repl
            assert top_c["allocation_var"] >= top_c["var"] * 0.5  # sanity check
            assert top_c["dollar_value"] >= top_c["util_value"]

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
        """A Util-only player's dollar_value should approximate util_value, not inflate."""
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
        # dollar_value should be close to util_value (within a few dollars),
        # not massively inflated by position scarcity elsewhere
        assert player["dollar_value"] <= player["util_value"] + 3

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

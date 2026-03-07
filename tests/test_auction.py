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


class TestAuctionValues:
    """Tests for the auction value calculation."""

    def test_total_values_sum_to_budget(self, valued_pool):
        """Dollar values should sum to approximately the total league budget."""
        result = calculate_auction_values(valued_pool)
        draftable = result[result["dollar_value"] > 0]
        total = draftable["dollar_value"].sum()
        assert total == pytest.approx(LEAGUE.total_budget, rel=0.01)

    def test_higher_points_means_higher_value(self, valued_pool):
        """Players with more points should have higher dollar values."""
        result = calculate_auction_values(valued_pool)
        draftable = result[result["dollar_value"] > 0].head(20)
        # Top players should be in descending value order
        values = draftable["dollar_value"].tolist()
        assert values == sorted(values, reverse=True)

    def test_minimum_dollar_value_is_one(self, valued_pool):
        """Draftable players should have at least $1 value."""
        result = calculate_auction_values(valued_pool)
        draftable = result[result["dollar_value"] > 0]
        assert (draftable["dollar_value"] >= 1.0).all()

    def test_non_draftable_players_have_zero(self, valued_pool):
        """Players below replacement should have $0 value."""
        result = calculate_auction_values(valued_pool)
        non_draftable = result[result["var"] <= 0]
        assert (non_draftable["dollar_value"] == 0).all()

    def test_var_column_exists(self, valued_pool):
        """Output should include value-above-replacement column."""
        result = calculate_auction_values(valued_pool)
        assert "var" in result.columns


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

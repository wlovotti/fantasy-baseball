"""Tests for fantasy points calculation."""

import pandas as pd
import pytest

from config.scoring import BATTING_SCORING, PITCHING_SCORING
from valuation.points import calculate_hitter_points, calculate_pitcher_points, add_points_column


@pytest.fixture
def sample_hitter():
    """Create a sample hitter row (roughly an MVP-caliber season)."""
    return pd.Series({
        "name": "Test Hitter",
        "player_type": "hitter",
        "single": 100,
        "double": 30,
        "triple": 5,
        "hr": 40,
        "r": 110,
        "rbi": 115,
        "bb": 80,
        "hbp": 5,
        "sb": 15,
        "cs": 3,
        "so": 120,
    })


@pytest.fixture
def sample_pitcher():
    """Create a sample pitcher row (roughly an ace-level season)."""
    return pd.Series({
        "name": "Test Pitcher",
        "player_type": "pitcher",
        "ip": 200,
        "w": 15,
        "l": 7,
        "sv": 0,
        "hld": 0,
        "er": 60,
        "so": 220,
        "h_allowed": 150,
        "bb_allowed": 50,

        "qs": 20,
        "cg": 2,
        "sho": 1,
        "bs": 0,
    })


@pytest.fixture
def sample_reliever():
    """Create a sample elite reliever row."""
    return pd.Series({
        "name": "Test Reliever",
        "player_type": "pitcher",
        "ip": 65,
        "w": 4,
        "l": 3,
        "sv": 35,
        "hld": 0,
        "er": 18,
        "so": 80,
        "h_allowed": 40,
        "bb_allowed": 20,
        "hbp_allowed": 2,
        "qs": 0,
        "cg": 0,
        "sho": 0,
        "bs": 4,
    })


class TestHitterPoints:
    """Tests for hitter points calculation."""

    def test_basic_calculation(self, sample_hitter):
        """Verify points calculation for a sample hitter."""
        points = calculate_hitter_points(sample_hitter)
        # Manual: 100*1 + 30*2 + 5*3 + 40*4 + 110*2 + 115*2
        #       + 80*1 + 5*1 + 15*2.5 + 3*(-1) + 120*(-1)
        expected = (
            100 * 1.0 + 30 * 2.0 + 5 * 3.0 + 40 * 4.0
            + 110 * 2.0 + 115 * 2.0
            + 80 * 1.0 + 5 * 1.0
            + 15 * 2.5 + 3 * (-1.0) + 120 * (-1.0)
        )
        assert points == pytest.approx(expected)

    def test_zero_stats(self):
        """Player with all zeros gets zero points."""
        row = pd.Series({
            "single": 0, "double": 0, "triple": 0, "hr": 0,
            "r": 0, "rbi": 0, "bb": 0, "hbp": 0,
            "sb": 0, "cs": 0, "so": 0,
        })
        assert calculate_hitter_points(row) == 0.0

    def test_missing_columns_treated_as_zero(self):
        """Missing stat columns should be treated as 0."""
        row = pd.Series({"single": 50, "hr": 10})
        points = calculate_hitter_points(row)
        assert points == 50 * 1.0 + 10 * 4.0

    def test_points_are_positive_for_good_hitter(self, sample_hitter):
        """A good hitter should have positive points."""
        assert calculate_hitter_points(sample_hitter) > 0


class TestPitcherPoints:
    """Tests for pitcher points calculation."""

    def test_starter_calculation(self, sample_pitcher):
        """Verify points calculation for a sample starter."""
        points = calculate_pitcher_points(sample_pitcher)
        expected = (
            200 * 1.0 + 15 * 4.5 + 7 * (-2.0) + 0 * 7.0 + 0 * 5.5
            + 60 * (-1.0) + 220 * 1.2 + 150 * (-0.25) + 50 * (-0.35)
            + 20 * 5.0 + 2 * 7.0 + 1 * 10.0 + 0 * (-2.0)
        )
        assert points == pytest.approx(expected)

    def test_reliever_calculation(self, sample_reliever):
        """Verify points for an elite reliever — SV and HLD are valuable."""
        points = calculate_pitcher_points(sample_reliever)
        # Saves worth 7.0 each = 245 from saves alone
        assert points > 0
        # Check saves contribute significantly
        save_contribution = 35 * 7.0
        assert save_contribution == 245.0

    def test_holds_are_valuable(self):
        """Holds at 5.5 should make setup men valuable."""
        holder = pd.Series({
            "ip": 60, "w": 3, "l": 2, "sv": 0, "hld": 25,
            "er": 15, "so": 70, "h_allowed": 40, "bb_allowed": 15,
 "qs": 0, "cg": 0, "sho": 0, "bs": 2,
        })
        points = calculate_pitcher_points(holder)
        assert points > 0
        # 25 holds * 5.5 = 137.5 from holds
        hold_contribution = 25 * 5.5
        assert hold_contribution == 137.5


class TestAddPointsColumn:
    """Tests for the add_points_column function."""

    def test_mixed_dataframe(self, sample_hitter, sample_pitcher):
        """Points column added correctly for mixed hitter/pitcher DataFrame."""
        df = pd.DataFrame([sample_hitter, sample_pitcher])
        result = add_points_column(df)
        assert "points" in result.columns
        assert len(result) == 2
        assert all(result["points"] > 0)

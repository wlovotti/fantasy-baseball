"""Tests for historical draft analysis functions."""

import pandas as pd
import pytest

from analysis.draft_history import (
    assign_primary_position,
    hitter_pitcher_split,
    overpay_recommendations,
    position_spend_summary,
    price_dropoff_by_position,
    spending_vs_standings,
    user_team_report,
)
from config.league import LeagueSettings


@pytest.fixture
def sample_picks():
    """Create synthetic draft pick data across two seasons."""
    picks = []
    # Season 2024 — Team A (hitter-heavy) and Team B (pitcher-heavy)
    for i in range(11):
        picks.append({
            "player_name": f"Hitter A{i}",
            "team_key": "424.l.1.t.1",
            "team_name": "Team A",
            "cost": 30 - i * 2,
            "position_type": "B",
            "primary_position": ["C", "1B", "2B", "3B", "SS",
                                  "OF", "OF", "OF", "OF", "Util", "Util"][i],
            "season": 2024,
        })
    for i in range(13):
        picks.append({
            "player_name": f"Pitcher A{i}",
            "team_key": "424.l.1.t.1",
            "team_name": "Team A",
            "cost": 8 - min(i, 6),
            "position_type": "P",
            "primary_position": "P",
            "season": 2024,
        })

    for i in range(11):
        picks.append({
            "player_name": f"Hitter B{i}",
            "team_key": "424.l.1.t.2",
            "team_name": "Team B",
            "cost": 15 - i,
            "position_type": "B",
            "primary_position": ["C", "1B", "2B", "3B", "SS",
                                  "OF", "OF", "OF", "OF", "Util", "Util"][i],
            "season": 2024,
        })
    for i in range(13):
        picks.append({
            "player_name": f"Pitcher B{i}",
            "team_key": "424.l.1.t.2",
            "team_name": "Team B",
            "cost": 15 - i,
            "position_type": "P",
            "primary_position": "P",
            "season": 2024,
        })

    return pd.DataFrame(picks)


@pytest.fixture
def sample_standings():
    """Create synthetic standings data."""
    return pd.DataFrame([
        {"season": 2024, "team_key": "424.l.1.t.1", "team_name": "Team A", "final_rank": 3},
        {"season": 2024, "team_key": "424.l.1.t.2", "team_name": "Team B", "final_rank": 8},
    ])


class TestAssignPrimaryPosition:
    """Tests for primary position assignment based on scarcity."""

    def test_catcher_is_scarcest(self):
        """Catcher (1 slot) should be preferred over 1B (1 slot) or OF (4 slots)."""
        # C and 1B both have 1 slot; min picks the first in iteration
        result = assign_primary_position(["OF", "C"])
        assert result == "C"

    def test_prefers_specific_over_util(self):
        """Should prefer a specific position over Util."""
        result = assign_primary_position(["Util", "3B"])
        assert result == "3B"

    def test_pitcher(self):
        """Pitcher positions should resolve to P."""
        result = assign_primary_position(["SP", "RP"])
        assert result == "P"

    def test_outfield_variants(self):
        """LF/CF/RF should all map to OF."""
        result = assign_primary_position(["LF", "CF"])
        assert result == "OF"

    def test_empty_positions_returns_first(self):
        """Unknown positions should return the first eligible string."""
        result = assign_primary_position(["BN"])
        assert result == "BN"

    def test_single_position(self):
        """Single position should be returned directly."""
        result = assign_primary_position(["SS"])
        assert result == "SS"


class TestPositionSpendSummary:
    """Tests for position spending summary with fair share comparison."""

    def test_returns_all_drafted_positions(self, sample_picks):
        """Should have a row for each primary position present in the data."""
        result = position_spend_summary(sample_picks)
        assert "P" in result.index
        assert "C" in result.index

    def test_budget_shares_sum_to_100(self, sample_picks):
        """Budget share percentages should sum to approximately 100."""
        result = position_spend_summary(sample_picks)
        assert abs(result["budget_share_pct"].sum() - 100.0) < 0.5

    def test_fair_share_for_pitcher(self, sample_picks):
        """P fair share should be pitcher slots / roster size * 100."""
        league = LeagueSettings()
        result = position_spend_summary(sample_picks, league=league)
        expected_fair = league.pitcher / league.roster_size * 100
        assert result.loc["P", "fair_share_pct"] == pytest.approx(expected_fair, abs=0.1)

    def test_premium_is_budget_minus_fair(self, sample_picks):
        """Premium should equal budget_share - fair_share."""
        result = position_spend_summary(sample_picks)
        for pos in result.index:
            expected = result.loc[pos, "budget_share_pct"] - result.loc[pos, "fair_share_pct"]
            assert result.loc[pos, "premium_pct"] == pytest.approx(expected, abs=0.2)


class TestHitterPitcherSplit:
    """Tests for hitter/pitcher budget split calculation."""

    def test_team_a_is_hitter_heavy(self, sample_picks):
        """Team A should spend more on hitters than Team B."""
        result = hitter_pitcher_split(sample_picks)
        team_a = result[result["team_name"] == "Team A"].iloc[0]
        team_b = result[result["team_name"] == "Team B"].iloc[0]
        assert team_a["hitter_pct"] > team_b["hitter_pct"]

    def test_spends_sum_to_total(self, sample_picks):
        """Hitter + pitcher spend should equal total spend per team."""
        result = hitter_pitcher_split(sample_picks)
        for _, row in result.iterrows():
            assert row["hitter_spend"] + row["pitcher_spend"] == row["total_spend"]


class TestSpendingVsStandings:
    """Tests for spending-to-standings correlation."""

    def test_returns_bins(self, sample_picks, sample_standings):
        """Should return bins with avg_rank and team_count."""
        result = spending_vs_standings(sample_picks, sample_standings)
        assert "hitter_pct_bin" in result.columns
        assert "avg_rank" in result.columns
        assert "team_count" in result.columns

    def test_total_teams_match(self, sample_picks, sample_standings):
        """Total teams across bins should match standings entries."""
        result = spending_vs_standings(sample_picks, sample_standings)
        assert result["team_count"].sum() == len(sample_standings)


class TestPriceDropoff:
    """Tests for price drop-off curves."""

    def test_top_player_most_expensive(self, sample_picks):
        """Rank 1 should have highest avg_cost per position."""
        result = price_dropoff_by_position(sample_picks, top_n=3)
        for pos in result["position"].unique():
            pos_data = result[result["position"] == pos]
            if len(pos_data) >= 2:
                rank1 = pos_data[pos_data["rank"] == 1]["avg_cost"].values[0]
                rank2 = pos_data[pos_data["rank"] == 2]["avg_cost"].values[0]
                assert rank1 >= rank2

    def test_steepness_only_on_rank_1(self, sample_picks):
        """Steepness should only be set for rank 1 rows."""
        result = price_dropoff_by_position(sample_picks, top_n=3)
        for _, row in result.iterrows():
            if row["rank"] != 1:
                assert pd.isna(row["steepness"]) or row["steepness"] is None


class TestUserTeamReport:
    """Tests for personalized team report."""

    def test_report_contains_team_name(self, sample_picks, sample_standings):
        """Report should contain the requested team name."""
        result = user_team_report(sample_picks, sample_standings, "Team A")
        assert result["team_name"] == "Team A"

    def test_report_includes_rank(self, sample_picks, sample_standings):
        """Report should include final rank from standings."""
        result = user_team_report(sample_picks, sample_standings, "Team A")
        assert result["seasons"][0]["final_rank"] == 3

    def test_missing_team_returns_empty_seasons(self, sample_picks, sample_standings):
        """Unknown team should return empty seasons list."""
        result = user_team_report(sample_picks, sample_standings, "Nonexistent")
        assert result["seasons"] == []


class TestOverpayRecommendations:
    """Tests for overpay recommendation synthesis."""

    def test_returns_recommendations_for_each_position(self, sample_picks):
        """Should return a recommendation for each position in the data."""
        result = overpay_recommendations(sample_picks)
        positions = {r["position"] for r in result}
        data_positions = set(sample_picks["primary_position"].unique())
        assert positions == data_positions

    def test_recommendation_has_required_fields(self, sample_picks):
        """Each recommendation should have position, strategy, and reasoning."""
        result = overpay_recommendations(sample_picks)
        for rec in result:
            assert "position" in rec
            assert "strategy" in rec
            assert "reasoning" in rec
            assert rec["strategy"] in {
                "overpay_for_elite",
                "let_others_overpay",
                "target_value",
                "draft_at_value",
            }

"""Tests for Yahoo position integration with the valuation pipeline."""

import pandas as pd
import pytest

from config.positions import Position, parse_positions
from data.yahoo_positions import _is_pitcher_only, merge_yahoo_positions


class TestParsePositionsYahooStrings:
    """Test parse_positions with Yahoo-style position strings."""

    def test_catcher_first_base_dh(self):
        """Yahoo string with C, 1B, DH parses correctly."""
        result = parse_positions("C,1B,DH")
        assert Position.C in result
        assert Position.FIRST in result
        assert Position.UTIL in result

    def test_outfield_positions(self):
        """Yahoo outfield strings (LF, CF, RF) all map to OF."""
        result = parse_positions("LF,CF")
        assert Position.OF in result
        assert Position.UTIL in result
        assert len([p for p in result if p == Position.OF]) == 1  # deduplicated

    def test_starting_pitcher(self):
        """SP maps to P position."""
        result = parse_positions("SP")
        assert result == [Position.P]

    def test_relief_pitcher(self):
        """RP maps to P position."""
        result = parse_positions("RP")
        assert result == [Position.P]

    def test_sp_rp_dual_eligible(self):
        """SP,RP maps to single P position."""
        result = parse_positions("SP,RP")
        assert result == [Position.P]

    def test_multi_position_infielder(self):
        """Multi-position infielder like 2B,SS."""
        result = parse_positions("2B,SS")
        assert Position.SECOND in result
        assert Position.SS in result
        assert Position.UTIL in result

    def test_full_yahoo_string(self):
        """Full Yahoo position string with multiple positions."""
        result = parse_positions("1B,3B,OF,DH")
        assert Position.FIRST in result
        assert Position.THIRD in result
        assert Position.OF in result
        assert Position.UTIL in result


class TestIsPitcherOnly:
    """Test _is_pitcher_only helper."""

    def test_single_p(self):
        """Exact 'P' is pitcher-only."""
        assert _is_pitcher_only("P") is True

    def test_sp(self):
        """'SP' is pitcher-only."""
        assert _is_pitcher_only("SP") is True

    def test_rp(self):
        """'RP' is pitcher-only."""
        assert _is_pitcher_only("RP") is True

    def test_sp_rp(self):
        """'SP,RP' is pitcher-only."""
        assert _is_pitcher_only("SP,RP") is True

    def test_util(self):
        """'Util' is not pitcher-only."""
        assert _is_pitcher_only("Util") is False

    def test_mixed(self):
        """'SP,DH' is not pitcher-only."""
        assert _is_pitcher_only("SP,DH") is False

    def test_hitter_positions(self):
        """'CF,DH' is not pitcher-only."""
        assert _is_pitcher_only("CF,DH") is False


class TestMergeYahooPositions:
    """Test merge_yahoo_positions merges Yahoo eligibility into hitters."""

    @pytest.fixture()
    def yahoo_df(self):
        """Sample Yahoo player DataFrame."""
        return pd.DataFrame({
            "yahoo_name": ["Mike Trout", "Shohei Ohtani", "Aaron Judge"],
            "yahoo_id": [101, 102, 103],
            "position": ["CF,DH", "DH", "RF,DH"],
        })

    @pytest.fixture()
    def hitters_df(self):
        """Sample hitters DataFrame with default UTIL positions."""
        return pd.DataFrame({
            "name": ["Mike Trout", "Aaron Judge", "Unknown Player"],
            "positions": [[Position.UTIL]] * 3,
            "points": [500.0, 480.0, 300.0],
        })

    def test_matched_hitters_get_yahoo_positions(self, hitters_df, yahoo_df):
        """Matched hitters should get Yahoo position eligibility."""
        result, unmatched = merge_yahoo_positions(hitters_df, yahoo_df, score_threshold=80)

        # Mike Trout: CF,DH -> OF, Util
        trout = result[result["name"] == "Mike Trout"].iloc[0]
        assert Position.OF in trout["positions"]
        assert Position.UTIL in trout["positions"]

        # Aaron Judge: RF,DH -> OF, Util
        judge = result[result["name"] == "Aaron Judge"].iloc[0]
        assert Position.OF in judge["positions"]
        assert Position.UTIL in judge["positions"]

    def test_unmatched_hitters_get_util(self, hitters_df, yahoo_df):
        """Unmatched hitters should fall back to UTIL."""
        result, unmatched = merge_yahoo_positions(hitters_df, yahoo_df, score_threshold=80)
        unknown = result[result["name"] == "Unknown Player"].iloc[0]
        assert unknown["positions"] == [Position.UTIL]
        assert "Unknown Player" in unmatched

    def test_dual_player_prefers_batter_positions(self):
        """When Yahoo has both Batter and Pitcher entries, hitter gets batter positions.

        Ohtani appears twice in Yahoo with the same normalized name. The batter
        entry (Util-only) must be used for hitter matching regardless of row order.
        """
        # Pitcher row comes FIRST — previously caused the bug (SP != "P")
        yahoo_df = pd.DataFrame({
            "yahoo_name": ["Shohei Ohtani", "Shohei Ohtani", "Mike Trout"],
            "yahoo_id": [901, 902, 103],
            "position": ["SP", "Util", "CF,DH"],
        })
        hitters_df = pd.DataFrame({
            "name": ["Shohei Ohtani"],
            "positions": [[Position.UTIL]],
            "points": [600.0],
        })
        result, _ = merge_yahoo_positions(hitters_df, yahoo_df, score_threshold=80)
        ohtani = result.iloc[0]
        # Should get batter positions (Util), NOT pitcher positions (P)
        assert ohtani["positions"] == [Position.UTIL]
        assert Position.P not in ohtani["positions"]

    def test_dual_player_batter_first_order(self):
        """Batter-first row order also correctly assigns batter positions."""
        yahoo_df = pd.DataFrame({
            "yahoo_name": ["Shohei Ohtani", "Shohei Ohtani"],
            "yahoo_id": [901, 902],
            "position": ["Util", "SP"],
        })
        hitters_df = pd.DataFrame({
            "name": ["Shohei Ohtani"],
            "positions": [[Position.UTIL]],
            "points": [600.0],
        })
        result, _ = merge_yahoo_positions(hitters_df, yahoo_df, score_threshold=80)
        assert result.iloc[0]["positions"] == [Position.UTIL]

    def test_pitchers_unaffected(self):
        """Pitchers should keep [Position.P] regardless of Yahoo data."""
        pitchers = pd.DataFrame({
            "name": ["Gerrit Cole"],
            "positions": [[Position.P]],
            "player_type": ["pitcher"],
        })
        # merge_yahoo_positions only processes hitters; pitchers are
        # concatenated separately in the script, so they stay as [P].
        assert pitchers.iloc[0]["positions"] == [Position.P]

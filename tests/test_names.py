"""Tests for player name disambiguation."""

from __future__ import annotations

import pandas as pd
import pytest

from valuation.names import disambiguate_player_names


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal player DataFrame from row dicts."""
    return pd.DataFrame(rows)


class TestDisambiguatePlayerNames:
    """Tests for disambiguate_player_names."""

    def test_dual_entry_player_gets_suffixed(self):
        """Players appearing as both hitter and pitcher get (Batter)/(Pitcher)."""
        df = _make_df([
            {"name": "Shohei Ohtani", "player_type": "hitter"},
            {"name": "Shohei Ohtani", "player_type": "pitcher"},
            {"name": "Mike Trout", "player_type": "hitter"},
        ])
        result = disambiguate_player_names(df)
        assert result.iloc[0]["name"] == "Shohei Ohtani (Batter)"
        assert result.iloc[1]["name"] == "Shohei Ohtani (Pitcher)"
        assert result.iloc[2]["name"] == "Mike Trout"

    def test_single_entry_player_unchanged(self):
        """Players with only one entry keep their original name."""
        df = _make_df([
            {"name": "Mike Trout", "player_type": "hitter"},
            {"name": "Gerrit Cole", "player_type": "pitcher"},
        ])
        result = disambiguate_player_names(df)
        assert result.iloc[0]["name"] == "Mike Trout"
        assert result.iloc[1]["name"] == "Gerrit Cole"

    def test_no_mutation_of_input(self):
        """Original DataFrame is not modified."""
        df = _make_df([
            {"name": "Shohei Ohtani", "player_type": "hitter"},
            {"name": "Shohei Ohtani", "player_type": "pitcher"},
        ])
        disambiguate_player_names(df)
        assert df.iloc[0]["name"] == "Shohei Ohtani"
        assert df.iloc[1]["name"] == "Shohei Ohtani"

    def test_empty_dataframe(self):
        """Empty DataFrame passes through without error."""
        df = _make_df([])
        df = pd.DataFrame(columns=["name", "player_type"])
        result = disambiguate_player_names(df)
        assert len(result) == 0

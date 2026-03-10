"""Tests for tier depletion tracking in the draft tracker."""

from __future__ import annotations

import pytest

from draft.api import _build_tier_counts, TIER_LABELS, TIER_POSITIONS
from draft.state import DraftState, PlayerValue


def _make_player(
    name: str,
    positions: list[str],
    original_value: float,
    player_type: str = "hitter",
) -> PlayerValue:
    """Create a PlayerValue for testing."""
    return PlayerValue(
        name=name,
        team="TST",
        positions=positions,
        player_type=player_type,
        points=100.0,
        original_value=original_value,
        current_value=original_value,
    )


def _make_state(players: list[PlayerValue]) -> DraftState:
    """Create a DraftState from a list of players."""
    return DraftState(
        players={p.name: p for p in players},
    )


class TestBasicCounts:
    """Test basic tier counting logic."""

    def test_single_player_in_correct_tier(self):
        """A $25 SS should appear in the $20-29 tier for SS."""
        state = _make_state([_make_player("Player A", ["SS"], 25.0)])
        result = _build_tier_counts(state)
        assert result["positions"]["SS"][1] == 1  # $20-29 tier

    def test_player_in_top_tier(self):
        """A $35 1B should appear in the $30+ tier."""
        state = _make_state([_make_player("Player B", ["1B"], 35.0)])
        result = _build_tier_counts(state)
        assert result["positions"]["1B"][0] == 1  # $30+ tier

    def test_player_in_bottom_tier(self):
        """A $3 OF should appear in the $1-4 tier."""
        state = _make_state([_make_player("Player C", ["OF"], 3.0)])
        result = _build_tier_counts(state)
        assert result["positions"]["OF"][4] == 1  # $1-4 tier

    def test_multiple_players_same_tier(self):
        """Multiple players at the same position/tier accumulate."""
        state = _make_state([
            _make_player("P1", ["C"], 12.0),
            _make_player("P2", ["C"], 15.0),
            _make_player("P3", ["C"], 18.0),
        ])
        result = _build_tier_counts(state)
        assert result["positions"]["C"][2] == 3  # $10-19 tier

    def test_tier_labels_returned(self):
        """Result includes correct tier labels."""
        state = _make_state([])
        result = _build_tier_counts(state)
        assert result["tiers"] == TIER_LABELS

    def test_all_positions_present(self):
        """All TIER_POSITIONS are present in output even with no players."""
        state = _make_state([])
        result = _build_tier_counts(state)
        for pos in TIER_POSITIONS:
            assert pos in result["positions"]
            assert result["positions"][pos] == [0, 0, 0, 0, 0]


class TestMultiPosition:
    """Test multi-position player counting."""

    def test_dual_position_counts_in_both(self):
        """A SS/2B player counts in both SS and 2B rows."""
        state = _make_state([_make_player("Dual", ["SS", "2B"], 20.0)])
        result = _build_tier_counts(state)
        assert result["positions"]["SS"][1] == 1
        assert result["positions"]["2B"][1] == 1

    def test_triple_position(self):
        """A 1B/3B/OF player counts in all three."""
        state = _make_state([_make_player("Triple", ["1B", "3B", "OF"], 10.0)])
        result = _build_tier_counts(state)
        assert result["positions"]["1B"][2] == 1
        assert result["positions"]["3B"][2] == 1
        assert result["positions"]["OF"][2] == 1


class TestPitcherPooling:
    """Test that SP and RP both count under P."""

    def test_sp_counts_as_p(self):
        """An SP player counts under P."""
        state = _make_state([
            _make_player("Starter", ["SP"], 15.0, player_type="pitcher"),
        ])
        result = _build_tier_counts(state)
        assert result["positions"]["P"][2] == 1

    def test_rp_counts_as_p(self):
        """An RP player counts under P."""
        state = _make_state([
            _make_player("Reliever", ["RP"], 8.0, player_type="pitcher"),
        ])
        result = _build_tier_counts(state)
        assert result["positions"]["P"][3] == 1

    def test_sp_rp_counts_once(self):
        """An SP/RP player counts as P only once."""
        state = _make_state([
            _make_player("SwingMan", ["SP", "RP"], 20.0, player_type="pitcher"),
        ])
        result = _build_tier_counts(state)
        assert result["positions"]["P"][1] == 1


class TestExclusions:
    """Test that Util-only and sub-$1 players are excluded."""

    def test_util_only_excluded(self):
        """A Util-only player doesn't appear in any position row."""
        state = _make_state([_make_player("UtilGuy", ["Util"], 10.0)])
        result = _build_tier_counts(state)
        for pos in TIER_POSITIONS:
            assert sum(result["positions"][pos]) == 0

    def test_util_with_real_position_counted(self):
        """A player with Util and a real position counts in the real position only."""
        state = _make_state([_make_player("Hybrid", ["1B", "Util"], 10.0)])
        result = _build_tier_counts(state)
        assert result["positions"]["1B"][2] == 1

    def test_below_one_dollar_excluded(self):
        """Players with original_value < 1 are skipped."""
        state = _make_state([_make_player("Filler", ["SS"], 0.5)])
        result = _build_tier_counts(state)
        assert sum(result["positions"]["SS"]) == 0

    def test_zero_value_excluded(self):
        """Players with original_value of 0 are skipped."""
        state = _make_state([_make_player("Zero", ["OF"], 0.0)])
        result = _build_tier_counts(state)
        assert sum(result["positions"]["OF"]) == 0


class TestAfterPick:
    """Test that counts update after players are removed."""

    def test_count_decreases_after_pick(self):
        """Removing a player from state decreases the count."""
        players = [
            _make_player("P1", ["SS"], 25.0),
            _make_player("P2", ["SS"], 22.0),
        ]
        state = _make_state(players)
        assert _build_tier_counts(state)["positions"]["SS"][1] == 2

        # Simulate drafting P1 (remove from pool)
        del state.players["P1"]
        assert _build_tier_counts(state)["positions"]["SS"][1] == 1


class TestEmptyPool:
    """Test with no players."""

    def test_all_zeros(self):
        """Empty pool gives all-zero counts."""
        state = _make_state([])
        result = _build_tier_counts(state)
        for pos in TIER_POSITIONS:
            assert result["positions"][pos] == [0, 0, 0, 0, 0]


class TestIntegration:
    """Test integration with _state_summary."""

    def test_state_summary_includes_tier_counts(self):
        """_state_summary output includes tier_counts key."""
        from draft.api import _state_summary

        state = _make_state([_make_player("Star", ["SS"], 30.0)])
        summary = _state_summary(state)
        assert "tier_counts" in summary
        assert summary["tier_counts"]["tiers"] == TIER_LABELS
        assert summary["tier_counts"]["positions"]["SS"][0] == 1

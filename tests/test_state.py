"""Tests for draft state model and persistence."""

import json
import tempfile
from pathlib import Path

import pytest

from draft.state import (
    DraftState,
    PlayerValue,
    TeamState,
    DraftPick,
    save_state,
    load_state,
)
from draft.tracker import record_pick, undo_last_pick


@pytest.fixture
def draft_state():
    """Create a minimal draft state for testing."""
    players = {
        "Aaron Judge": PlayerValue(
            name="Aaron Judge",
            team="NYY",
            positions=["OF"],
            player_type="hitter",
            points=500,
            original_value=45.0,
            current_value=45.0,
            var=200,
        ),
        "Shohei Ohtani": PlayerValue(
            name="Shohei Ohtani",
            team="LAD",
            positions=["OF"],
            player_type="hitter",
            points=550,
            original_value=50.0,
            current_value=50.0,
            var=250,
        ),
        "Gerrit Cole": PlayerValue(
            name="Gerrit Cole",
            team="NYY",
            positions=["P"],
            player_type="pitcher",
            points=400,
            original_value=30.0,
            current_value=30.0,
            var=150,
        ),
    }
    teams = {
        1: TeamState(team_id=1, name="Team 1", budget=260),
        2: TeamState(team_id=2, name="Team 2", budget=260),
    }
    return DraftState(
        players=players,
        teams=teams,
        total_roster_slots=24,
        budget_per_team=260,
    )


class TestDraftState:
    """Tests for the DraftState model."""

    def test_initial_inflation_factor(self, draft_state):
        """Initial inflation factor should reflect full budget vs total value."""
        factor = draft_state.inflation_factor
        assert factor > 0

    def test_team_budget_tracking(self, draft_state):
        """Team budget should track spending correctly."""
        team = draft_state.teams[1]
        assert team.remaining_budget == 260
        assert team.spent == 0
        assert team.roster_size == 0


class TestRecordPick:
    """Tests for recording draft picks."""

    def test_basic_pick(self, draft_state):
        """Recording a pick should remove player and update team."""
        state = record_pick(draft_state, "Aaron Judge", 50, 1)
        assert "Aaron Judge" not in state.players
        assert state.teams[1].remaining_budget == 210
        assert state.teams[1].roster_size == 1
        assert len(state.draft_log) == 1

    def test_values_recalculate_after_pick(self, draft_state):
        """Remaining player values should change after a pick."""
        original_cole = draft_state.players["Gerrit Cole"].current_value
        state = record_pick(draft_state, "Aaron Judge", 50, 1)
        # Values should change (likely increase due to inflation)
        new_cole = state.players["Gerrit Cole"].current_value
        assert new_cole != original_cole

    def test_invalid_player_raises(self, draft_state):
        """Drafting a non-existent player should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            record_pick(draft_state, "Fake Player", 10, 1)

    def test_over_budget_raises(self, draft_state):
        """Spending more than remaining budget should raise ValueError."""
        with pytest.raises(ValueError, match="remaining"):
            record_pick(draft_state, "Aaron Judge", 300, 1)

    def test_invalid_team_raises(self, draft_state):
        """Drafting to a non-existent team should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            record_pick(draft_state, "Aaron Judge", 10, 99)


class TestUndo:
    """Tests for undo functionality."""

    def test_undo_restores_player(self, draft_state):
        """Undoing a pick should restore the player to the pool."""
        state = record_pick(draft_state, "Aaron Judge", 50, 1)
        assert "Aaron Judge" not in state.players
        state = undo_last_pick(state)
        assert "Aaron Judge" in state.players

    def test_undo_restores_budget(self, draft_state):
        """Undoing a pick should restore the team's budget."""
        state = record_pick(draft_state, "Aaron Judge", 50, 1)
        assert state.teams[1].remaining_budget == 210
        state = undo_last_pick(state)
        assert state.teams[1].remaining_budget == 260

    def test_undo_with_no_picks_raises(self, draft_state):
        """Undoing when no picks have been made should raise ValueError."""
        with pytest.raises(ValueError, match="No picks"):
            undo_last_pick(draft_state)


class TestPersistence:
    """Tests for state save/load."""

    def test_save_and_load_roundtrip(self, draft_state):
        """State should survive a save/load cycle."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            save_state(draft_state, path)
            loaded = load_state(path)
            assert len(loaded.players) == len(draft_state.players)
            assert len(loaded.teams) == len(draft_state.teams)
            assert "Aaron Judge" in loaded.players
        finally:
            Path(path).unlink(missing_ok=True)

    def test_save_after_picks(self, draft_state):
        """State with picks should persist correctly."""
        state = record_pick(draft_state, "Aaron Judge", 50, 1)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            save_state(state, path)
            loaded = load_state(path)
            assert "Aaron Judge" not in loaded.players
            assert loaded.teams[1].roster_size == 1
            assert len(loaded.draft_log) == 1
        finally:
            Path(path).unlink(missing_ok=True)

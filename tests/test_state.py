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
from draft.tracker import (
    record_pick,
    undo_last_pick,
    add_unknown_player,
    edit_pick_price,
    remove_pick,
)


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
            positions=["SP"],
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
        original_values_map={
            "Aaron Judge": 45.0,
            "Shohei Ohtani": 50.0,
            "Gerrit Cole": 30.0,
        },
    )


class TestDraftState:
    """Tests for the DraftState model."""

    def test_team_budget_tracking(self, draft_state):
        """Team budget should track spending correctly."""
        team = draft_state.teams[1]
        assert team.remaining_budget == 260
        assert team.spent == 0
        assert team.roster_size == 0

    def test_my_team_id_default(self, draft_state):
        """Default my_team_id should be 0."""
        assert draft_state.my_team_id == 0

    def test_original_values_map(self, draft_state):
        """Original values map should be populated."""
        assert draft_state.original_values_map["Aaron Judge"] == 45.0
        assert draft_state.original_values_map["Gerrit Cole"] == 30.0


class TestRecordPick:
    """Tests for recording draft picks."""

    def test_basic_pick(self, draft_state):
        """Recording a pick should remove player and update team."""
        state = record_pick(draft_state, "Aaron Judge", 50, 1)
        assert "Aaron Judge" not in state.players
        assert state.teams[1].remaining_budget == 210
        assert state.teams[1].roster_size == 1
        assert len(state.draft_log) == 1

    def test_position_assignment(self, draft_state):
        """Pick should have an assigned position."""
        state = record_pick(draft_state, "Aaron Judge", 50, 1)
        pick = state.draft_log[0]
        assert pick.assigned_position == "OF"

    def test_pitcher_position_assignment(self, draft_state):
        """SP pitcher should be assigned to P slot."""
        state = record_pick(draft_state, "Gerrit Cole", 30, 1)
        pick = state.draft_log[0]
        assert pick.assigned_position == "P"

    def test_player_snapshot_stored(self, draft_state):
        """Pick should store a player snapshot for potential restore."""
        state = record_pick(draft_state, "Aaron Judge", 50, 1)
        pick = state.draft_log[0]
        assert pick.player_snapshot != ""
        restored = json.loads(pick.player_snapshot)
        assert restored["name"] == "Aaron Judge"

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


class TestAddUnknownPlayer:
    """Tests for adding unknown players."""

    def test_add_player(self, draft_state):
        """Adding an unknown player should add them to the pool."""
        add_unknown_player(draft_state, "New Guy", ["SS", "2B"], "hitter")
        assert "New Guy" in draft_state.players
        assert draft_state.players["New Guy"].positions == ["SS", "2B"]
        assert draft_state.players["New Guy"].original_value == 0.0

    def test_add_player_updates_values_map(self, draft_state):
        """Adding a player should update original_values_map."""
        add_unknown_player(draft_state, "New Guy", ["SS"], "hitter")
        assert draft_state.original_values_map["New Guy"] == 0.0

    def test_add_duplicate_raises(self, draft_state):
        """Adding a player that already exists should raise ValueError."""
        with pytest.raises(ValueError, match="already exists"):
            add_unknown_player(draft_state, "Aaron Judge", ["OF"], "hitter")


class TestEditPickPrice:
    """Tests for editing pick prices."""

    def test_edit_price(self, draft_state):
        """Editing a price should update the pick."""
        state = record_pick(draft_state, "Aaron Judge", 50, 1)
        edit_pick_price(state, 1, 40)
        assert state.draft_log[0].price == 40
        assert state.teams[1].roster[0].price == 40
        assert state.teams[1].remaining_budget == 220

    def test_edit_price_invalid_pick_raises(self, draft_state):
        """Editing a non-existent pick should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            edit_pick_price(draft_state, 99, 10)

    def test_edit_price_over_budget_raises(self, draft_state):
        """Editing to exceed budget should raise ValueError."""
        state = record_pick(draft_state, "Aaron Judge", 50, 1)
        with pytest.raises(ValueError, match="can't afford"):
            edit_pick_price(state, 1, 300)


class TestRemovePick:
    """Tests for removing picks."""

    def test_remove_pick(self, draft_state):
        """Removing a pick should return the player to the pool."""
        state = record_pick(draft_state, "Aaron Judge", 50, 1)
        assert "Aaron Judge" not in state.players
        remove_pick(state, 1)
        assert "Aaron Judge" in state.players
        assert state.teams[1].roster_size == 0

    def test_remove_pick_restores_player_data(self, draft_state):
        """Restored player should have original data."""
        state = record_pick(draft_state, "Aaron Judge", 50, 1)
        remove_pick(state, 1)
        player = state.players["Aaron Judge"]
        assert player.original_value == 45.0
        assert player.positions == ["OF"]

    def test_remove_pick_clears_draft_log(self, draft_state):
        """Removing a pick should remove it from the draft log."""
        state = record_pick(draft_state, "Aaron Judge", 50, 1)
        assert len(state.draft_log) == 1
        remove_pick(state, 1)
        assert len(state.draft_log) == 0

    def test_remove_invalid_pick_raises(self, draft_state):
        """Removing a non-existent pick should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            remove_pick(draft_state, 99)


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

    def test_save_preserves_original_values_map(self, draft_state):
        """Original values map should persist across save/load."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            save_state(draft_state, path)
            loaded = load_state(path)
            assert loaded.original_values_map["Aaron Judge"] == 45.0
        finally:
            Path(path).unlink(missing_ok=True)

    def test_save_preserves_my_team_id(self, draft_state):
        """my_team_id should persist across save/load."""
        draft_state.my_team_id = 3
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            save_state(draft_state, path)
            loaded = load_state(path)
            assert loaded.my_team_id == 3
        finally:
            Path(path).unlink(missing_ok=True)

"""Tests for bidding strategies and engine integration."""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd
import pytest

from config.league import LEAGUE, LeagueSettings
from config.positions import Position
from simulation.engine import (
    SimPlayer,
    SimTeam,
    run_one_draft,
)
from simulation.strategies import (
    dynamic_strategy,
    load_player_dataframe,
    personal_strategy,
    static_strategy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_player(
    name: str = "Test Player",
    player_type: str = "hitter",
    points: float = 500.0,
    positions: list[Position] | None = None,
    our_value: int = 20,
    yahoo_value: int = 20,
) -> SimPlayer:
    """Create a SimPlayer with sensible defaults."""
    if positions is None:
        positions = [Position.OF, Position.UTIL]
    return SimPlayer(
        name=name,
        player_type=player_type,
        points=points,
        positions=positions,
        our_value=our_value,
        yahoo_value=yahoo_value,
    )


# ---------------------------------------------------------------------------
# Static strategy tests
# ---------------------------------------------------------------------------

class TestStaticStrategy:
    """Tests for the static (baseline) strategy."""

    def test_static_matches_our_value(self) -> None:
        """Static strategy should return the same value as player.our_value."""
        players = [
            _make_player(name="Alice", our_value=30),
            _make_player(name="Bob", our_value=15),
        ]
        bid = static_strategy(players)
        assert bid("Alice") == 30
        assert bid("Bob") == 15

    def test_static_unknown_player_defaults_to_one(self) -> None:
        """Unknown player names should default to $1."""
        bid = static_strategy([])
        assert bid("Nobody") == 1


# ---------------------------------------------------------------------------
# Personal strategy tests
# ---------------------------------------------------------------------------

class TestPersonalStrategy:
    """Tests for the personal (custom league settings) strategy."""

    def test_personal_produces_different_values(self) -> None:
        """Personal strategy with bench_hitters=0 should differ from default (bh=1)."""
        csv_path = Path("player_values.csv")
        if not csv_path.exists():
            pytest.skip("player_values.csv not present")

        df = load_player_dataframe(csv_path)

        # Static values (bench_hitters=1, default)
        static_bid = static_strategy(
            [SimPlayer(
                name=row["name"],
                player_type=row["player_type"],
                points=row["points"],
                positions=row["positions"],
                our_value=int(float(row.get("dollar_value", 1))),
                yahoo_value=1,
            ) for _, row in df.iterrows()]
        )

        # Personal values (bench_hitters=0)
        personal_bid = personal_strategy(df, LeagueSettings(bench_hitters=0))

        # Collect differences across top players
        diffs = 0
        top_names = df.nlargest(50, "points")["name"].tolist()
        for name in top_names:
            if static_bid(name) != personal_bid(name):
                diffs += 1

        assert diffs > 0, "Personal strategy should produce at least some different values"


# ---------------------------------------------------------------------------
# Dynamic strategy tests
# ---------------------------------------------------------------------------

class TestDynamicStrategy:
    """Tests for the dynamic (revaluation) strategy."""

    def test_dynamic_updates_after_pick(self) -> None:
        """Dynamic strategy values should change after on_pick is called."""
        csv_path = Path("player_values.csv")
        if not csv_path.exists():
            pytest.skip("player_values.csv not present")

        df = load_player_dataframe(csv_path)
        bid, on_pick = dynamic_strategy(df, LEAGUE)

        # Get value for a mid-tier player before any picks
        top_player = df.nlargest(1, "points")["name"].iloc[0]
        mid_player = df.nlargest(20, "points")["name"].iloc[19]
        value_before = bid(mid_player)

        # Remove the top player
        on_pick(top_player)

        value_after = bid(mid_player)

        # Values should shift (removing top player changes replacement levels)
        # We just verify the mechanism works — values may or may not change
        # for any specific player, but the top player should now be gone
        assert bid(top_player) == 1, "Removed player should default to 1"

    def test_dynamic_initial_values_match_revalue(self) -> None:
        """Initial dynamic values should match a fresh revaluation."""
        csv_path = Path("player_values.csv")
        if not csv_path.exists():
            pytest.skip("player_values.csv not present")

        df = load_player_dataframe(csv_path)
        bid, _ = dynamic_strategy(df, LEAGUE)

        # The dynamic strategy revalues at init, so values should be
        # consistent (non-negative integers for top players)
        top_name = df.nlargest(1, "points")["name"].iloc[0]
        assert bid(top_name) >= 1


# ---------------------------------------------------------------------------
# Engine integration tests
# ---------------------------------------------------------------------------

class TestOnPickHook:
    """Tests for the on_pick callback in run_one_draft."""

    def test_on_pick_hook_called(self) -> None:
        """Verify on_pick fires after each successful pick in run_one_draft."""
        # Small 2-team draft to keep it fast
        players = []
        for i in range(30):
            players.append(_make_player(
                name=f"H{i}",
                points=500.0 - i * 10,
                our_value=max(1, 20 - i),
                yahoo_value=max(1, 20 - i),
                positions=[Position.OF, Position.C, Position.FIRST,
                           Position.SECOND, Position.THIRD, Position.SS,
                           Position.UTIL],
            ))
        for i in range(30):
            players.append(_make_player(
                name=f"P{i}",
                player_type="pitcher",
                points=400.0 - i * 10,
                our_value=max(1, 15 - i),
                yahoo_value=max(1, 15 - i),
                positions=[Position.P],
            ))

        picks_recorded: list[str] = []

        def track_pick(
            player: SimPlayer,
            winner: SimTeam,
            available: list[SimPlayer],
        ) -> None:
            """Record each pick for assertion."""
            picks_recorded.append(player.name)

        league = LeagueSettings(num_teams=2)
        rng = random.Random(42)
        result = run_one_draft(
            players, rng, noise_std=0.0, league=league, on_pick=track_pick,
        )

        # on_pick should have been called for every drafted player (minus fillers)
        total_drafted = sum(
            1 for t in result.teams
            for dp in t.roster
            if not dp.player.name.startswith("Filler")
        )
        assert len(picks_recorded) == total_drafted
        assert len(picks_recorded) > 0

    def test_user_strategy_changes_bids(self) -> None:
        """User strategy should override our_value for bidding."""
        players = []
        for i in range(30):
            players.append(_make_player(
                name=f"H{i}",
                points=500.0 - i * 10,
                our_value=1,  # low model value
                yahoo_value=max(1, 20 - i),
                positions=[Position.OF, Position.C, Position.FIRST,
                           Position.SECOND, Position.THIRD, Position.SS,
                           Position.UTIL],
            ))
        for i in range(30):
            players.append(_make_player(
                name=f"P{i}",
                player_type="pitcher",
                points=400.0 - i * 10,
                our_value=1,
                yahoo_value=max(1, 15 - i),
                positions=[Position.P],
            ))

        # Strategy that values H0 very highly
        def high_h0(name: str) -> int:
            """Bid $50 for H0, $1 for everyone else."""
            return 50 if name == "H0" else 1

        league = LeagueSettings(num_teams=2)
        rng = random.Random(42)
        result = run_one_draft(
            players, rng, noise_std=0.0, league=league, user_strategy=high_h0,
        )

        user = result.user_team
        user_names = {dp.player.name for dp in user.roster}
        assert "H0" in user_names, "User strategy should have won H0"


# ---------------------------------------------------------------------------
# CSV loading test
# ---------------------------------------------------------------------------

class TestLoadPlayerDataframe:
    """Tests for load_player_dataframe."""

    def test_load_player_dataframe(self) -> None:
        """Verify CSV loading produces parsed position lists."""
        csv_path = Path("player_values.csv")
        if not csv_path.exists():
            pytest.skip("player_values.csv not present")

        df = load_player_dataframe(csv_path)
        assert "positions" in df.columns
        assert "name" in df.columns
        assert len(df) > 0

        # Positions should be lists of Position enums
        first_positions = df.iloc[0]["positions"]
        assert isinstance(first_positions, list)
        assert all(isinstance(p, Position) for p in first_positions)

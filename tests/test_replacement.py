"""Tests for replacement level calculation."""

import pandas as pd
import pytest

from config.league import LeagueSettings
from config.positions import Position
from valuation.replacement import (
    _assign_primary_position,
    _build_drafted_pool,
    _final_replacement_levels,
    _first_pass_replacement,
    calculate_replacement_levels,
)


def _make_league(**kwargs):
    """Create a small league for testing.

    Defaults: 2 teams, 10 roster, 1C/1B/1OF/1Util/1P per team, bench=1,
    bench_hitters=0. Override any field via kwargs.
    """
    defaults = dict(
        num_teams=2,
        roster_size=5,
        catcher=1,
        first_base=1,
        second_base=0,
        third_base=0,
        shortstop=0,
        outfield=1,
        utility=1,
        pitcher=1,
        bench=0,
        bench_hitters=0,
    )
    defaults.update(kwargs)
    return LeagueSettings(**defaults)


def _make_players(groups):
    """Create a player DataFrame from a list of (name_prefix, positions, base_pts, count, step, player_type) tuples."""
    players = []
    for name_prefix, positions, base_pts, count, step, player_type in groups:
        for i in range(count):
            players.append({
                "name": f"{name_prefix} {i}",
                "positions": positions,
                "points": base_pts - i * step,
                "player_type": player_type,
            })
    return pd.DataFrame(players)


class TestFirstPassReplacement:
    """Tests for first-pass (independent) replacement levels."""

    def test_nth_best_at_position(self):
        """First-pass replacement should be the Nth-best eligible player at each position."""
        df = _make_players([
            ("C", [Position.C, Position.UTIL], 300, 5, 10, "hitter"),
            ("OF", [Position.OF, Position.UTIL], 350, 8, 10, "hitter"),
            ("P", [Position.P], 280, 5, 10, "pitcher"),
        ])
        league = _make_league(num_teams=2, catcher=1, outfield=2, pitcher=1)
        levels = _first_pass_replacement(df, league)

        # 2nd-best C (N=2): 300, 290 → replacement = 290
        assert levels[Position.C] == 290
        # 4th-best OF (N=4): 350, 340, 330, 320 → replacement = 320
        assert levels[Position.OF] == 320
        # 2nd-best P (N=2): 280, 270 → replacement = 270
        assert levels[Position.P] == 270

    def test_fewer_players_than_slots(self):
        """When fewer players exist than slots, use worst available."""
        df = _make_players([
            ("C", [Position.C, Position.UTIL], 300, 1, 10, "hitter"),
            ("OF", [Position.OF, Position.UTIL], 350, 5, 10, "hitter"),
            ("P", [Position.P], 280, 3, 10, "pitcher"),
        ])
        # Need 4 catchers but only 1 exists
        league = _make_league(num_teams=2, catcher=2, outfield=1, pitcher=1)
        levels = _first_pass_replacement(df, league)

        assert levels[Position.C] == 300  # Only 1 catcher, that's the worst

    def test_excludes_util(self):
        """First-pass replacement should not include Util as a position."""
        df = _make_players([
            ("C", [Position.C, Position.UTIL], 300, 3, 10, "hitter"),
            ("P", [Position.P], 280, 3, 10, "pitcher"),
        ])
        league = _make_league(num_teams=1, catcher=1, pitcher=1)
        levels = _first_pass_replacement(df, league)

        assert Position.UTIL not in levels

    def test_multi_position_counted_at_all(self):
        """A C/1B player should count toward both C and 1B first-pass levels."""
        df = _make_players([
            ("C", [Position.C, Position.UTIL], 300, 2, 10, "hitter"),
            ("C/1B", [Position.C, Position.FIRST, Position.UTIL], 295, 1, 0, "hitter"),
            ("1B", [Position.FIRST, Position.UTIL], 400, 3, 10, "hitter"),
            ("P", [Position.P], 280, 2, 10, "pitcher"),
        ])
        league = _make_league(num_teams=1, catcher=1, first_base=1, pitcher=1)
        levels = _first_pass_replacement(df, league)

        # C-eligible: 300, 295, 290 → 1st-best = 300
        assert levels[Position.C] == 300
        # 1B-eligible: 400, 395 (wait, 295 is C/1B), 390, 380 → 1st-best = 400
        # Actually: 1B-eligible = [400, 390, 380, 295] → sorted desc → 1st = 400
        assert levels[Position.FIRST] == 400


class TestPrimaryPositionAssignment:
    """Tests for multi-position player assignment to primary position."""

    def test_assigns_to_scarcest_position(self):
        """Player should be assigned to position with lowest first-pass replacement."""
        first_pass = {Position.C: 200, Position.FIRST: 350, Position.OF: 300}
        positions = [Position.C, Position.FIRST, Position.UTIL]

        result = _assign_primary_position(positions, first_pass)
        assert result == Position.C  # C has lowest replacement (200)

    def test_util_only_returns_none(self):
        """Util-only players should return None (no specific position)."""
        first_pass = {Position.C: 200}
        positions = [Position.UTIL]

        result = _assign_primary_position(positions, first_pass)
        assert result is None

    def test_pitcher_assigned_to_p(self):
        """Pitchers (only P eligible) should be assigned to P."""
        first_pass = {Position.P: 150}
        positions = [Position.P]

        result = _assign_primary_position(positions, first_pass)
        assert result == Position.P

    def test_single_position_hitter(self):
        """Single-position hitter assigned to that position."""
        first_pass = {Position.SS: 250, Position.OF: 300}
        positions = [Position.SS, Position.UTIL]

        result = _assign_primary_position(positions, first_pass)
        assert result == Position.SS


class TestDraftedPoolConstruction:
    """Tests for building the projected drafted pool."""

    def test_pool_size_matches_roster_slots(self):
        """Drafted pool should have exactly roster_size × num_teams players."""
        df = _make_players([
            ("C", [Position.C, Position.UTIL], 300, 5, 10, "hitter"),
            ("1B", [Position.FIRST, Position.UTIL], 350, 5, 10, "hitter"),
            ("OF", [Position.OF, Position.UTIL], 320, 10, 5, "hitter"),
            ("P", [Position.P], 280, 10, 5, "pitcher"),
        ])
        league = _make_league(
            num_teams=2, roster_size=10,
            catcher=1, first_base=1, outfield=2, utility=1,
            pitcher=3, bench=2, bench_hitters=1,
        )
        first_pass = _first_pass_replacement(df, league)
        pool = _build_drafted_pool(df, league, first_pass)

        expected_size = league.roster_size * league.num_teams
        assert len(pool) == expected_size

    def test_respects_position_slots(self):
        """Starter slots should be filled by top players at each position."""
        df = _make_players([
            ("C", [Position.C, Position.UTIL], 300, 5, 10, "hitter"),
            ("OF", [Position.OF, Position.UTIL], 350, 10, 10, "hitter"),
            ("P", [Position.P], 280, 8, 10, "pitcher"),
        ])
        league = _make_league(
            num_teams=2, roster_size=6,
            catcher=1, first_base=0, outfield=1, utility=1,
            pitcher=1, bench=2, bench_hitters=1,
        )
        first_pass = _first_pass_replacement(df, league)
        pool = _build_drafted_pool(df, league, first_pass)

        # Top 2 catchers should be in the pool (2 C slots)
        catcher_names = pool[
            pool["positions"].apply(lambda ps: Position.C in ps)
        ]["name"].tolist()
        assert "C 0" in catcher_names
        assert "C 1" in catcher_names

    def test_util_only_hitters_fill_util_slots(self):
        """Util-only hitters should be drafted into Util/bench slots."""
        df = _make_players([
            ("C", [Position.C, Position.UTIL], 300, 3, 10, "hitter"),
            ("Util", [Position.UTIL], 350, 3, 10, "hitter"),
            ("P", [Position.P], 280, 5, 10, "pitcher"),
        ])
        league = _make_league(
            num_teams=1, roster_size=5,
            catcher=1, first_base=0, outfield=0, utility=2,
            pitcher=2, bench=0, bench_hitters=0,
        )
        first_pass = _first_pass_replacement(df, league)
        pool = _build_drafted_pool(df, league, first_pass)

        # The top Util-only hitter (350 pts) should be drafted
        assert "Util 0" in pool["name"].tolist()

    def test_fewer_players_than_pool_size(self):
        """When fewer players exist than pool slots, draft all of them."""
        df = _make_players([
            ("C", [Position.C, Position.UTIL], 300, 2, 10, "hitter"),
            ("P", [Position.P], 280, 2, 10, "pitcher"),
        ])
        league = _make_league(
            num_teams=2, roster_size=10,
            catcher=1, pitcher=1, bench=0, bench_hitters=0,
        )
        first_pass = _first_pass_replacement(df, league)
        pool = _build_drafted_pool(df, league, first_pass)

        # Only 4 players exist, pool can't exceed that
        assert len(pool) == 4


class TestFinalReplacementLevels:
    """Tests for deriving final replacement levels from the drafted pool."""

    def test_multi_position_counted_at_primary_only(self):
        """A drafted C/1B player should only count toward their primary position."""
        df = _make_players([
            ("C/1B", [Position.C, Position.FIRST, Position.UTIL], 250, 1, 0, "hitter"),
            ("OF", [Position.OF, Position.UTIL], 350, 5, 10, "hitter"),
            ("P", [Position.P], 280, 3, 10, "pitcher"),
        ])
        league = _make_league(
            num_teams=1, roster_size=5,
            catcher=1, first_base=0, outfield=2, utility=0,
            pitcher=2, bench=0, bench_hitters=0,
        )
        first_pass = _first_pass_replacement(df, league)
        pool = _build_drafted_pool(df, league, first_pass)

        levels = _final_replacement_levels(pool)

        # C/1B player assigned to C (scarcest), so counts toward C only
        assert levels[Position.C] <= 250
        # No one assigned to 1B, so 1B replacement = 0
        assert levels[Position.FIRST] == 0.0

    def test_final_levels_leq_first_pass(self):
        """Final replacement levels should be <= first-pass levels.

        Util/bench expand effective demand at each position, so the worst
        drafted player eligible at a position may be a Util/bench player
        with lower points than the Nth-best starter.
        """
        df = _make_players([
            ("C", [Position.C, Position.UTIL], 300, 5, 10, "hitter"),
            ("1B", [Position.FIRST, Position.UTIL], 350, 5, 10, "hitter"),
            ("OF", [Position.OF, Position.UTIL], 320, 10, 5, "hitter"),
            ("P", [Position.P], 280, 10, 5, "pitcher"),
        ])
        league = _make_league(
            num_teams=2, roster_size=10,
            catcher=1, first_base=1, outfield=2, utility=1,
            pitcher=3, bench=2, bench_hitters=1,
        )
        first_pass = _first_pass_replacement(df, league)
        pool = _build_drafted_pool(df, league, first_pass)
        final = _final_replacement_levels(pool)

        for pos in first_pass:
            if final.get(pos, 0) > 0 and first_pass[pos] > 0:
                assert final[pos] <= first_pass[pos], (
                    f"Final {pos} ({final[pos]}) > first-pass ({first_pass[pos]})"
                )

    def test_empty_position_gets_zero(self):
        """Positions with no drafted eligible players get replacement = 0."""
        df = _make_players([
            ("OF", [Position.OF, Position.UTIL], 350, 5, 10, "hitter"),
            ("P", [Position.P], 280, 3, 10, "pitcher"),
        ])
        league = _make_league(
            num_teams=1, roster_size=4,
            catcher=0, first_base=0, outfield=2, utility=0,
            pitcher=2, bench=0, bench_hitters=0,
        )
        first_pass = _first_pass_replacement(df, league)
        pool = _build_drafted_pool(df, league, first_pass)
        levels = _final_replacement_levels(pool)

        assert levels[Position.C] == 0.0
        assert levels[Position.SS] == 0.0


class TestReplacementLevels:
    """Integration tests for the full calculate_replacement_levels function."""

    def test_returns_all_positions(self):
        """Should return replacement levels for all positions."""
        df = _make_players([
            ("C", [Position.C, Position.UTIL], 300, 5, 10, "hitter"),
            ("1B", [Position.FIRST, Position.UTIL], 350, 5, 10, "hitter"),
            ("OF", [Position.OF, Position.UTIL], 320, 10, 5, "hitter"),
            ("P", [Position.P], 280, 10, 5, "pitcher"),
        ])
        league = _make_league(
            num_teams=2, roster_size=8,
            catcher=1, first_base=1, outfield=2, utility=1,
            pitcher=3, bench=0, bench_hitters=0,
        )
        levels = calculate_replacement_levels(df, league=league)
        for pos in Position:
            assert pos in levels

    def test_replacement_levels_are_reasonable(self):
        """Replacement levels should be between 0 and max player points."""
        df = _make_players([
            ("C", [Position.C, Position.UTIL], 300, 5, 10, "hitter"),
            ("OF", [Position.OF, Position.UTIL], 350, 10, 10, "hitter"),
            ("P", [Position.P], 280, 8, 10, "pitcher"),
        ])
        league = _make_league(
            num_teams=2, roster_size=8,
            catcher=1, first_base=0, outfield=2, utility=1,
            pitcher=3, bench=1, bench_hitters=0,
        )
        levels = calculate_replacement_levels(df, league=league)
        max_pts = df["points"].max()

        for pos, level in levels.items():
            assert level >= 0, f"{pos} has negative replacement level"
            assert level <= max_pts, f"{pos} replacement level exceeds max"


class TestReplacementLevelValidation:
    """Tests for the Util-only validation guard."""

    def test_raises_on_all_util_hitters(self):
        """Should raise ValueError when most hitters have only [Util] positions."""
        players = []
        for i in range(20):
            players.append({
                "name": f"Hitter {i}",
                "positions": [Position.UTIL],
                "points": 300 - i * 10,
                "player_type": "hitter",
            })
        for i in range(10):
            players.append({
                "name": f"Pitcher {i}",
                "positions": [Position.P],
                "points": 250 - i * 10,
                "player_type": "pitcher",
            })
        df = pd.DataFrame(players)
        with pytest.raises(ValueError, match="positions"):
            calculate_replacement_levels(df)


class TestLeagueSettingsBenchHitters:
    """Tests for the bench_hitters override on LeagueSettings."""

    def test_default_bench_hitters_is_one(self):
        """Default LeagueSettings should use calibrated bench_hitters=1."""
        league = LeagueSettings()
        assert league.bench_hitters == 1

    def test_bench_hitting_estimate_with_override(self):
        """Setting bench_hitters should override proportional calculation."""
        league = LeagueSettings(bench_hitters=1)
        assert league.bench_hitting_estimate == 1 * league.num_teams

    def test_bench_pitching_estimate_with_override(self):
        """Bench pitching should be the remainder after bench hitters."""
        league = LeagueSettings(bench_hitters=1)
        total_bench = league.bench * league.num_teams
        assert league.bench_pitching_estimate == total_bench - league.bench_hitting_estimate

    def test_bench_hitters_zero(self):
        """bench_hitters=0 should allocate all bench to pitchers."""
        league = LeagueSettings(bench_hitters=0)
        assert league.bench_hitting_estimate == 0
        assert league.bench_pitching_estimate == league.bench * league.num_teams

    def test_bench_hitters_equals_bench(self):
        """bench_hitters=bench should allocate all bench to hitters."""
        league = LeagueSettings(bench_hitters=4)
        assert league.bench_hitting_estimate == 4 * league.num_teams
        assert league.bench_pitching_estimate == 0

    def test_bench_hitters_too_high_raises(self):
        """bench_hitters > bench should raise ValueError."""
        with pytest.raises(ValueError, match="bench_hitters must be between"):
            LeagueSettings(bench_hitters=5)

    def test_bench_hitters_negative_raises(self):
        """Negative bench_hitters should raise ValueError."""
        with pytest.raises(ValueError, match="bench_hitters must be between"):
            LeagueSettings(bench_hitters=-1)

"""Tests for the draft simulation engine."""

from __future__ import annotations

import random
import textwrap
from pathlib import Path

import pytest

from config.league import LEAGUE
from config.positions import Position
from simulation.engine import (
    AggregateResults,
    DraftResult,
    SLOT_CAPACITIES,
    SimPlayer,
    SimTeam,
    determine_bid,
    load_simulation_players,
    parse_yahoo_values,
    run_one_draft,
    run_simulations,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
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


def _make_team(team_id: int = 0, is_user: bool = False, budget: int = 260) -> SimTeam:
    """Create a SimTeam with default budget."""
    team = SimTeam(team_id=team_id, is_user=is_user, budget=budget)
    return team


# ---------------------------------------------------------------------------
# SimTeam tests
# ---------------------------------------------------------------------------

class TestSimTeam:
    """Tests for SimTeam roster management."""

    def test_initial_state(self) -> None:
        """New team has full budget and empty roster."""
        team = _make_team()
        assert team.budget == 260
        assert team.remaining_slots == 23  # slot_capacity = 23 (no IL slot)
        assert team.max_bid == 238  # 260 - 22

    def test_max_bid_reserves_dollar_per_slot(self) -> None:
        """Max bid must leave $1 per remaining empty slot."""
        team = _make_team(budget=50)
        # 23 slots remaining -> max bid = 50 - 22 = 28
        assert team.max_bid == 28

    def test_assign_hitter_to_scarcest_position(self) -> None:
        """Multi-position hitter should be assigned to scarcest eligible slot."""
        team = _make_team()
        # C/OF eligible -> should go to C (scarcer)
        player = _make_player(positions=[Position.C, Position.OF, Position.UTIL])
        team.assign_player(player, 10)
        assert team.roster[0].slot == Position.C

    def test_assign_pitcher_to_p_slot(self) -> None:
        """Pitcher should be assigned to P slot first."""
        team = _make_team()
        player = _make_player(player_type="pitcher", positions=[Position.P])
        team.assign_player(player, 10)
        assert team.roster[0].slot == Position.P

    def test_pitcher_overflow_to_bench(self) -> None:
        """When P slots are full, pitcher goes to bench."""
        team = _make_team()
        # Fill all 8 P slots
        for i in range(8):
            p = _make_player(name=f"P{i}", player_type="pitcher", positions=[Position.P])
            team.assign_player(p, 1)
        # 9th pitcher should go to bench
        p9 = _make_player(name="P9", player_type="pitcher", positions=[Position.P])
        team.assign_player(p9, 1)
        assert team.roster[-1].slot == "Bench"

    def test_hitter_overflow_to_util_then_bench(self) -> None:
        """When position slots are full, hitter goes to Util, then Bench."""
        team = _make_team()
        # Fill 4 OF slots
        for i in range(4):
            p = _make_player(name=f"OF{i}", positions=[Position.OF, Position.UTIL])
            team.assign_player(p, 1)
        # Fill 2 Util slots
        for i in range(2):
            p = _make_player(name=f"Util{i}", positions=[Position.OF, Position.UTIL])
            team.assign_player(p, 1)
        # Next OF-only eligible player should go to bench
        p_bench = _make_player(name="OFBench", positions=[Position.OF, Position.UTIL])
        team.assign_player(p_bench, 1)
        assert team.roster[-1].slot == "Bench"

    def test_can_roster_false_when_no_slot(self) -> None:
        """can_roster returns False when no valid slot exists for player type."""
        team = _make_team(budget=100)
        # Fill all slots that an OF-eligible player can go to:
        # OF (4), Util (2), Bench (4) = 10 slots
        for i in range(4):
            team.assign_player(
                _make_player(name=f"OF{i}", positions=[Position.OF, Position.UTIL]), 1
            )
        for i in range(2):
            team.assign_player(
                _make_player(name=f"U{i}", positions=[Position.OF, Position.UTIL]), 1
            )
        for i in range(4):
            team.assign_player(
                _make_player(name=f"B{i}", positions=[Position.OF, Position.UTIL]), 1
            )
        # OF-only player can no longer be rostered (all OF/Util/Bench full)
        new_of = _make_player(positions=[Position.OF, Position.UTIL])
        assert team._find_slot(new_of) is None

    def test_budget_deducted_on_assign(self) -> None:
        """Assigning a player deducts the price from team budget."""
        team = _make_team(budget=100)
        player = _make_player()
        team.assign_player(player, 25)
        assert team.budget == 75


# ---------------------------------------------------------------------------
# Bidding tests
# ---------------------------------------------------------------------------

class TestBidding:
    """Tests for the determine_bid function."""

    def test_user_bids_our_value(self) -> None:
        """User team should bid based on our_value."""
        team = _make_team(is_user=True)
        player = _make_player(our_value=30, yahoo_value=50)
        rng = random.Random(42)
        bid = determine_bid(team, player, rng, noise_std=0.0)
        assert bid == 30

    def test_competitor_bids_yahoo_value(self) -> None:
        """Competitor team should bid based on yahoo_value."""
        team = _make_team(is_user=False)
        player = _make_player(our_value=30, yahoo_value=50)
        rng = random.Random(42)
        bid = determine_bid(team, player, rng, noise_std=0.0)
        assert bid == 50

    def test_bid_capped_at_max_bid(self) -> None:
        """Bid should never exceed team's max_bid."""
        team = _make_team(budget=5)
        # Fill 21 of 23 slots to leave 2 remaining -> max_bid = 5 - 1 = 4
        for i in range(8):
            team.assign_player(
                _make_player(name=f"P{i}", player_type="pitcher", positions=[Position.P]), 0
            )
        for i in range(4):
            team.assign_player(
                _make_player(name=f"OF{i}", positions=[Position.OF, Position.UTIL]), 0
            )
        for i in range(2):
            team.assign_player(
                _make_player(name=f"U{i}", positions=[Position.FIRST, Position.UTIL]), 0
            )
        for i in range(4):
            team.assign_player(
                _make_player(name=f"B{i}", positions=[Position.THIRD, Position.UTIL]), 0
            )
        # Fill more: C, SS, 2B = 3 more -> 21 total, 2 remaining
        team.assign_player(_make_player(name="C1", positions=[Position.C, Position.UTIL]), 0)
        team.assign_player(_make_player(name="SS1", positions=[Position.SS, Position.UTIL]), 0)
        team.assign_player(_make_player(name="2B1", positions=[Position.SECOND, Position.UTIL]), 0)
        assert team.remaining_slots == 2
        assert team.max_bid == 4

        player = _make_player(our_value=100, yahoo_value=100, positions=[Position.THIRD, Position.UTIL])
        rng = random.Random(42)
        bid = determine_bid(team, player, rng, noise_std=0.0)
        assert bid <= 4

    def test_zero_value_bids_one_to_fill_roster(self) -> None:
        """Player with zero base value still gets $1 bid to fill roster."""
        team = _make_team(is_user=True)
        player = _make_player(our_value=0)
        rng = random.Random(42)
        bid = determine_bid(team, player, rng)
        assert bid == 1

    def test_noise_varies_bids(self) -> None:
        """With noise, repeated bids for the same player should vary."""
        team = _make_team()
        player = _make_player(yahoo_value=40)
        bids = set()
        for seed in range(20):
            rng = random.Random(seed)
            # Reset team state for each bid
            fresh_team = _make_team()
            bids.add(determine_bid(fresh_team, player, rng, noise_std=0.18))
        assert len(bids) > 1, "Bids should vary with noise"

    def test_bid_minimum_is_one(self) -> None:
        """Bid should be at least $1 when base value is positive."""
        team = _make_team()
        player = _make_player(yahoo_value=1)
        rng = random.Random(42)
        bid = determine_bid(team, player, rng, noise_std=0.0)
        assert bid >= 1


# ---------------------------------------------------------------------------
# Auction mechanic tests
# ---------------------------------------------------------------------------

class TestAuctionMechanics:
    """Tests for the ascending auction (second-highest bid + $1) mechanic."""

    def test_winner_pays_second_plus_one(self) -> None:
        """Winner should pay second-highest bid + $1, not their own bid."""
        # Create a 2-team league with known bids
        from simulation.engine import run_one_draft
        from config.league import LeagueSettings

        # Player valued at $20 by user, $10 by competitor
        player = _make_player(
            name="Target",
            our_value=20,
            yahoo_value=10,
            positions=[Position.OF, Position.UTIL],
        )
        # Add enough filler to fill rosters
        fillers = []
        for i in range(50):
            fillers.append(_make_player(
                name=f"Filler{i}",
                our_value=1,
                yahoo_value=1,
                points=100.0,
                positions=[Position.OF, Position.C, Position.FIRST, Position.SECOND,
                           Position.THIRD, Position.SS, Position.UTIL],
            ))
        for i in range(50):
            fillers.append(_make_player(
                name=f"FillerP{i}",
                player_type="pitcher",
                our_value=1,
                yahoo_value=1,
                points=100.0,
                positions=[Position.P],
            ))
        players = [player] + fillers

        league = LeagueSettings(num_teams=2)
        rng = random.Random(42)
        result = run_one_draft(players, rng, noise_std=0.0, league=league)

        # User should win at $11 (second bid $10 + $1), not $20
        user = result.user_team
        target_pick = [dp for dp in user.roster if dp.player.name == "Target"]
        assert len(target_pick) == 1
        assert target_pick[0].price == 11

    def test_low_competition_pays_two(self) -> None:
        """When competitor only bids $1 (roster fill), winner pays $2."""
        from simulation.engine import run_one_draft
        from config.league import LeagueSettings

        # Player valued at $20 by user, $0 by competitor (bids $1 to fill roster)
        player = _make_player(
            name="Sleeper",
            our_value=20,
            yahoo_value=0,
            points=500.0,
            positions=[Position.OF, Position.UTIL],
        )
        fillers = []
        for i in range(50):
            fillers.append(_make_player(
                name=f"F{i}", our_value=1, yahoo_value=1, points=100.0,
                positions=[Position.OF, Position.C, Position.FIRST, Position.SECOND,
                           Position.THIRD, Position.SS, Position.UTIL],
            ))
        for i in range(50):
            fillers.append(_make_player(
                name=f"FP{i}", player_type="pitcher", our_value=1, yahoo_value=1,
                points=100.0, positions=[Position.P],
            ))
        players = [player] + fillers

        league = LeagueSettings(num_teams=2)
        rng = random.Random(42)
        result = run_one_draft(players, rng, noise_std=0.0, league=league)

        user = result.user_team
        sleeper_pick = [dp for dp in user.roster if dp.player.name == "Sleeper"]
        assert len(sleeper_pick) == 1
        # Competitor bids $1 (roster fill), so winner pays $1 + $1 = $2
        assert sleeper_pick[0].price == 2


# ---------------------------------------------------------------------------
# Yahoo parsing tests
# ---------------------------------------------------------------------------

class TestYahooParsing:
    """Tests for parse_yahoo_values."""

    def test_parse_real_file(self) -> None:
        """Parse the actual Yahoo auction values file if it exists."""
        path = Path("projections/yahoo_auction_values.txt")
        if not path.exists():
            pytest.skip("Yahoo auction values file not present")
        values = parse_yahoo_values(path)
        assert len(values) > 100, f"Expected >100 players, got {len(values)}"
        # Spot check a known player
        assert "Aaron Judge" in values
        assert values["Aaron Judge"]["league_value"] > 0

    def test_missing_player_defaults(self) -> None:
        """Players not in Yahoo values should get yahoo_value=1."""
        yahoo = {"Known Player": {"league_value": 30, "avg_salary": 35.0}}
        players = load_simulation_players(
            Path("player_values.csv"),
            yahoo,
        )
        # Most players won't match -> should default to 1
        unknown = [p for p in players if p.yahoo_value == 1]
        assert len(unknown) > 0


# ---------------------------------------------------------------------------
# Full draft simulation tests
# ---------------------------------------------------------------------------

class TestDraftSimulation:
    """Tests for run_one_draft."""

    def test_all_teams_fill_rosters(self) -> None:
        """Every team should fill all 23 draftable roster spots (IL slot excluded)."""
        yahoo = parse_yahoo_values(Path("projections/yahoo_auction_values.txt"))
        players = load_simulation_players(Path("player_values.csv"), yahoo)
        rng = random.Random(42)
        result = run_one_draft(players, rng)

        for team in result.teams:
            assert team.remaining_slots == 0, (
                f"Team {team.team_id} has {team.remaining_slots} unfilled slots"
            )

    def test_no_team_exceeds_budget(self) -> None:
        """No team should have negative remaining budget."""
        yahoo = parse_yahoo_values(Path("projections/yahoo_auction_values.txt"))
        players = load_simulation_players(Path("player_values.csv"), yahoo)
        rng = random.Random(42)
        result = run_one_draft(players, rng)

        for team in result.teams:
            assert team.budget >= 0, (
                f"Team {team.team_id} overspent: ${team.budget} remaining"
            )

    def test_roster_constraints_satisfied(self) -> None:
        """Each team's roster should respect position slot limits."""
        yahoo = parse_yahoo_values(Path("projections/yahoo_auction_values.txt"))
        players = load_simulation_players(Path("player_values.csv"), yahoo)
        rng = random.Random(42)
        result = run_one_draft(players, rng)

        for team in result.teams:
            for slot, capacity in SLOT_CAPACITIES.items():
                assert team.filled_slots[slot] <= capacity, (
                    f"Team {team.team_id}: {slot} has {team.filled_slots[slot]}/{capacity}"
                )

    def test_total_drafted_equals_expected(self) -> None:
        """Total drafted players should be 14 teams * 23 draftable slots = 322."""
        yahoo = parse_yahoo_values(Path("projections/yahoo_auction_values.txt"))
        players = load_simulation_players(Path("player_values.csv"), yahoo)
        rng = random.Random(42)
        result = run_one_draft(players, rng)

        expected = LEAGUE.num_teams * sum(SLOT_CAPACITIES.values())
        total = sum(len(t.roster) for t in result.teams)
        assert total == expected

    def test_user_rank_in_range(self) -> None:
        """User's rank should be between 1 and 14."""
        yahoo = parse_yahoo_values(Path("projections/yahoo_auction_values.txt"))
        players = load_simulation_players(Path("player_values.csv"), yahoo)
        rng = random.Random(42)
        result = run_one_draft(players, rng)

        assert 1 <= result.user_rank <= 14


class TestAggregateResults:
    """Tests for run_simulations aggregate output."""

    def test_run_simulations_basic(self) -> None:
        """run_simulations should complete and return valid aggregate stats."""
        results = run_simulations(
            "player_values.csv",
            "projections/yahoo_auction_values.txt",
            n=3,
            seed=42,
        )
        assert results.n_simulations == 3
        assert len(results.user_points) == 3
        assert len(results.user_ranks) == 3
        assert all(1 <= r <= 14 for r in results.user_ranks)
        assert results.mean_user_points > 0
        assert results.mean_competitor_points > 0

    def test_deterministic_with_seed(self) -> None:
        """Same seed should produce identical results."""
        r1 = run_simulations(
            "player_values.csv",
            "projections/yahoo_auction_values.txt",
            n=2,
            seed=123,
        )
        r2 = run_simulations(
            "player_values.csv",
            "projections/yahoo_auction_values.txt",
            n=2,
            seed=123,
        )
        assert r1.user_points == r2.user_points
        assert r1.user_ranks == r2.user_ranks

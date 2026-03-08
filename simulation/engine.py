"""Core Monte Carlo draft simulation engine.

Simulates auction drafts where a "user" team bids using our model's values
while competitor teams bid using Yahoo league values, with Gaussian noise.
"""

from __future__ import annotations

import csv
import math
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from config.league import LEAGUE, LeagueSettings
from config.positions import Position, parse_positions


# Slot capacities for a single team, derived from league settings.
SLOT_CAPACITIES: dict[Position | str, int] = {
    Position.C: LEAGUE.catcher,
    Position.FIRST: LEAGUE.first_base,
    Position.SECOND: LEAGUE.second_base,
    Position.THIRD: LEAGUE.third_base,
    Position.SS: LEAGUE.shortstop,
    Position.OF: LEAGUE.outfield,
    Position.UTIL: LEAGUE.utility,
    Position.P: LEAGUE.pitcher,
    "Bench": LEAGUE.bench,
}

# Scarcity order for hitter slot assignment (lower replacement = scarcer).
# Derived from replacement levels: C(333.5) > 3B(334.0) > OF(336.5) > SS(361.0) > 1B(362.0) > 2B(365.5)
HITTER_SCARCITY_ORDER: list[Position] = [
    Position.C,
    Position.THIRD,
    Position.OF,
    Position.SS,
    Position.FIRST,
    Position.SECOND,
    Position.UTIL,
]


@dataclass
class SimPlayer:
    """A player available for auction in the simulation."""

    name: str
    player_type: str  # "hitter" or "pitcher"
    points: float
    positions: list[Position]
    our_value: int
    yahoo_value: int

    @property
    def is_pitcher(self) -> bool:
        """Return True if this player is a pitcher."""
        return self.player_type == "pitcher"


@dataclass
class DraftedPlayer:
    """A player drafted to a team with assigned slot and price."""

    player: SimPlayer
    slot: Position | str  # Position or "Bench"
    price: int


@dataclass
class SimTeam:
    """A team participating in the simulated draft."""

    team_id: int
    is_user: bool
    budget: int = LEAGUE.budget_per_team
    filled_slots: dict[Position | str, int] = field(default_factory=dict)
    roster: list[DraftedPlayer] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Initialize filled slot counts to zero."""
        if not self.filled_slots:
            self.filled_slots = {slot: 0 for slot in SLOT_CAPACITIES}

    @property
    def slot_capacity(self) -> int:
        """Total slot capacity (sum of all slot types)."""
        return sum(SLOT_CAPACITIES.values())

    @property
    def remaining_slots(self) -> int:
        """Number of unfilled roster spots."""
        total_filled = sum(self.filled_slots.values())
        return self.slot_capacity - total_filled

    @property
    def max_bid(self) -> int:
        """Maximum legal bid: must reserve $1 per remaining empty slot."""
        remaining = self.remaining_slots
        if remaining <= 0:
            return 0
        return self.budget - (remaining - 1)

    @property
    def total_points(self) -> float:
        """Sum of projected points across all rostered players."""
        return sum(dp.player.points for dp in self.roster)

    def can_roster(self, player: SimPlayer) -> bool:
        """Check if any legal slot exists for this player."""
        if self.remaining_slots <= 0:
            return False
        if self.max_bid < 1:
            return False
        return self._find_slot(player) is not None

    def assign_player(self, player: SimPlayer, price: int) -> None:
        """Assign a player to the scarcest open eligible slot and deduct budget."""
        slot = self._find_slot(player)
        if slot is None:
            raise ValueError(f"No valid slot for {player.name}")
        self.filled_slots[slot] += 1
        self.budget -= price
        self.roster.append(DraftedPlayer(player=player, slot=slot, price=price))

    def _find_slot(self, player: SimPlayer) -> Position | str | None:
        """Find the best slot for a player using scarcest-first assignment."""
        if player.is_pitcher:
            # Pitchers: P > Bench
            if self.filled_slots[Position.P] < SLOT_CAPACITIES[Position.P]:
                return Position.P
            if self.filled_slots["Bench"] < SLOT_CAPACITIES["Bench"]:
                return "Bench"
            return None

        # Hitters: try scarcest eligible position first, then Util, then Bench
        for pos in HITTER_SCARCITY_ORDER:
            if pos == Position.UTIL:
                # Util is always eligible for hitters
                if self.filled_slots[Position.UTIL] < SLOT_CAPACITIES[Position.UTIL]:
                    return Position.UTIL
            elif pos in player.positions:
                if self.filled_slots[pos] < SLOT_CAPACITIES[pos]:
                    return pos
        # Fall through to bench
        if self.filled_slots["Bench"] < SLOT_CAPACITIES["Bench"]:
            return "Bench"
        return None


def parse_yahoo_values(filepath: str | Path) -> dict[str, dict]:
    """Parse Yahoo auction values from the raw text file.

    The file has a repeating pattern per player:
    - Player name line
    - Info line (name + team/position details)
    - Blank or $ line
    - Dash line
    - Tab-separated values line: $league_value $proj_salary $avg_salary status

    Returns dict mapping player name to {"league_value": int, "avg_salary": float}.
    """
    filepath = Path(filepath)
    text = filepath.read_text(encoding="utf-8")
    lines = text.splitlines()

    values: dict[str, dict] = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Skip empty lines and header lines
        if not line or line in ("Player", "My Value", "League Value",
                                "Proj Salary", "Avg Salary", "Roster Status",
                                "$", "-"):
            i += 1
            continue

        # Look for a values line (starts with tab, contains dollar amounts)
        if "\t$" in lines[i] if i < len(lines) else False:
            i += 1
            continue

        # This might be a player name line — check if subsequent lines match pattern
        candidate_name = line
        # Look ahead for the value line pattern: \t$NN \t$NN \t$NN.N \tStatus
        found_values = False
        for j in range(i + 1, min(i + 6, len(lines))):
            val_line = lines[j]
            # Match lines like: \t$54 \t$54 \t$65.1 \tW (Mar 9)
            match = re.search(r'\$(\d+)\s+\t\$(\d+)\s+\t\$(\d+\.?\d*)', val_line)
            if match:
                league_value = int(match.group(1))
                avg_salary = float(match.group(3))
                values[candidate_name] = {
                    "league_value": league_value,
                    "avg_salary": avg_salary,
                }
                found_values = True
                i = j + 1
                break
        if not found_values:
            i += 1

    return values


def load_simulation_players(
    our_csv: str | Path,
    yahoo_values: dict[str, dict],
) -> list[SimPlayer]:
    """Load player values CSV and merge with Yahoo values.

    Players without Yahoo matches default to yahoo_value=1.

    Returns list of SimPlayer objects sorted by points descending.
    """
    players: list[SimPlayer] = []
    our_csv = Path(our_csv)

    with open(our_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"]
            our_value = int(float(row["dollar_value"]))
            points = float(row["points"])
            player_type = row["player_type"]
            positions = parse_positions(row["positions"])

            yahoo = yahoo_values.get(name, {})
            yahoo_value = yahoo.get("league_value", 1)

            players.append(
                SimPlayer(
                    name=name,
                    player_type=player_type,
                    points=points,
                    positions=positions,
                    our_value=our_value,
                    yahoo_value=yahoo_value,
                )
            )

    # Sort by points descending (nomination order)
    players.sort(key=lambda p: p.points, reverse=True)
    return players


def determine_bid(
    team: SimTeam,
    player: SimPlayer,
    rng: random.Random,
    noise_std: float = 0.18,
) -> int:
    """Determine a team's bid for a player.

    User teams bid based on our_value; competitors bid based on yahoo_value.
    Gaussian noise is added with std = noise_std * base_value.
    """
    if not team.can_roster(player):
        return 0
    base = player.our_value if team.is_user else player.yahoo_value
    if base <= 0:
        # Still bid $1 to fill roster if team has open slots
        return min(1, team.max_bid) if team.max_bid >= 1 else 0
    # User bids exactly at model value; only competitors get noise
    if team.is_user:
        bid = base
    else:
        bid = max(1, round(base + rng.gauss(0, base * noise_std)))
    return min(bid, team.max_bid)


@dataclass
class DraftResult:
    """Results from a single simulated draft."""

    teams: list[SimTeam]
    undrafted: list[SimPlayer]

    @property
    def user_team(self) -> SimTeam:
        """Return the user's team."""
        for t in self.teams:
            if t.is_user:
                return t
        raise ValueError("No user team found")

    @property
    def user_rank(self) -> int:
        """User's rank by total points (1 = best)."""
        sorted_teams = sorted(self.teams, key=lambda t: t.total_points, reverse=True)
        for i, t in enumerate(sorted_teams, 1):
            if t.is_user:
                return i
        raise ValueError("No user team found")

    @property
    def competitor_avg_points(self) -> float:
        """Average total points across competitor (non-user) teams."""
        comps = [t for t in self.teams if not t.is_user]
        return sum(t.total_points for t in comps) / len(comps)


def _choose_nomination(team: SimTeam, available: list[SimPlayer]) -> SimPlayer | None:
    """Choose which player a team nominates.

    Each team nominates the available player they value most highly
    (our_value for user, yahoo_value for competitors) that they can roster.
    """
    best: SimPlayer | None = None
    best_val = -1
    for player in available:
        if not team.can_roster(player):
            continue
        val = player.our_value if team.is_user else player.yahoo_value
        if val > best_val:
            best_val = val
            best = player
    return best


def _fill_remaining_rosters(teams: list[SimTeam]) -> None:
    """Fill remaining roster spots with $1 filler players (below-replacement)."""
    filler_id = 0
    for team in teams:
        while team.remaining_slots > 0 and team.max_bid >= 1:
            filler_id += 1
            assigned = False
            # Try pitcher filler first if P slots are open
            if team.filled_slots[Position.P] < SLOT_CAPACITIES[Position.P]:
                filler = SimPlayer(
                    name=f"Filler P {filler_id}",
                    player_type="pitcher",
                    points=0.0,
                    positions=[Position.P],
                    our_value=1,
                    yahoo_value=1,
                )
                if team.can_roster(filler):
                    team.assign_player(filler, 1)
                    assigned = True
            if not assigned:
                # Try hitter filler — eligible for all hitter positions + Bench
                all_hitter_pos = [
                    p for p in HITTER_SCARCITY_ORDER if p != Position.UTIL
                ] + [Position.UTIL]
                filler = SimPlayer(
                    name=f"Filler H {filler_id}",
                    player_type="hitter",
                    points=0.0,
                    positions=all_hitter_pos,
                    our_value=1,
                    yahoo_value=1,
                )
                if team.can_roster(filler):
                    team.assign_player(filler, 1)
                    assigned = True
            if not assigned:
                break  # No valid slot for any filler type


def run_one_draft(
    players: list[SimPlayer],
    rng: random.Random,
    noise_std: float = 0.18,
    league: LeagueSettings = LEAGUE,
) -> DraftResult:
    """Simulate a single auction draft with realistic auction mechanics.

    Nomination rotates round-robin among teams. Each team nominates the
    available player they value most. All teams submit their max
    willingness-to-pay; the winner pays second-highest bid + $1 (floored
    at $1). If only one bidder, they win at $1.
    """
    teams = [
        SimTeam(team_id=0, is_user=True),
    ] + [
        SimTeam(team_id=i, is_user=False)
        for i in range(1, league.num_teams)
    ]

    available = list(players)  # mutable copy
    available_set = set(id(p) for p in available)
    undrafted: list[SimPlayer] = []

    nom_idx = 0  # round-robin nomination index
    stale_rounds = 0  # track consecutive full rounds with no nomination

    while available:
        nominator = teams[nom_idx % league.num_teams]
        nom_idx += 1

        # Skip teams with full rosters
        if nominator.remaining_slots <= 0:
            # If we've cycled through all teams with no one able to nominate, stop
            if nom_idx % league.num_teams == 0:
                all_full = all(t.remaining_slots <= 0 for t in teams)
                if all_full:
                    break
            continue

        # Nominator picks the player they want most
        nominated = _choose_nomination(nominator, available)
        if nominated is None:
            stale_rounds += 1
            if stale_rounds >= league.num_teams:
                break  # No team can nominate anyone
            continue
        stale_rounds = 0

        # Remove from available pool
        available_set.discard(id(nominated))
        available = [p for p in available if id(p) in available_set]

        # All teams submit willingness-to-pay (starting bid is $1)
        bids: list[tuple[int, SimTeam]] = []
        for team in teams:
            bid = determine_bid(team, nominated, rng, noise_std)
            if bid > 0:
                bids.append((bid, team))

        if not bids:
            undrafted.append(nominated)
            continue

        # Sort bids descending; break ties randomly
        rng.shuffle(bids)  # randomize before stable sort for tie-breaking
        bids.sort(key=lambda b: b[0], reverse=True)

        winner_bid, winner = bids[0]
        if len(bids) >= 2:
            second_bid = bids[1][0]
            price = min(winner_bid, second_bid + 1)
        else:
            price = 1  # no competition, win at $1

        price = max(1, price)
        winner.assign_player(nominated, price)

    # Any remaining players are undrafted
    undrafted.extend(available)

    _fill_remaining_rosters(teams)

    return DraftResult(teams=teams, undrafted=undrafted)


@dataclass
class AggregateResults:
    """Aggregated results across multiple simulated drafts."""

    n_simulations: int
    user_points: list[float]
    competitor_avg_points: list[float]
    user_ranks: list[int]
    user_budgets_remaining: list[int]
    competitor_budgets_remaining: list[list[int]]
    user_roster_sizes: list[int]
    draft_results: list[DraftResult]

    @property
    def mean_user_points(self) -> float:
        """Mean total points for user across simulations."""
        return sum(self.user_points) / len(self.user_points)

    @property
    def std_user_points(self) -> float:
        """Standard deviation of user's total points."""
        mean = self.mean_user_points
        variance = sum((p - mean) ** 2 for p in self.user_points) / len(self.user_points)
        return math.sqrt(variance)

    @property
    def mean_competitor_points(self) -> float:
        """Mean of competitor average points across simulations."""
        return sum(self.competitor_avg_points) / len(self.competitor_avg_points)

    @property
    def std_competitor_points(self) -> float:
        """Standard deviation of competitor average points."""
        mean = self.mean_competitor_points
        variance = sum(
            (p - mean) ** 2 for p in self.competitor_avg_points
        ) / len(self.competitor_avg_points)
        return math.sqrt(variance)

    @property
    def mean_user_rank(self) -> float:
        """Mean rank of user across simulations."""
        return sum(self.user_ranks) / len(self.user_ranks)

    @property
    def top4_rate(self) -> float:
        """Fraction of simulations where user finishes in top 4."""
        return sum(1 for r in self.user_ranks if r <= 4) / len(self.user_ranks)

    @property
    def win_rate(self) -> float:
        """Fraction of simulations where user finishes 1st."""
        return sum(1 for r in self.user_ranks if r == 1) / len(self.user_ranks)

    @property
    def mean_user_budget_remaining(self) -> float:
        """Mean leftover budget for user."""
        return sum(self.user_budgets_remaining) / len(self.user_budgets_remaining)

    @property
    def mean_competitor_budget_remaining(self) -> float:
        """Mean leftover budget across all competitors and simulations."""
        all_budgets = [b for sim_budgets in self.competitor_budgets_remaining for b in sim_budgets]
        if not all_budgets:
            return 0.0
        return sum(all_budgets) / len(all_budgets)


def run_simulations(
    our_csv: str | Path,
    yahoo_txt: str | Path,
    n: int = 10,
    seed: int | None = None,
    noise_std: float = 0.18,
) -> AggregateResults:
    """Run multiple draft simulations and aggregate results.

    Args:
        our_csv: Path to player_values.csv with our model's valuations.
        yahoo_txt: Path to Yahoo auction values text file.
        n: Number of simulations to run.
        seed: Random seed for reproducibility.
        noise_std: Bid noise standard deviation as a fraction of base value.

    Returns:
        AggregateResults with per-simulation and aggregate statistics.
    """
    yahoo_values = parse_yahoo_values(yahoo_txt)
    players = load_simulation_players(our_csv, yahoo_values)

    rng = random.Random(seed)

    user_points: list[float] = []
    comp_avg_points: list[float] = []
    user_ranks: list[int] = []
    user_budgets: list[int] = []
    comp_budgets: list[list[int]] = []
    user_roster_sizes: list[int] = []
    results: list[DraftResult] = []

    for _ in range(n):
        result = run_one_draft(players, rng, noise_std)
        results.append(result)

        user = result.user_team
        user_points.append(user.total_points)
        comp_avg_points.append(result.competitor_avg_points)
        user_ranks.append(result.user_rank)
        user_budgets.append(user.budget)
        user_roster_sizes.append(LEAGUE.roster_size - user.remaining_slots)
        comp_budgets.append([t.budget for t in result.teams if not t.is_user])

    return AggregateResults(
        n_simulations=n,
        user_points=user_points,
        competitor_avg_points=comp_avg_points,
        user_ranks=user_ranks,
        user_budgets_remaining=user_budgets,
        competitor_budgets_remaining=comp_budgets,
        user_roster_sizes=user_roster_sizes,
        draft_results=results,
    )

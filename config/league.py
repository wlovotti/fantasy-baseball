"""League constants: team count, budget, and roster construction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class LeagueSettings:
    """Core league configuration."""

    num_teams: int = 14
    budget_per_team: int = 260
    roster_size: int = 24

    # Hitting roster slots
    catcher: int = 1
    first_base: int = 1
    second_base: int = 1
    third_base: int = 1
    shortstop: int = 1
    outfield: int = 4
    utility: int = 2

    # Pitching roster slots
    pitcher: int = 8

    # Bench
    bench: int = 4

    # Per-team bench hitters, calibrated from 3 seasons of draft history (avg 1.36).
    # Override via LeagueSettings(bench_hitters=N) or --bench-hitters on CLI.
    bench_hitters: int | None = 1

    def __post_init__(self) -> None:
        """Validate bench_hitters is within bounds."""
        if self.bench_hitters is not None:
            if not (0 <= self.bench_hitters <= self.bench):
                raise ValueError(
                    f"bench_hitters must be between 0 and {self.bench}, "
                    f"got {self.bench_hitters}"
                )

    @property
    def total_budget(self) -> int:
        """Total auction dollars across the league."""
        return self.num_teams * self.budget_per_team

    @property
    def hitting_slots(self) -> int:
        """Total starting hitting slots (excluding bench)."""
        return (
            self.catcher
            + self.first_base
            + self.second_base
            + self.third_base
            + self.shortstop
            + self.outfield
            + self.utility
        )

    @property
    def pitching_slots(self) -> int:
        """Total starting pitching slots."""
        return self.pitcher

    @property
    def starting_slots(self) -> int:
        """Total starting roster slots."""
        return self.hitting_slots + self.pitching_slots

    @property
    def total_hitting_slots_league(self) -> int:
        """Total hitting starters across the league."""
        return self.hitting_slots * self.num_teams

    @property
    def total_pitching_slots_league(self) -> int:
        """Total pitching starters across the league."""
        return self.pitching_slots * self.num_teams

    @property
    def bench_hitting_estimate(self) -> int:
        """Estimated bench slots used for hitters league-wide.

        When ``bench_hitters`` is set, uses that per-team count times
        the number of teams. Otherwise falls back to a proportional
        estimate based on the ratio of hitting to total starting slots.
        """
        if self.bench_hitters is not None:
            return self.bench_hitters * self.num_teams
        hitting_ratio = self.hitting_slots / self.starting_slots
        total_bench = self.bench * self.num_teams
        return round(total_bench * hitting_ratio)

    @property
    def bench_pitching_estimate(self) -> int:
        """Estimated bench slots used for pitchers (proportional)."""
        total_bench = self.bench * self.num_teams
        return total_bench - self.bench_hitting_estimate


LEAGUE = LeagueSettings()

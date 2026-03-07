"""Position definitions and eligibility mapping."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config.league import LEAGUE


class Position(str, Enum):
    """Fantasy roster positions."""

    C = "C"
    FIRST = "1B"
    SECOND = "2B"
    THIRD = "3B"
    SS = "SS"
    OF = "OF"
    UTIL = "Util"
    P = "P"


@dataclass(frozen=True)
class PositionSlots:
    """Number of starters needed league-wide for each position."""

    slots: dict[Position, int]

    def total_hitting_starters(self) -> int:
        """Total hitting starter slots (excluding Util and P)."""
        return sum(
            v for k, v in self.slots.items() if k not in (Position.UTIL, Position.P)
        )


def build_position_slots() -> PositionSlots:
    """Build league-wide position slot counts from league settings."""
    return PositionSlots(
        slots={
            Position.C: LEAGUE.catcher * LEAGUE.num_teams,
            Position.FIRST: LEAGUE.first_base * LEAGUE.num_teams,
            Position.SECOND: LEAGUE.second_base * LEAGUE.num_teams,
            Position.THIRD: LEAGUE.third_base * LEAGUE.num_teams,
            Position.SS: LEAGUE.shortstop * LEAGUE.num_teams,
            Position.OF: LEAGUE.outfield * LEAGUE.num_teams,
            Position.UTIL: LEAGUE.utility * LEAGUE.num_teams,
            Position.P: LEAGUE.pitcher * LEAGUE.num_teams,
        }
    )


# FanGraphs position string → our Position enum mapping
FANGRAPHS_POSITION_MAP: dict[str, list[Position]] = {
    "C": [Position.C],
    "1B": [Position.FIRST],
    "2B": [Position.SECOND],
    "3B": [Position.THIRD],
    "SS": [Position.SS],
    "OF": [Position.OF],
    "LF": [Position.OF],
    "CF": [Position.OF],
    "RF": [Position.OF],
    "DH": [Position.UTIL],
    "Util": [Position.UTIL],
    "SP": [Position.P],
    "RP": [Position.P],
}


def parse_positions(position_str: str) -> list[Position]:
    """Parse a FanGraphs position string into a list of eligible positions.

    FanGraphs uses comma-separated positions like '2B,SS,OF'.
    All hitters are also eligible for Util.
    """
    positions: set[Position] = set()
    for part in position_str.split(","):
        part = part.strip()
        if part in FANGRAPHS_POSITION_MAP:
            positions.update(FANGRAPHS_POSITION_MAP[part])

    # All hitters are Util-eligible; pitchers are not
    if positions and positions != {Position.P}:
        positions.add(Position.UTIL)

    return sorted(positions, key=lambda p: list(Position).index(p))


POSITION_SLOTS = build_position_slots()

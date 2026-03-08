"""Replacement level calculation using greedy position assignment."""

from __future__ import annotations

import pandas as pd

from config.league import LEAGUE, LeagueSettings
from config.positions import POSITION_SLOTS, Position


def calculate_replacement_levels(
    df: pd.DataFrame,
    league: LeagueSettings = LEAGUE,
) -> dict[Position, float]:
    """Calculate replacement-level points for each position.

    Uses greedy assignment: iterates through players by descending points,
    assigning each to the position where they provide the most marginal value
    (i.e., the position with the fewest remaining slots relative to demand).

    All pitchers are ranked in a single P pool — no SP/RP split.
    This naturally rewards elite relievers in leagues with HLD/SV scoring.

    Bench slots are allocated proportionally between hitters and pitchers.

    Args:
        df: Player DataFrame with 'points', 'positions', and 'player_type' columns.
        league: League settings controlling roster construction and bench allocation.

    Returns:
        Dictionary mapping each Position to its replacement-level points value.
    """
    # Guard: if most hitters have only [Util], positions are missing and
    # the output will be garbage (no positional scarcity).
    hitters = df[df["player_type"] == "hitter"]
    if len(hitters) > 0:
        util_only_count = sum(
            1 for positions in hitters["positions"]
            if positions == [Position.UTIL]
        )
        if util_only_count / len(hitters) > 0.5:
            raise ValueError(
                f"{util_only_count}/{len(hitters)} hitters have only [Util] "
                "positions. This means position data is missing and valuations "
                "will be wildly inaccurate. Merge Yahoo position eligibility "
                "before calculating replacement levels."
            )

    slots = dict(POSITION_SLOTS.slots)

    # Add bench slots proportionally
    slots_with_bench = _add_bench_slots(slots, league=league)

    # Track how many slots remain and who was the last assigned at each position
    remaining = dict(slots_with_bench)
    last_assigned: dict[Position, float] = {pos: 0.0 for pos in remaining}

    # Sort all players by points descending
    sorted_df = df.sort_values("points", ascending=False).reset_index(drop=True)

    for _, player in sorted_df.iterrows():
        eligible = player["positions"]
        pts = player["points"]

        # Find the best position to assign this player to:
        # Prefer positions that still have open slots
        best_pos = _find_best_position(eligible, remaining)

        if best_pos is not None:
            remaining[best_pos] -= 1
            last_assigned[best_pos] = pts

    # Replacement level = the points of the next player after all slots filled
    # Approximated by the last player assigned to each position
    return last_assigned


def _add_bench_slots(
    slots: dict[Position, int],
    league: LeagueSettings = LEAGUE,
) -> dict[Position, int]:
    """Add estimated bench slots to position slot counts.

    Bench hitters go to Util (best available hitter), bench pitchers to P.

    Args:
        slots: Base position slot counts.
        league: League settings for bench allocation.

    Returns:
        Updated slot counts with bench allocation.
    """
    result = dict(slots)
    result[Position.UTIL] = result.get(Position.UTIL, 0) + league.bench_hitting_estimate
    result[Position.P] = result.get(Position.P, 0) + league.bench_pitching_estimate
    return result


def _find_best_position(
    eligible: list[Position], remaining: dict[Position, int]
) -> Position | None:
    """Find the best position to assign a player to.

    Prefers positions with remaining slots. Among those, prefers
    the most scarce position (fewest remaining slots) to maximize value.
    Util is deprioritized — only used when no specific position slots remain.

    Args:
        eligible: Positions this player is eligible for.
        remaining: Remaining slot counts per position.

    Returns:
        The best position to assign, or None if no slots available.
    """
    # Filter to positions with remaining slots
    available = [p for p in eligible if remaining.get(p, 0) > 0]

    if not available:
        return None

    # Prefer specific positions over Util
    specific = [p for p in available if p != Position.UTIL]
    candidates = specific if specific else available

    # Pick the scarcest position (fewest remaining slots)
    return min(candidates, key=lambda p: remaining[p])

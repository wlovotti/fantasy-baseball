"""Replacement level calculation using projected-draft methodology."""

from __future__ import annotations

import pandas as pd

from config.league import LEAGUE, LeagueSettings
from config.positions import Position


def _position_slots(league: LeagueSettings) -> dict[Position, int]:
    """Build league-wide position slot counts from league settings.

    Args:
        league: League settings with per-team position counts.

    Returns:
        Dictionary mapping each Position to the total starter slots league-wide.
    """
    return {
        Position.C: league.catcher * league.num_teams,
        Position.FIRST: league.first_base * league.num_teams,
        Position.SECOND: league.second_base * league.num_teams,
        Position.THIRD: league.third_base * league.num_teams,
        Position.SS: league.shortstop * league.num_teams,
        Position.OF: league.outfield * league.num_teams,
        Position.UTIL: league.utility * league.num_teams,
        Position.P: league.pitcher * league.num_teams,
    }


def _first_pass_replacement(
    df: pd.DataFrame, league: LeagueSettings
) -> dict[Position, float]:
    """Compute independent replacement levels per position.

    For each specific position (excluding Util), the replacement level is the
    Nth-best eligible player's points, where N = starter slots for that position.
    These levels are only used to determine position hierarchy for multi-position
    assignment — not for final valuation.

    Args:
        df: Player DataFrame with 'points' and 'positions' columns.
        league: League settings controlling slot counts.

    Returns:
        Dictionary mapping each specific Position to its first-pass replacement level.
    """
    slots = _position_slots(league)
    levels: dict[Position, float] = {}
    for pos in Position:
        if pos == Position.UTIL:
            continue
        n = slots.get(pos, 0)
        if n == 0:
            levels[pos] = 0.0
            continue
        eligible = df[df["positions"].apply(lambda ps, p=pos: p in ps)]
        eligible_sorted = eligible.sort_values("points", ascending=False)
        if len(eligible_sorted) >= n:
            levels[pos] = eligible_sorted.iloc[n - 1]["points"]
        elif len(eligible_sorted) > 0:
            levels[pos] = eligible_sorted.iloc[-1]["points"]
        else:
            levels[pos] = 0.0
    return levels


def _assign_primary_position(
    positions: list[Position],
    first_pass_levels: dict[Position, float],
) -> Position | None:
    """Assign a player to the specific position with the lowest first-pass replacement.

    Lower replacement = weaker talent pool = player provides more marginal value there.
    Excludes Util from assignment. Returns None for Util-only players.

    Args:
        positions: Player's eligible positions.
        first_pass_levels: First-pass replacement levels per position.

    Returns:
        The scarcest eligible position, or None for Util-only players.
    """
    specific = [p for p in positions if p != Position.UTIL]
    if not specific:
        return None
    return min(specific, key=lambda p: first_pass_levels.get(p, 0))


def _build_drafted_pool(
    df: pd.DataFrame,
    league: LeagueSettings,
    first_pass_levels: dict[Position, float],
) -> pd.DataFrame:
    """Build the projected drafted pool respecting all roster constraints.

    Process:
    1. Assign each multi-position hitter to their scarcest position.
    2. Fill starter slots (scarcest position first).
    3. Fill Util + bench hitter slots from remaining hitters.
    4. Fill bench pitcher slots from remaining pitchers.
    5. Fill any remaining slots from best available players.

    Args:
        df: Full player DataFrame.
        league: League settings controlling roster construction.
        first_pass_levels: First-pass replacement levels for position assignment.

    Returns:
        DataFrame of drafted players (up to roster_size × num_teams) with a
        ``primary_pos`` column indicating each player's assigned position.
    """
    slots = _position_slots(league)

    hitters = df[df["player_type"] == "hitter"].copy()
    pitchers = df[df["player_type"] == "pitcher"].copy()

    # Assign primary position to each hitter
    hitters["primary_pos"] = hitters["positions"].apply(
        lambda ps: _assign_primary_position(ps, first_pass_levels)
    )

    drafted_indices: set[int] = set()

    # Fill specific hitting positions, scarcest first (lowest replacement)
    specific_positions = [p for p in Position if p not in (Position.UTIL, Position.P)]
    specific_positions.sort(key=lambda p: first_pass_levels.get(p, 0))

    for pos in specific_positions:
        n = slots.get(pos, 0)
        assigned = hitters[
            (hitters["primary_pos"] == pos)
            & (~hitters.index.isin(drafted_indices))
        ].sort_values("points", ascending=False)
        drafted_indices.update(assigned.head(n).index)

    # Fill pitcher starter slots
    pitcher_sorted = pitchers.sort_values("points", ascending=False)
    drafted_indices.update(
        pitcher_sorted.head(slots.get(Position.P, 0)).index
    )

    # Fill Util + bench hitter slots from remaining hitters
    util_bench_slots = slots.get(Position.UTIL, 0) + league.bench_hitting_estimate
    remaining_hitters = hitters[
        ~hitters.index.isin(drafted_indices)
    ].sort_values("points", ascending=False)
    drafted_indices.update(remaining_hitters.head(util_bench_slots).index)

    # Fill bench pitcher slots from remaining pitchers
    remaining_pitchers = pitchers[
        ~pitchers.index.isin(drafted_indices)
    ].sort_values("points", ascending=False)
    drafted_indices.update(
        remaining_pitchers.head(league.bench_pitching_estimate).index
    )

    # Fill any remaining slots (e.g., IL) from best available
    pool_size = league.roster_size * league.num_teams
    if len(drafted_indices) < pool_size:
        remaining = df[~df.index.isin(drafted_indices)].sort_values(
            "points", ascending=False
        )
        need = pool_size - len(drafted_indices)
        drafted_indices.update(remaining.head(need).index)

    # Build result with primary_pos for all drafted players
    result = df.loc[list(drafted_indices)].copy()
    # Merge hitter primary_pos assignments
    result["primary_pos"] = hitters["primary_pos"]
    # Pitchers are always P
    pitcher_mask = result["player_type"] == "pitcher"
    result.loc[pitcher_mask, "primary_pos"] = Position.P

    return result


def _final_replacement_levels(
    drafted_pool: pd.DataFrame,
) -> dict[Position, float]:
    """Derive final replacement levels from the drafted pool.

    Each drafted player counts toward exactly one specific position — their
    ``primary_pos`` (scarcest eligible position). This prevents multi-position
    players from artificially lowering replacement levels at positions they
    wouldn't actually be slotted into.

    Util replacement is the minimum points among all drafted hitters (since
    any hitter can fill a Util slot). Pitchers all count toward P.

    Args:
        drafted_pool: DataFrame of drafted players with ``primary_pos`` column.

    Returns:
        Dictionary mapping each Position to its final replacement level.
    """
    levels: dict[Position, float] = {}
    for pos in Position:
        if pos == Position.UTIL:
            # Any drafted hitter can fill Util
            eligible = drafted_pool[drafted_pool["player_type"] == "hitter"]
        else:
            # Only players assigned to this position count
            eligible = drafted_pool[drafted_pool["primary_pos"] == pos]
        if len(eligible) > 0:
            levels[pos] = eligible["points"].min()
        else:
            levels[pos] = 0.0
    return levels


def calculate_replacement_levels(
    df: pd.DataFrame,
    league: LeagueSettings = LEAGUE,
) -> dict[Position, float]:
    """Calculate replacement-level points using projected-draft methodology.

    Projects a realistic drafted pool respecting all roster constraints
    (position slots, Util, bench), then derives replacement levels from
    that pool. Each position's replacement level is the minimum points
    among drafted players eligible at that position.

    Algorithm:
    1. First-pass replacement levels (Nth-best at each position).
    2. Assign multi-position players to scarcest eligible position.
    3. Fill starter slots (scarcest position first).
    4. Fill Util + bench from remaining players.
    5. Final replacement = min points among drafted players assigned to each position.

    Args:
        df: Player DataFrame with 'points', 'positions', and 'player_type' columns.
        league: League settings controlling roster construction.

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

    first_pass = _first_pass_replacement(df, league)
    drafted_pool = _build_drafted_pool(df, league, first_pass)
    return _final_replacement_levels(drafted_pool)

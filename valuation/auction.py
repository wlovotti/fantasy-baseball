"""Convert value-above-replacement into auction dollar values."""

from __future__ import annotations

import pandas as pd

from config.league import LEAGUE, LeagueSettings
from config.positions import Position
from valuation.replacement import calculate_replacement_levels


def calculate_auction_values(
    df: pd.DataFrame,
    league: LeagueSettings = LEAGUE,
    replacement_levels: dict[Position, float] | None = None,
) -> pd.DataFrame:
    """Calculate auction dollar values for all players.

    Process:
    1. Determine replacement level per position
    2. For each player, VAR = points - replacement_level (for best position)
    3. Distribute total league budget proportionally to positive VAR
    4. $1 minimum for draftable players

    Args:
        df: Player DataFrame with 'points' and 'positions' columns.
        league: League settings for budget/team calculations.
        replacement_levels: Pre-calculated replacement levels (optional).

    Returns:
        DataFrame with 'replacement_level', 'var', and 'dollar_value' columns added,
        sorted by dollar_value descending.
    """
    df = df.copy()

    if replacement_levels is None:
        replacement_levels = calculate_replacement_levels(df, league=league)

    # Calculate each player's replacement level (best eligible position)
    df["replacement_level"] = df["positions"].apply(
        lambda positions: min(replacement_levels.get(p, 0) for p in positions)
    )

    # Value above replacement
    df["var"] = df["points"] - df["replacement_level"]

    # Only players with positive VAR are draftable
    total_positive_var = df.loc[df["var"] > 0, "var"].sum()
    total_budget = league.total_budget

    if total_positive_var > 0:
        # Count draftable players for $1 minimum floor
        draftable = df["var"] > 0
        num_draftable = draftable.sum()

        # Reserve $1 per draftable player, distribute rest by VAR share
        distributable = total_budget - num_draftable
        df.loc[draftable, "dollar_value"] = (
            df.loc[draftable, "var"] / total_positive_var * distributable + 1
        )
        df.loc[~draftable, "dollar_value"] = 0
    else:
        df["dollar_value"] = 0

    return df.sort_values("dollar_value", ascending=False).reset_index(drop=True)


def format_positions(positions: list[Position]) -> str:
    """Format a position list into a readable string.

    Excludes Util from display unless it's the only position.

    Args:
        positions: List of Position enums.

    Returns:
        Comma-separated position string.
    """
    display = [p.value for p in positions if p != Position.UTIL]
    if not display:
        display = [Position.UTIL.value]
    return ",".join(display)

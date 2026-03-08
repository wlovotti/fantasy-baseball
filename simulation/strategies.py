"""Bidding strategy factories for Monte Carlo draft simulation.

Provides three strategies for the user team:
- Static: bids at pre-computed model values (baseline)
- Personal: bids using custom league settings (e.g., bench_hitters=0)
- Dynamic: recalculates values after each user pick
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Callable

import pandas as pd

from config.league import LEAGUE, LeagueSettings
from config.positions import Position, parse_positions
from valuation.auction import calculate_auction_values
from valuation.replacement import calculate_replacement_levels


# Type alias for a bid strategy: given a player name, returns dollar value.
BidStrategy = Callable[[str], int]


def _parse_csv_positions(pos_str: str) -> list[Position]:
    """Parse a position string from the player values CSV.

    The CSV may store positions as simple values like 'P', 'OF', 'C,SS',
    which differ from FanGraphs format. This handles 'P' directly
    (since parse_positions only knows 'SP'/'RP') and falls back to
    parse_positions for multi-position strings.

    Args:
        pos_str: Raw position string from CSV.

    Returns:
        List of Position enums.
    """
    pos_str = pos_str.strip()
    if pos_str == "P":
        return [Position.P]
    result = parse_positions(pos_str)
    if not result and pos_str:
        # Try individual position lookup as enum value
        try:
            return [Position(pos_str)]
        except ValueError:
            pass
    return result


def load_player_dataframe(csv_path: str | Path) -> pd.DataFrame:
    """Load player values CSV into a DataFrame with parsed positions.

    The CSV must have columns: name, team, player_type, points, positions.
    The positions column is parsed into lists of Position enums.

    Args:
        csv_path: Path to the player values CSV file.

    Returns:
        DataFrame with parsed 'positions' column (list of Position enums).
    """
    df = pd.read_csv(csv_path)
    df["positions"] = df["positions"].apply(_parse_csv_positions)
    return df


def _revalue_remaining(df: pd.DataFrame, league: LeagueSettings) -> dict[str, int]:
    """Run the full valuation pipeline on a player DataFrame.

    Args:
        df: Player DataFrame with 'points', 'positions', 'player_type' columns.
        league: League settings for replacement level and auction calculation.

    Returns:
        Dictionary mapping player name to integer dollar value.
    """
    replacement_levels = calculate_replacement_levels(df, league=league)
    valued = calculate_auction_values(df, league=league, replacement_levels=replacement_levels)
    return dict(zip(valued["name"], valued["dollar_value"].astype(int)))


def static_strategy(players: list) -> BidStrategy:
    """Create a strategy that bids at pre-computed model values.

    This is the baseline strategy — identical to the current simulation behavior.
    Looks up each player's ``our_value`` from the SimPlayer list.

    Args:
        players: List of SimPlayer objects with our_value attributes.

    Returns:
        Callable that maps player name to its pre-computed dollar value.
    """
    value_map = {p.name: p.our_value for p in players}

    def bid(player_name: str) -> int:
        """Return pre-computed model value for the player."""
        return value_map.get(player_name, 1)

    return bid


def personal_strategy(
    player_df: pd.DataFrame,
    league_override: LeagueSettings | None = None,
) -> BidStrategy:
    """Create a strategy using custom league settings for valuation.

    Runs the full valuation pipeline once at init time with the overridden
    settings (e.g., bench_hitters=0) to produce alternative dollar values.

    Args:
        player_df: Player DataFrame with parsed positions column.
        league_override: Custom league settings. Defaults to bench_hitters=0.

    Returns:
        Callable that maps player name to the recomputed dollar value.
    """
    if league_override is None:
        league_override = LeagueSettings(bench_hitters=0)

    value_map = _revalue_remaining(player_df, league_override)

    def bid(player_name: str) -> int:
        """Return personal-valuation dollar value for the player."""
        return value_map.get(player_name, 1)

    return bid


def dynamic_strategy(
    player_df: pd.DataFrame,
    league: LeagueSettings = LEAGUE,
) -> tuple[BidStrategy, Callable[[str], None]]:
    """Create a strategy that recalculates values after each user pick.

    Returns both a bid function and an on_pick callback. The callback should
    be called with the drafted player's name after each user pick to trigger
    revaluation of the remaining pool.

    Args:
        player_df: Player DataFrame with parsed positions column.
        league: League settings for valuation pipeline.

    Returns:
        Tuple of (bid_strategy, on_pick_callback).
        - bid_strategy: maps player name to current dynamic dollar value.
        - on_pick_callback: call with player name after each user pick.
    """
    remaining_df = player_df.copy()
    value_map = _revalue_remaining(remaining_df, league)

    # Use a mutable container so closures share state
    state = {"values": value_map, "df": remaining_df}

    def bid(player_name: str) -> int:
        """Return current dynamic dollar value for the player."""
        return state["values"].get(player_name, 1)

    def on_pick(player_name: str) -> None:
        """Remove a drafted player and revalue the remaining pool."""
        df = state["df"]
        state["df"] = df[df["name"] != player_name].copy()
        if len(state["df"]) > 0:
            state["values"] = _revalue_remaining(state["df"], league)

    return bid, on_pick

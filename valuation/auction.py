"""Convert value-above-replacement into auction dollar values."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from config.league import LEAGUE, LeagueSettings
from config.positions import Position
from valuation.replacement import calculate_replacement_levels


def _round_to_integers(values: pd.Series, total: int) -> pd.Series:
    """Round fractional dollar values to integers preserving the total.

    Uses largest-remainder method: floor all values, then distribute the
    leftover dollars one at a time to the players with the largest fractional
    remainders.

    Args:
        values: Series of fractional dollar values (all >= 1 for draftable).
        total: Target integer total that rounded values must sum to.

    Returns:
        Series of integer dollar values summing exactly to *total*.
    """
    floors = np.floor(values).astype(int)
    remainders = values - floors
    shortfall = total - floors.sum()

    # Award extra $1 to the players with the largest remainders
    if shortfall > 0:
        top_indices = remainders.nlargest(shortfall).index
        floors.loc[top_indices] += 1

    return floors


def _position_replacement(
    positions: list[Position],
    replacement_levels: dict[Position, float],
) -> float:
    """Get replacement level using specific positions, falling back to Util.

    Excludes Util when a player has real positional eligibility so that
    positional scarcity is reflected in dollar values.  Util-only players
    still use the Util replacement level.

    Args:
        positions: Player's eligible positions (including Util).
        replacement_levels: Mapping of position to replacement-level points.

    Returns:
        The minimum replacement level across the player's relevant positions.
    """
    specific = [p for p in positions if p != Position.UTIL]
    candidates = specific if specific else positions
    return min(replacement_levels.get(p, 0) for p in candidates)


def _allocation_var(
    points: float,
    position_repl: float,
    pooled_repl: float,
    is_hitter: bool,
) -> float:
    """Compute clamped allocation weight for dollar distribution.

    For hitters, uses a two-part formula that prevents deep/Util positions
    from inflating dollar values:
      base_var    = points - pooled_replacement  (position-blind value)
      pos_premium = max(0, pooled_repl - position_repl)  (scarcity bonus)
      allocation_var = max(0, base_var) + pos_premium

    For scarce positions (position_repl < pooled_repl), this simplifies to
    the full position-specific VAR. For deep/Util positions, the premium
    clamps to 0 so only pooled VAR is used.

    Pitchers are unaffected — their allocation_var equals their normal VAR.

    Args:
        points: Player's projected fantasy points.
        position_repl: Position-specific replacement level.
        pooled_repl: Pooled hitter replacement level.
        is_hitter: Whether the player is a hitter.

    Returns:
        Clamped allocation weight (>= 0).
    """
    if not is_hitter:
        return max(0, points - position_repl)

    base_var = points - pooled_repl
    pos_premium = max(0, pooled_repl - position_repl)
    return max(0, base_var) + pos_premium


def calculate_auction_values(
    df: pd.DataFrame,
    league: LeagueSettings = LEAGUE,
    replacement_levels: dict[Position, float] | None = None,
) -> pd.DataFrame:
    """Calculate auction dollar values for all players.

    Process:
    1. Determine replacement level per position
    2. For each player, VAR = points - replacement_level (for best position)
    3. Compute clamped allocation_var to prevent Util/deep-position inflation
    4. Distribute total league budget proportionally to positive allocation_var
    5. $1 minimum for draftable players
    6. Round to whole dollars using largest-remainder method

    Args:
        df: Player DataFrame with 'points' and 'positions' columns.
        league: League settings for budget/team calculations.
        replacement_levels: Pre-calculated replacement levels (optional).

    Returns:
        DataFrame with 'replacement_level', 'var', 'allocation_var', and
        'dollar_value' columns added, sorted by dollar_value descending.
    """
    df = df.copy()

    if replacement_levels is None:
        replacement_levels = calculate_replacement_levels(df, league=league)

    # Calculate each player's replacement level (best eligible position)
    df["replacement_level"] = df["positions"].apply(
        lambda positions: _position_replacement(positions, replacement_levels)
    )

    # Value above replacement (position-specific, used for ranking/display)
    df["var"] = df["points"] - df["replacement_level"]

    # Pooled hitter replacement level for allocation clamping
    hitter_mask = df["player_type"] == "hitter"
    total_hitting_slots = (
        league.total_hitting_slots_league + league.bench_hitting_estimate
    )
    hitters_by_pts = df.loc[hitter_mask, "points"].sort_values(ascending=False)
    if len(hitters_by_pts) >= total_hitting_slots:
        pooled_repl = hitters_by_pts.iloc[total_hitting_slots - 1]
    else:
        pooled_repl = hitters_by_pts.iloc[-1] if len(hitters_by_pts) > 0 else 0

    # Clamped allocation weight: prevents deep/Util inflation
    df["allocation_var"] = df.apply(
        lambda row: _allocation_var(
            row["points"],
            row["replacement_level"],
            pooled_repl,
            row["player_type"] == "hitter",
        ),
        axis=1,
    )

    # Cap draftable players to actual roster spots
    max_draftable = league.roster_size * league.num_teams
    positive_mask = df["allocation_var"] > 0
    if positive_mask.sum() > max_draftable:
        # Keep only the top max_draftable by allocation_var
        threshold = (
            df.loc[positive_mask, "allocation_var"]
            .nlargest(max_draftable)
            .iloc[-1]
        )
        above_threshold = df["allocation_var"] > threshold
        at_threshold = df["allocation_var"] == threshold
        needed = max_draftable - above_threshold.sum()
        # If ties at threshold, keep first `needed` by points (tiebreaker)
        if at_threshold.sum() > needed:
            tie_indices = df.loc[at_threshold].nlargest(needed, "points").index
            keep = above_threshold.copy()
            keep.loc[tie_indices] = True
        else:
            keep = above_threshold | at_threshold
        df.loc[~keep, "allocation_var"] = 0

    # Only players with positive allocation_var are draftable
    total_positive_alloc = df.loc[df["allocation_var"] > 0, "allocation_var"].sum()
    total_budget = league.total_budget

    if total_positive_alloc > 0:
        # Count draftable players for $1 minimum floor
        draftable = df["allocation_var"] > 0
        num_draftable = draftable.sum()

        # Reserve $1 per draftable player, distribute rest by allocation_var share
        distributable = total_budget - num_draftable
        df.loc[draftable, "dollar_value"] = (
            df.loc[draftable, "allocation_var"]
            / total_positive_alloc
            * distributable
            + 1
        )
        df.loc[~draftable, "dollar_value"] = 0

        # Round to whole dollars, preserving total budget
        df.loc[draftable, "dollar_value"] = _round_to_integers(
            df.loc[draftable, "dollar_value"], total_budget
        )
    else:
        df["dollar_value"] = 0

    # Pooled Util value: what each hitter is worth ignoring positional scarcity
    df["util_value"] = 0
    if hitter_mask.any() and total_positive_alloc > 0:
        util_var = df.loc[hitter_mask, "points"] - pooled_repl
        pitcher_mask = df["player_type"] == "pitcher"
        pitcher_var = df.loc[pitcher_mask, "var"].clip(lower=0)

        # Combine hitter util_var and pitcher var for unified ranking
        combined_var = pd.Series(0.0, index=df.index)
        combined_var.loc[util_var.index] = util_var.clip(lower=0)
        combined_var.loc[pitcher_var.index] = pitcher_var

        # Cap to max_draftable roster spots
        positive_combined = combined_var > 0
        if positive_combined.sum() > max_draftable:
            util_threshold = (
                combined_var[positive_combined]
                .nlargest(max_draftable)
                .iloc[-1]
            )
            above = combined_var > util_threshold
            at = combined_var == util_threshold
            needed_util = max_draftable - above.sum()
            if at.sum() > needed_util:
                tie_idx = df.loc[at].nlargest(needed_util, "points").index
                keep_util = above.copy()
                keep_util.loc[tie_idx] = True
            else:
                keep_util = above | at
            combined_var.loc[~keep_util] = 0

        util_pos = combined_var.loc[hitter_mask] > 0
        if util_pos.any():
            util_var_capped = combined_var.loc[hitter_mask]
            pitcher_var_sum = combined_var.loc[pitcher_mask].sum()
            util_total_var = util_var_capped[util_pos].sum() + pitcher_var_sum
            util_num_draftable = (combined_var > 0).sum()
            util_distributable = total_budget - util_num_draftable

            raw_util = (
                util_var_capped[util_pos] / util_total_var * util_distributable
                + 1
            )
            df.loc[raw_util.index, "util_value"] = raw_util.round().astype(int)

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

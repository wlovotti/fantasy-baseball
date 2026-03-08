"""Convert player projections into projected fantasy points."""

import pandas as pd

from config.scoring import (
    BATTING_SCORING,
    BattingScoring,
    PITCHING_SCORING,
    PitchingScoring,
)


def calculate_hitter_points(
    row: pd.Series, scoring: BattingScoring = BATTING_SCORING
) -> float:
    """Calculate projected fantasy points for a hitter.

    Skips rare bonus events (cycle, grand slam) as they are too
    unpredictable to project and have minimal impact on relative values.

    Args:
        row: A row from the hitters DataFrame with standardized column names.
        scoring: Batting scoring rules to apply.

    Returns:
        Total projected fantasy points.
    """
    return (
        row.get("single", 0) * scoring.single
        + row.get("double", 0) * scoring.double
        + row.get("triple", 0) * scoring.triple
        + row.get("hr", 0) * scoring.home_run
        + row.get("r", 0) * scoring.run
        + row.get("rbi", 0) * scoring.rbi
        + row.get("bb", 0) * scoring.walk
        + row.get("hbp", 0) * scoring.hbp
        + row.get("sb", 0) * scoring.stolen_base
        + row.get("cs", 0) * scoring.caught_stealing
        + row.get("so", 0) * scoring.strikeout
    )


def calculate_pitcher_points(
    row: pd.Series, scoring: PitchingScoring = PITCHING_SCORING
) -> float:
    """Calculate projected fantasy points for a pitcher.

    Skips rare bonus events (no-hitter, perfect game) as they are too
    unpredictable to project.

    Args:
        row: A row from the pitchers DataFrame with standardized column names.
        scoring: Pitching scoring rules to apply.

    Returns:
        Total projected fantasy points.
    """
    return (
        row.get("ip", 0) * scoring.inning_pitched
        + row.get("w", 0) * scoring.win
        + row.get("l", 0) * scoring.loss
        + row.get("sv", 0) * scoring.save
        + row.get("hld", 0) * scoring.hold
        + row.get("er", 0) * scoring.earned_run
        + row.get("so", 0) * scoring.strikeout
        + row.get("h_allowed", 0) * scoring.hit_allowed
        + row.get("bb_allowed", 0) * scoring.walk_allowed
        + row.get("qs", 0) * scoring.quality_start
        + row.get("cg", 0) * scoring.complete_game
        + row.get("sho", 0) * scoring.shutout
        + row.get("bs", 0) * scoring.blown_save
    )


def add_points_column(df: pd.DataFrame) -> pd.DataFrame:
    """Add a 'points' column to a player DataFrame.

    Automatically detects hitters vs pitchers via the 'player_type' column.

    Args:
        df: Player DataFrame with standardized stat columns and 'player_type'.

    Returns:
        Same DataFrame with 'points' column added.
    """
    df = df.copy()
    mask_hitter = df["player_type"] == "hitter"
    mask_pitcher = df["player_type"] == "pitcher"

    df.loc[mask_hitter, "points"] = df[mask_hitter].apply(
        calculate_hitter_points, axis=1
    )
    df.loc[mask_pitcher, "points"] = df[mask_pitcher].apply(
        calculate_pitcher_points, axis=1
    )
    return df

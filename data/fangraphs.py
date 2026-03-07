"""Parse FanGraphs ATC projection CSV exports."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from config.positions import Position, parse_positions

# Standard column name mappings from FanGraphs export
HITTER_COLUMN_MAP = {
    "Name": "name",
    "Team": "team",
    "PA": "pa",
    "AB": "ab",
    "H": "h",
    "1B": "single",
    "2B": "double",
    "3B": "triple",
    "HR": "hr",
    "R": "r",
    "RBI": "rbi",
    "BB": "bb",
    "HBP": "hbp",
    "SB": "sb",
    "CS": "cs",
    "SO": "so",
}

PITCHER_COLUMN_MAP = {
    "Name": "name",
    "Team": "team",
    "IP": "ip",
    "W": "w",
    "L": "l",
    "SV": "sv",
    "HLD": "hld",
    "ER": "er",
    "SO": "so",
    "H": "h_allowed",
    "BB": "bb_allowed",
    "HBP": "hbp_allowed",
    "QS": "qs",
    "CG": "cg",
    "ShO": "sho",
    "BS": "bs",
}


def load_hitters(csv_path: str | Path) -> pd.DataFrame:
    """Load and standardize a FanGraphs hitter projection CSV.

    Calculates singles if not present (H - 2B - 3B - HR).
    Parses position eligibility from the FanGraphs position column.

    Args:
        csv_path: Path to the FanGraphs hitter CSV export.

    Returns:
        DataFrame with standardized column names and parsed positions.
    """
    df = pd.read_csv(csv_path)

    # Find the position column (FanGraphs uses various names)
    pos_col = None
    for candidate in ["Pos", "Position", "POS", "Team/Pos"]:
        if candidate in df.columns:
            pos_col = candidate
            break

    # Rename known columns
    rename = {k: v for k, v in HITTER_COLUMN_MAP.items() if k in df.columns}
    df = df.rename(columns=rename)

    # Calculate singles if not already present
    if "single" not in df.columns and all(
        c in df.columns for c in ("h", "double", "triple", "hr")
    ):
        df["single"] = df["h"] - df["double"] - df["triple"] - df["hr"]

    # Parse positions
    if pos_col and pos_col in df.columns:
        df["positions"] = df[pos_col].fillna("DH").apply(parse_positions)
    elif "positions" not in df.columns:
        # Default to Util-only if no position info available
        df["positions"] = [[Position.UTIL]] * len(df)

    # Fill missing stat columns with 0
    for col in ["single", "double", "triple", "hr", "r", "rbi", "bb", "hbp",
                 "sb", "cs", "so", "pa", "ab", "h"]:
        if col not in df.columns:
            df[col] = 0

    df["player_type"] = "hitter"
    return df


def load_pitchers(csv_path: str | Path) -> pd.DataFrame:
    """Load and standardize a FanGraphs pitcher projection CSV.

    Missing columns (HLD, QS, BS, CG, ShO) are filled with 0.

    Args:
        csv_path: Path to the FanGraphs pitcher CSV export.

    Returns:
        DataFrame with standardized column names.
    """
    df = pd.read_csv(csv_path)

    # Rename known columns
    rename = {k: v for k, v in PITCHER_COLUMN_MAP.items() if k in df.columns}
    df = df.rename(columns=rename)

    # Fill missing stat columns with 0
    for col in ["ip", "w", "l", "sv", "hld", "er", "so", "h_allowed",
                 "bb_allowed", "hbp_allowed", "qs", "cg", "sho", "bs"]:
        if col not in df.columns:
            df[col] = 0

    df["positions"] = [[Position.P]] * len(df)
    df["player_type"] = "pitcher"
    return df

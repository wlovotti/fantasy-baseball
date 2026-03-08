#!/usr/bin/env python3
"""Interactive CLI to look up player auction values from a generated CSV.

For Util-only players, displays util_value as the primary value.
For players with real positions, displays dollar_value.
"""

import sys
from pathlib import Path

import click
import pandas as pd
from rapidfuzz import process, fuzz

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_values(csv_path: str) -> pd.DataFrame:
    """Load player values CSV into a DataFrame."""
    return pd.read_csv(csv_path)


def is_util_only(positions: str) -> bool:
    """Return True if the player's only position is Util."""
    return positions.strip() == "Util"


def lookup(df: pd.DataFrame, query: str, top: int = 5) -> pd.DataFrame:
    """Fuzzy-match a player name and return top matches."""
    results = process.extract(
        query, df["name"].tolist(), scorer=fuzz.WRatio, limit=top
    )
    indices = [df.index[df["name"] == name].tolist()[0] for name, score, _ in results]
    return df.loc[indices].copy()


def format_result(row: pd.Series) -> str:
    """Format a single player result line."""
    util_only = is_util_only(row["positions"])
    value = int(row["util_value"]) if util_only else int(row["dollar_value"])
    label = "util" if util_only else "pos"
    return (
        f"  {row['name']:<25} {row['positions']:<14} "
        f"${value:>3} ({label})  |  "
        f"pts: {row['points']:.0f}  var: {row['var']:.0f}  "
        f"pos${int(row['dollar_value'])}  util${int(row['util_value'])}"
    )


@click.command()
@click.argument(
    "csv_path",
    type=click.Path(exists=True),
    default="player_values.csv",
)
def main(csv_path: str) -> None:
    """Interactive player value lookup.

    CSV_PATH: Path to player_values.csv (default: player_values.csv).
    """
    df = load_values(csv_path)
    click.echo(f"Loaded {len(df)} players from {csv_path}")
    click.echo("Type a player name to look up (Ctrl+C or 'q' to quit)\n")

    while True:
        try:
            query = click.prompt("Player", prompt_suffix="> ").strip()
        except (click.Abort, EOFError):
            click.echo("\nBye!")
            break

        if query.lower() in ("q", "quit", "exit"):
            click.echo("Bye!")
            break

        if not query:
            continue

        matches = lookup(df, query)
        click.echo()
        for _, row in matches.iterrows():
            click.echo(format_result(row))
        click.echo()


if __name__ == "__main__":
    main()

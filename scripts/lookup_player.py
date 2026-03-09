#!/usr/bin/env python3
"""Interactive CLI to look up player auction values from a generated CSV.

Shows dollar_value as the primary value for all players, with util_value
shown alongside for hitters as a reference when filling Util slots.
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


MIN_SCORE = 70


def lookup(
    df: pd.DataFrame, query: str, top: int = 5, min_score: float = MIN_SCORE
) -> pd.DataFrame:
    """Fuzzy-match a player name and return top matches above a similarity threshold.

    Uses the DataFrame index directly from rapidfuzz results to correctly
    handle players with identical names (e.g. dual hitter/pitcher entries).
    Results below *min_score* are filtered out to avoid showing unrelated players.
    """
    names = {idx: name for idx, name in enumerate(df["name"].tolist())}
    results = process.extract(
        query, names, scorer=fuzz.WRatio, limit=top
    )
    indices = [idx for _, score, idx in results if score >= min_score]
    if not indices:
        return df.iloc[:0].copy()
    return df.iloc[indices].copy()


def format_result(row: pd.Series) -> str:
    """Format a single player result line.

    Shows dollar_value as the primary value, with util_value for hitters
    as a secondary reference for Util slot evaluation.
    """
    value = int(row["dollar_value"])
    util = int(row["util_value"])
    util_suffix = f"  Util: ${util}" if util > 0 else ""
    return f"  {row['name']:<25} {row['positions']:<14} ${value:>3}{util_suffix}"


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
        if matches.empty:
            click.echo("  No matches found.")
        else:
            for _, row in matches.iterrows():
                click.echo(format_result(row))
        click.echo()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""CLI: Upload auction values to Yahoo Fantasy."""

import sys
from pathlib import Path

import click
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yahoo.league_client import get_league, fetch_yahoo_players, match_players
from yahoo.upload import upload_values


@click.command()
@click.argument("values_csv", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Match players but don't upload")
@click.option("--threshold", default=90, help="Fuzzy match threshold (default: 90)")
def main(values_csv: str, dry_run: bool, threshold: int) -> None:
    """Upload auction values from VALUES_CSV to Yahoo Fantasy.

    VALUES_CSV: Path to the player values CSV (output of generate_values.py).
    """
    click.echo("Loading player values...")
    values_df = pd.read_csv(values_csv)
    click.echo(f"  {len(values_df)} valued players")

    click.echo("Connecting to Yahoo Fantasy...")
    league = get_league()

    click.echo("Fetching Yahoo player list...")
    yahoo_df = fetch_yahoo_players(league)
    click.echo(f"  {len(yahoo_df)} Yahoo players")

    click.echo("Matching players...")
    matched = match_players(values_df, yahoo_df, score_threshold=threshold, league=league)
    n_matched = matched["yahoo_id"].notna().sum()
    click.echo(f"  {n_matched}/{len(values_df)} players matched")

    if dry_run:
        click.echo("\nDry run — not uploading. Top 20 matches:")
        for _, row in matched.head(20).iterrows():
            status = "MATCHED" if pd.notna(row["yahoo_id"]) else "UNMATCHED"
            click.echo(
                f"  [{status}] {row['name']} → ${row['dollar_value']:.0f} "
                f"(score: {row['match_score']:.0f})"
            )
        return

    click.echo("Uploading values to Yahoo...")
    result = upload_values(league, matched)
    click.echo(
        f"\nDone! Uploaded: {result['uploaded']}, Skipped: {result['skipped']}"
    )


if __name__ == "__main__":
    main()

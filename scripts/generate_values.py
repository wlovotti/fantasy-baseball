#!/usr/bin/env python3
"""CLI: Generate auction values using Yahoo positions + FanGraphs projections.

Fetches real position eligibility from the Yahoo Fantasy API and merges it
with FanGraphs projections for accurate replacement-level calculations.
"""

import sys
from pathlib import Path
from typing import Optional

import click
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.league import LEAGUE, LeagueSettings
from data.fangraphs import load_hitters, load_pitchers
from data.yahoo_positions import fetch_and_merge_positions
from valuation.auction import calculate_auction_values, format_positions
from valuation.names import disambiguate_player_names
from valuation.points import add_points_column
from yahoo.auth import get_yahoo_auth
from yahoo.league_client import get_league


@click.command()
@click.argument("hitters_csv", type=click.Path(exists=True))
@click.argument("pitchers_csv", type=click.Path(exists=True))
@click.option(
    "--output", "-o",
    default="player_values.csv",
    help="Output CSV path (default: player_values.csv)",
)
@click.option("--top", "-n", default=50, help="Number of top players to display")
@click.option(
    "--threshold", "-t",
    default=90,
    help="Fuzzy match score threshold (0-100, default: 90)",
)
@click.option(
    "--bench-hitters",
    type=int,
    default=None,
    help="Override bench hitters per team (default: proportional estimate)",
)
def main(
    hitters_csv: str,
    pitchers_csv: str,
    output: str,
    top: int,
    threshold: int,
    bench_hitters: Optional[int],
) -> None:
    """Generate auction values using Yahoo positions + FanGraphs projections.

    HITTERS_CSV: Path to FanGraphs hitter projections CSV.
    PITCHERS_CSV: Path to FanGraphs pitcher projections CSV.
    """
    # Load projections
    click.echo("Loading hitter projections...")
    hitters = load_hitters(hitters_csv)
    click.echo(f"  Loaded {len(hitters)} hitters")

    click.echo("Loading pitcher projections...")
    pitchers = load_pitchers(pitchers_csv)
    click.echo(f"  Loaded {len(pitchers)} pitchers")

    # Fetch Yahoo positions and merge into hitters
    click.echo("Authenticating with Yahoo...")
    league = get_league()

    click.echo("Fetching and merging Yahoo positions...")
    hitters = fetch_and_merge_positions(hitters, league, threshold=threshold)

    # Combine, disambiguate dual-entry players (e.g. Ohtani), and calculate points
    all_players = pd.concat([hitters, pitchers], ignore_index=True)
    all_players = disambiguate_player_names(all_players)
    all_players = add_points_column(all_players)

    # Build league settings with optional bench override
    if bench_hitters is not None:
        league_settings = LeagueSettings(bench_hitters=bench_hitters)
        click.echo(f"Using bench hitters override: {bench_hitters}/team "
                   f"({bench_hitters * league_settings.num_teams} league-wide)")
    else:
        league_settings = LEAGUE

    # Calculate auction values
    click.echo("Calculating auction values...")
    valued = calculate_auction_values(all_players, league=league_settings)

    # Display top players
    click.echo(f"\nTop {top} players by auction value:")
    click.echo(f"{'Rank':<5} {'Name':<25} {'Pos':<12} {'Points':>8} {'Value':>7} {'Util':>6}")
    click.echo("-" * 67)

    for i, (_, row) in enumerate(valued.head(top).iterrows(), 1):
        pos_str = format_positions(row["positions"])
        click.echo(
            f"{i:<5} {row['name']:<25} {pos_str:<12} "
            f"{row['points']:>8.1f} ${row['dollar_value']:>6.0f} "
            f"${row['util_value']:>5.0f}"
        )

    # Summary stats
    draftable = valued[valued["dollar_value"] > 0]
    click.echo(f"\nDraftable players: {len(draftable)}")
    click.echo(f"Total dollar values: ${draftable['dollar_value'].sum():,.0f}")

    # Export to CSV
    export_cols = ["name", "team", "player_type", "points", "replacement_level",
                   "var", "allocation_var", "dollar_value", "util_value"]
    export_df = valued[valued["dollar_value"] > 0][
        [c for c in export_cols if c in valued.columns]
    ].copy()
    export_df["positions"] = valued.loc[export_df.index, "positions"].apply(
        format_positions
    )
    export_df.to_csv(output, index=False)
    click.echo(f"\nValues exported to {output}")


if __name__ == "__main__":
    main()

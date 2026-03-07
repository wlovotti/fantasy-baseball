#!/usr/bin/env python3
"""CLI: Generate auction dollar values from FanGraphs projection CSVs."""

import sys
from pathlib import Path

import click
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.fangraphs import load_hitters, load_pitchers
from valuation.auction import calculate_auction_values, format_positions
from valuation.points import add_points_column


@click.command()
@click.argument("hitters_csv", type=click.Path(exists=True))
@click.argument("pitchers_csv", type=click.Path(exists=True))
@click.option(
    "--output", "-o",
    default="player_values.csv",
    help="Output CSV path (default: player_values.csv)",
)
@click.option("--top", "-n", default=50, help="Number of top players to display")
def main(hitters_csv: str, pitchers_csv: str, output: str, top: int) -> None:
    """Generate auction dollar values from FanGraphs ATC projection CSVs.

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

    # Combine and calculate points
    all_players = pd.concat([hitters, pitchers], ignore_index=True)
    all_players = add_points_column(all_players)

    # Calculate auction values
    click.echo("Calculating auction values...")
    valued = calculate_auction_values(all_players)

    # Display top players
    click.echo(f"\nTop {top} players by auction value:")
    click.echo(f"{'Rank':<5} {'Name':<25} {'Pos':<12} {'Points':>8} {'Value':>7}")
    click.echo("-" * 60)

    for i, (_, row) in enumerate(valued.head(top).iterrows(), 1):
        pos_str = format_positions(row["positions"])
        click.echo(
            f"{i:<5} {row['name']:<25} {pos_str:<12} {row['points']:>8.1f} ${row['dollar_value']:>6.1f}"
        )

    # Summary stats
    draftable = valued[valued["dollar_value"] > 0]
    click.echo(f"\nDraftable players: {len(draftable)}")
    click.echo(f"Total dollar values: ${draftable['dollar_value'].sum():,.0f}")

    # Export to CSV
    export_cols = ["name", "team", "player_type", "points", "replacement_level",
                   "var", "dollar_value"]
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

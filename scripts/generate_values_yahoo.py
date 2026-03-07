#!/usr/bin/env python3
"""CLI: Generate auction values using Yahoo position eligibility data.

Fetches real position eligibility from the Yahoo Fantasy API and merges it
with FanGraphs projections for accurate replacement-level calculations.
"""

import sys
from pathlib import Path

import click
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.positions import Position, parse_positions
from data.fangraphs import load_hitters, load_pitchers
from valuation.auction import calculate_auction_values, format_positions
from valuation.points import add_points_column
from yahoo.auth import get_yahoo_auth
from yahoo.league_client import fetch_yahoo_players, get_league, match_players


def merge_yahoo_positions(
    hitters: pd.DataFrame,
    yahoo_df: pd.DataFrame,
    score_threshold: int = 90,
) -> tuple[pd.DataFrame, list[str]]:
    """Replace hitter positions with Yahoo eligibility via fuzzy matching.

    Matched hitters get their Yahoo position eligibility parsed into Position
    enums. Unmatched hitters fall back to [UTIL].

    Args:
        hitters: Hitter DataFrame from load_hitters().
        yahoo_df: Yahoo player DataFrame from fetch_yahoo_players().
        score_threshold: Minimum fuzzy match score (0-100) to accept.

    Returns:
        Tuple of (updated hitters DataFrame, list of unmatched player names).
    """
    if yahoo_df.empty:
        click.echo("  Warning: No Yahoo players found, keeping default positions")
        return hitters, hitters["name"].tolist()

    # Build name→position map, preferring non-pitcher entries for hitters.
    # Yahoo lists dual players like Ohtani twice (Batter + Pitcher) with the
    # same normalized name; we want the batter entry when matching hitters.
    yahoo_pos_map: dict[str, str] = {}
    for _, yrow in yahoo_df.iterrows():
        name = yrow["yahoo_name"]
        pos = yrow["position"]
        if name not in yahoo_pos_map or yahoo_pos_map[name] == "P":
            yahoo_pos_map[name] = pos
    yahoo_names = list(yahoo_pos_map.keys())

    from rapidfuzz import fuzz, process

    hitters = hitters.copy()
    matched_count = 0
    unmatched_names = []

    for idx, row in hitters.iterrows():
        result = process.extractOne(
            row["name"], yahoo_names, scorer=fuzz.token_sort_ratio
        )
        if result and result[1] >= score_threshold:
            yahoo_pos_str = yahoo_pos_map[result[0]]
            parsed = parse_positions(yahoo_pos_str)
            if parsed:
                hitters.at[idx, "positions"] = parsed
                matched_count += 1
            else:
                hitters.at[idx, "positions"] = [Position.UTIL]
                unmatched_names.append(row["name"])
        else:
            hitters.at[idx, "positions"] = [Position.UTIL]
            unmatched_names.append(row["name"])

    click.echo(f"  Matched {matched_count}/{len(hitters)} hitters to Yahoo positions")
    if unmatched_names:
        click.echo(f"  Unmatched ({len(unmatched_names)}):")
        for name in unmatched_names[:10]:
            click.echo(f"    - {name}")
        if len(unmatched_names) > 10:
            click.echo(f"    ... and {len(unmatched_names) - 10} more")

    return hitters, unmatched_names


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
def main(
    hitters_csv: str,
    pitchers_csv: str,
    output: str,
    top: int,
    threshold: int,
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

    # Fetch Yahoo positions
    click.echo("Authenticating with Yahoo...")
    league = get_league()

    click.echo("Fetching Yahoo player positions...")
    yahoo_df = fetch_yahoo_players(league)
    click.echo(f"  Fetched {len(yahoo_df)} players from Yahoo")

    # First pass: merge Yahoo positions into hitters
    click.echo("Matching hitter positions from Yahoo...")
    hitters, unmatched_names = merge_yahoo_positions(
        hitters, yahoo_df, score_threshold=threshold
    )

    # Second pass: search Yahoo for unmatched hitters (catches dual-eligible
    # players like Ohtani who have synthetic IDs)
    if unmatched_names:
        last_names = list({n.split()[-1] for n in unmatched_names})
        click.echo(f"Searching Yahoo for {len(last_names)} unmatched last names...")
        yahoo_df = fetch_yahoo_players(league, search_names=last_names)
        click.echo(f"  Player pool now {len(yahoo_df)} after search")
        hitters, still_unmatched = merge_yahoo_positions(
            hitters, yahoo_df, score_threshold=threshold
        )

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
            f"{i:<5} {row['name']:<25} {pos_str:<12} "
            f"{row['points']:>8.1f} ${row['dollar_value']:>6.1f}"
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

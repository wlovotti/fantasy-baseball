#!/usr/bin/env python3
"""Analyze past Yahoo drafts for bench calibration and position valuation insights.

Examines actual draft results from past seasons to determine:
- Bench hitter allocation (existing calibration)
- Position-level spending patterns and market premiums
- Hitter/pitcher budget splits and correlation with standings
- Price drop-off curves revealing positional scarcity
- Actionable recommendations for draft strategy
"""

import sys
from pathlib import Path
from typing import Optional

import click
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.draft_history import (
    assign_primary_position,
    hitter_pitcher_split,
    overpay_recommendations,
    position_spend_summary,
    price_dropoff_by_position,
    spending_vs_standings,
    user_team_report,
)
from config.league import LEAGUE
from yahoo.auth import get_yahoo_auth


def _get_game_and_leagues(oauth, seasons: list[int]) -> list[tuple[int, object]]:
    """Discover Yahoo league objects for the given past seasons.

    Args:
        oauth: Authenticated Yahoo OAuth2 session.
        seasons: List of MLB season years to look up.

    Returns:
        List of (year, league_object) tuples.
    """
    import yahoo_fantasy_api as yfa

    game = yfa.Game(oauth, "mlb")

    leagues = []
    for year in seasons:
        try:
            league_ids = game.league_ids(year=year)
        except Exception as e:
            click.echo(f"  Warning: could not find leagues for {year}: {e}")
            continue
        for lid in league_ids:
            league = game.to_league(lid)
            leagues.append((year, league))

    return leagues


def _fetch_team_names(league) -> dict[str, str]:
    """Fetch team key to team name mapping for a league.

    Args:
        league: A yahoo_fantasy_api League object.

    Returns:
        Dictionary mapping team_key to team_name.
    """
    teams = league.teams()
    return {key: info["name"] for key, info in teams.items()}


def _fetch_standings(league, year: int) -> list[dict]:
    """Fetch final standings for a league season.

    Args:
        league: A yahoo_fantasy_api League object.
        year: Season year.

    Returns:
        List of dicts with season, team_key, team_name, final_rank.
    """
    standings = league.standings()
    results = []
    for idx, team in enumerate(standings, start=1):
        results.append({
            "season": year,
            "team_key": team["team_key"],
            "team_name": team["name"],
            "final_rank": int(team.get("rank", idx)),
        })
    return results


def _collect_draft_picks(league, year: int, team_names: dict[str, str]) -> list[dict]:
    """Collect detailed draft pick data from a league.

    Fetches player details in batches to get position type and eligible
    positions, then assigns a primary position based on scarcity.

    Args:
        league: A yahoo_fantasy_api League object.
        year: Season year.
        team_names: Mapping of team_key to team_name.

    Returns:
        List of per-pick dicts with full draft data.
    """
    draft_results = league.draft_results()

    # Batch-fetch player details (player_details accepts list of int IDs)
    player_ids = [pick["player_id"] for pick in draft_results]
    player_info_map: dict[int, dict] = {}

    batch_size = 25
    for i in range(0, len(player_ids), batch_size):
        batch = player_ids[i : i + batch_size]
        try:
            details = league.player_details(batch)
            for info in details:
                pid = int(info.get("player_id", 0))
                player_info_map[pid] = info
        except Exception as e:
            click.echo(f"  Warning: batch player lookup failed: {e}")
            # Fall back to individual lookups
            for pid in batch:
                try:
                    details = league.player_details(pid)
                    if details:
                        player_info_map[pid] = details[0]
                except Exception as e2:
                    click.echo(f"  Warning: could not look up player {pid}: {e2}")

    picks = []
    for pick in draft_results:
        team_key = pick["team_key"]
        player_id = pick["player_id"]
        cost = int(pick.get("cost", 0))

        info = player_info_map.get(player_id, {})
        name_field = info.get("name", {})
        player_name = (
            name_field.get("full", "Unknown")
            if isinstance(name_field, dict)
            else str(name_field) if name_field else "Unknown"
        )
        position_type = info.get("position_type", "")

        # eligible_positions is a list of {"position": "OF"} dicts
        raw_positions = info.get("eligible_positions", [])
        eligible_positions = [
            p["position"] if isinstance(p, dict) else p
            for p in raw_positions
        ]

        # Filter out non-roster positions
        roster_positions = [
            p for p in eligible_positions
            if p not in ("BN", "IL", "IL+", "NA", "DL")
        ]

        primary = assign_primary_position(roster_positions) if roster_positions else (
            "P" if position_type == "P" else "Util"
        )

        picks.append({
            "player_name": player_name,
            "team_key": team_key,
            "team_name": team_names.get(team_key, team_key),
            "cost": cost,
            "position_type": position_type,
            "eligible_positions": roster_positions,
            "primary_position": primary,
            "season": year,
        })

    return picks


def _compute_bench_hitter_stats(
    picks: list[dict],
) -> list[dict]:
    """Compute bench hitter counts per team from pick data.

    Args:
        picks: List of per-pick dicts with position_type and team_key.

    Returns:
        List of per-team dicts with hitter/pitcher/bench counts.
    """
    teams: dict[str, dict] = {}
    for pick in picks:
        team_key = pick["team_key"]
        if team_key not in teams:
            teams[team_key] = {
                "team_key": team_key,
                "team_name": pick["team_name"],
                "hitters": 0,
                "pitchers": 0,
            }
        if pick["position_type"] == "B":
            teams[team_key]["hitters"] += 1
        elif pick["position_type"] == "P":
            teams[team_key]["pitchers"] += 1

    results = []
    for info in teams.values():
        bench_hitters = max(0, info["hitters"] - LEAGUE.hitting_slots)
        results.append({
            "team_key": info["team_key"],
            "team_name": info["team_name"],
            "hitters_drafted": info["hitters"],
            "pitchers_drafted": info["pitchers"],
            "bench_hitters": bench_hitters,
        })
    return results


def _print_bench_calibration(all_results: list[dict], all_bench_hitters: list[int]) -> None:
    """Print bench hitter calibration section.

    Args:
        all_results: Per-team draft results across all seasons.
        all_bench_hitters: Flat list of bench hitter counts.
    """
    if not all_bench_hitters:
        return

    avg = sum(all_bench_hitters) / len(all_bench_hitters)
    recommended = round(avg)
    click.echo(f"\nAverage bench hitters per team: {avg:.2f}")
    click.echo(f"Recommended --bench-hitters value: {recommended}")
    click.echo(
        f"\n  .venv/bin/python scripts/generate_values.py "
        f"projections/hitters.csv projections/pitchers.csv "
        f"--bench-hitters {recommended}"
    )


def _print_budget_allocation(picks_df: pd.DataFrame) -> None:
    """Print hitter/pitcher budget split per team.

    Args:
        picks_df: DataFrame of all draft picks.
    """
    click.echo(f"\n{'=' * 60}")
    click.echo("BUDGET ALLOCATION — Hitter/Pitcher Split")
    click.echo(f"{'=' * 60}")

    split = hitter_pitcher_split(picks_df)
    click.echo(
        f"{'Team':<25} {'Season':>6} {'Hitters $':>10} {'Pitchers $':>11} {'Hit %':>6}"
    )
    click.echo("-" * 60)
    for _, row in split.iterrows():
        click.echo(
            f"{row['team_name']:<25} {row['season']:>6} "
            f"${row['hitter_spend']:>8} ${row['pitcher_spend']:>9} "
            f"{row['hitter_pct']:>5.1f}%"
        )

    # Multi-season averages
    avg = split.groupby("team_name")["hitter_pct"].mean().sort_values(ascending=False)
    click.echo(f"\n{'Team':<25} {'Avg Hit %':>10}")
    click.echo("-" * 37)
    for team, pct in avg.items():
        click.echo(f"{team:<25} {pct:>9.1f}%")


def _print_position_premiums(picks_df: pd.DataFrame) -> None:
    """Print position market premium/discount table.

    Args:
        picks_df: DataFrame of all draft picks.
    """
    click.echo(f"\n{'=' * 60}")
    click.echo("POSITION MARKET PREMIUMS")
    click.echo(f"{'=' * 60}")

    summary = position_spend_summary(picks_df)
    click.echo(
        f"{'Position':<10} {'Count':>6} {'Mean $':>7} {'Med $':>6} "
        f"{'Budget%':>8} {'Fair%':>6} {'Premium':>8}"
    )
    click.echo("-" * 55)
    for pos in summary.index:
        row = summary.loc[pos]
        click.echo(
            f"{pos:<10} {row['count']:>6.0f} ${row['mean_cost']:>5.1f} "
            f"${row['median_cost']:>4.1f} {row['budget_share_pct']:>7.1f}% "
            f"{row['fair_share_pct']:>5.1f}% {row['premium_pct']:>+7.1f}%"
        )


def _print_price_dropoff(picks_df: pd.DataFrame) -> None:
    """Print price drop-off curves per position.

    Args:
        picks_df: DataFrame of all draft picks.
    """
    click.echo(f"\n{'=' * 60}")
    click.echo("PRICE DROP-OFF CURVES — Top 5 by Position")
    click.echo(f"{'=' * 60}")

    dropoff = price_dropoff_by_position(picks_df, top_n=5)
    if dropoff.empty:
        click.echo("  No data available.")
        return

    for pos in sorted(dropoff["position"].unique()):
        pos_data = dropoff[dropoff["position"] == pos]
        steep_row = pos_data[pos_data["rank"] == 1]
        steepness = steep_row["steepness"].values[0] if not steep_row.empty else None

        prices = []
        for _, row in pos_data.iterrows():
            prices.append(f"#{int(row['rank'])}: ${row['avg_cost']:.0f}")

        steep_str = f"  (drop: ${steepness:.0f})" if steepness and pd.notna(steepness) else ""
        click.echo(f"  {pos:<6} {', '.join(prices)}{steep_str}")


def _print_standings_correlation(
    picks_df: pd.DataFrame,
    standings_df: pd.DataFrame,
) -> None:
    """Print spending vs standings correlation.

    Args:
        picks_df: DataFrame of all draft picks.
        standings_df: DataFrame with standings data.
    """
    click.echo(f"\n{'=' * 60}")
    click.echo("STANDINGS CORRELATION — Hitter Spend % vs Final Rank")
    click.echo(f"{'=' * 60}")

    corr = spending_vs_standings(picks_df, standings_df)
    if corr.empty:
        click.echo("  No standings data available.")
        return

    click.echo(f"{'Hitter Spend %':<16} {'Avg Rank':>9} {'Teams':>6}")
    click.echo("-" * 33)
    for _, row in corr.iterrows():
        click.echo(
            f"{row['hitter_pct_bin']:<16} {row['avg_rank']:>9.1f} {row['team_count']:>6}"
        )


def _print_team_report(
    picks_df: pd.DataFrame,
    standings_df: pd.DataFrame,
    team_name: str,
) -> None:
    """Print personalized team report.

    Args:
        picks_df: DataFrame of all draft picks.
        standings_df: DataFrame with standings data.
        team_name: Name of the team to report on.
    """
    click.echo(f"\n{'=' * 60}")
    click.echo(f"TEAM REPORT — {team_name}")
    click.echo(f"{'=' * 60}")

    report = user_team_report(picks_df, standings_df, team_name)
    if not report["seasons"]:
        click.echo(f"  No data found for team '{team_name}'.")
        return

    click.echo(
        f"{'Season':>6} {'Hit $':>7} {'Pitch $':>9} {'Hit %':>6} "
        f"{'Lg Avg':>7} {'Rank':>5}"
    )
    click.echo("-" * 42)
    for s in report["seasons"]:
        rank_str = str(s["final_rank"]) if s["final_rank"] is not None else "N/A"
        click.echo(
            f"{s['season']:>6} ${s['hitter_spend']:>5} ${s['pitcher_spend']:>7} "
            f"{s['hitter_pct']:>5.1f}% {s['league_avg_hitter_pct']:>6.1f}% "
            f"{rank_str:>5}"
        )


def _print_recommendations(picks_df: pd.DataFrame) -> None:
    """Print actionable overpay/underpay recommendations.

    Args:
        picks_df: DataFrame of all draft picks.
    """
    click.echo(f"\n{'=' * 60}")
    click.echo("DRAFT RECOMMENDATIONS")
    click.echo(f"{'=' * 60}")

    recs = overpay_recommendations(picks_df)
    for rec in sorted(recs, key=lambda r: r["position"]):
        label = rec["strategy"].replace("_", " ").upper()
        click.echo(f"\n  {rec['position']:<6} [{label}]")
        click.echo(f"         {rec['reasoning']}")


@click.command()
@click.argument("seasons", nargs=-1, type=int, required=True)
@click.option("--team", default=None, help="Your team name for personalized report.")
@click.option(
    "--output", "-o", default=None, type=click.Path(),
    help="CSV export path for raw draft data.",
)
def main(seasons: tuple[int, ...], team: Optional[str], output: Optional[str]) -> None:
    """Analyze past Yahoo drafts for valuation calibration and strategy insights.

    SEASONS: One or more past season years (e.g. 2023 2024 2025).
    """
    click.echo("Authenticating with Yahoo...")
    oauth = get_yahoo_auth()

    click.echo(f"Discovering leagues for seasons: {list(seasons)}...")
    leagues = _get_game_and_leagues(oauth, list(seasons))

    if not leagues:
        click.echo("No leagues found for the specified seasons.")
        return

    all_picks: list[dict] = []
    all_standings: list[dict] = []
    all_bench_hitters: list[int] = []

    for year, league in leagues:
        click.echo(f"\nFetching data for {year}...")

        team_names = _fetch_team_names(league)
        picks = _collect_draft_picks(league, year, team_names)
        standings = _fetch_standings(league, year)

        all_picks.extend(picks)
        all_standings.extend(standings)

        # Bench calibration per season
        bench_stats = _compute_bench_hitter_stats(picks)
        click.echo(f"\n{'=' * 60}")
        click.echo(f"Season {year} — Bench Hitter Calibration")
        click.echo(f"{'=' * 60}")
        click.echo(
            f"{'Team':<25} {'Hitters':>8} {'Pitchers':>9} {'Bench H':>8}"
        )
        click.echo("-" * 53)
        for r in bench_stats:
            click.echo(
                f"{r['team_name']:<25} {r['hitters_drafted']:>8} "
                f"{r['pitchers_drafted']:>9} {r['bench_hitters']:>8}"
            )
            all_bench_hitters.append(r["bench_hitters"])

    # Build DataFrames
    picks_df = pd.DataFrame(all_picks)
    standings_df = pd.DataFrame(all_standings)

    # Export raw data if requested
    if output:
        export_df = picks_df.copy()
        export_df["eligible_positions"] = export_df["eligible_positions"].apply(
            lambda x: ",".join(x) if isinstance(x, list) else x
        )
        export_df.to_csv(output, index=False)
        click.echo(f"\nRaw draft data exported to {output}")

    # === Report Sections ===

    # 1. Bench calibration summary
    click.echo(f"\n{'=' * 60}")
    click.echo("BENCH HITTER CALIBRATION — Summary")
    click.echo(f"{'=' * 60}")
    _print_bench_calibration([], all_bench_hitters)

    # 2. Budget allocation
    _print_budget_allocation(picks_df)

    # 3. Position market premiums
    _print_position_premiums(picks_df)

    # 4. Price drop-off curves
    _print_price_dropoff(picks_df)

    # 5. Standings correlation
    _print_standings_correlation(picks_df, standings_df)

    # 6. Team report (if requested)
    if team:
        _print_team_report(picks_df, standings_df, team)

    # 7. Recommendations
    _print_recommendations(picks_df)


if __name__ == "__main__":
    main()

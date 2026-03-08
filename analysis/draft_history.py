"""Historical draft analysis for position valuation calibration.

Analyzes past Yahoo auction draft data to identify market premiums,
spending patterns, and their correlation with final standings.
"""

from __future__ import annotations

import pandas as pd

from config.league import LEAGUE, LeagueSettings
from config.positions import Position


# Map Yahoo position strings to our Position enum
YAHOO_POSITION_MAP: dict[str, Position] = {
    "C": Position.C,
    "1B": Position.FIRST,
    "2B": Position.SECOND,
    "3B": Position.THIRD,
    "SS": Position.SS,
    "LF": Position.OF,
    "CF": Position.OF,
    "RF": Position.OF,
    "OF": Position.OF,
    "DH": Position.UTIL,
    "Util": Position.UTIL,
    "SP": Position.P,
    "RP": Position.P,
    "P": Position.P,
}


def assign_primary_position(
    eligible_positions: list[str],
    league: LeagueSettings = LEAGUE,
) -> str:
    """Assign a primary position based on scarcity of eligible positions.

    Uses the same logic as the valuation engine: prefer the scarcest
    eligible position (fewest league-wide slots) to reflect positional value.

    Args:
        eligible_positions: List of Yahoo position strings (e.g. ["C", "1B", "Util"]).
        league: League settings for slot counts.

    Returns:
        The primary position string (e.g. "C").
    """
    # Build slot counts per Position enum
    slot_counts: dict[Position, int] = {
        Position.C: league.catcher,
        Position.FIRST: league.first_base,
        Position.SECOND: league.second_base,
        Position.THIRD: league.third_base,
        Position.SS: league.shortstop,
        Position.OF: league.outfield,
        Position.UTIL: league.utility,
        Position.P: league.pitcher,
    }

    # Map eligible positions to Position enums, dedup
    mapped: list[Position] = []
    seen: set[Position] = set()
    for pos_str in eligible_positions:
        pos = YAHOO_POSITION_MAP.get(pos_str)
        if pos is not None and pos not in seen:
            mapped.append(pos)
            seen.add(pos)

    if not mapped:
        return eligible_positions[0] if eligible_positions else "Unknown"

    # Filter out Util for scarcity ranking (prefer specific positions)
    specific = [p for p in mapped if p != Position.UTIL]
    candidates = specific if specific else mapped

    # Pick scarcest (fewest per-team slots)
    best = min(candidates, key=lambda p: slot_counts.get(p, 999))
    return best.value


def position_spend_summary(
    picks_df: pd.DataFrame,
    league: LeagueSettings = LEAGUE,
) -> pd.DataFrame:
    """Summarize spending by primary position across all drafts.

    Calculates count, mean/median cost, total spend, budget share, and
    compares to "fair share" (position's slot fraction of total slots x budget).

    Args:
        picks_df: DataFrame with columns: cost, primary_position, season.
        league: League settings for fair share calculation.

    Returns:
        DataFrame indexed by position with spending metrics and premium/discount.
    """
    total_spend = picks_df["cost"].sum()
    num_seasons = picks_df["season"].nunique()

    grouped = picks_df.groupby("primary_position")["cost"].agg(
        count="count",
        total_spend="sum",
        mean_cost="mean",
        median_cost="median",
    )

    grouped["budget_share_pct"] = (grouped["total_spend"] / total_spend * 100).round(1)

    # Calculate fair share per position
    slot_counts: dict[str, int] = {
        "C": league.catcher,
        "1B": league.first_base,
        "2B": league.second_base,
        "3B": league.third_base,
        "SS": league.shortstop,
        "OF": league.outfield,
        "Util": league.utility,
        "P": league.pitcher,
    }
    total_slots = league.roster_size
    fair_shares: dict[str, float] = {
        pos: (slots / total_slots * 100) for pos, slots in slot_counts.items()
    }

    grouped["fair_share_pct"] = grouped.index.map(
        lambda p: fair_shares.get(p, 0.0)
    )
    grouped["premium_pct"] = (grouped["budget_share_pct"] - grouped["fair_share_pct"]).round(1)

    # Round numeric columns
    grouped["mean_cost"] = grouped["mean_cost"].round(1)
    grouped["median_cost"] = grouped["median_cost"].round(1)

    return grouped.sort_values("total_spend", ascending=False)


def hitter_pitcher_split(picks_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate hitter vs pitcher spending split per team per season.

    Args:
        picks_df: DataFrame with columns: cost, position_type, team_name, season.

    Returns:
        DataFrame with team_name, season, hitter_spend, pitcher_spend, hitter_pct.
    """
    team_season = picks_df.groupby(["season", "team_name", "position_type"])["cost"].sum()
    team_season = team_season.unstack(fill_value=0)

    result = pd.DataFrame({
        "season": team_season.index.get_level_values("season"),
        "team_name": team_season.index.get_level_values("team_name"),
        "hitter_spend": team_season.get("B", pd.Series(0, index=team_season.index)).values,
        "pitcher_spend": team_season.get("P", pd.Series(0, index=team_season.index)).values,
    })

    result["total_spend"] = result["hitter_spend"] + result["pitcher_spend"]
    result["hitter_pct"] = (result["hitter_spend"] / result["total_spend"] * 100).round(1)

    return result.sort_values(["season", "team_name"]).reset_index(drop=True)


def spending_vs_standings(
    picks_df: pd.DataFrame,
    standings_df: pd.DataFrame,
) -> pd.DataFrame:
    """Correlate hitter spending percentage with final standings rank.

    Bins teams by hitter-spend % and shows average rank per bin.

    Args:
        picks_df: DataFrame with columns: cost, position_type, team_name, season.
        standings_df: DataFrame with columns: season, team_key, team_name, final_rank.

    Returns:
        DataFrame with hitter_pct_bin, avg_rank, team_count.
    """
    split = hitter_pitcher_split(picks_df)

    # Merge with standings
    merged = split.merge(
        standings_df[["season", "team_name", "final_rank"]],
        on=["season", "team_name"],
        how="inner",
    )

    if merged.empty:
        return pd.DataFrame(columns=["hitter_pct_bin", "avg_rank", "team_count"])

    # Bin by hitter spending percentage
    bins = [0, 50, 55, 60, 65, 70, 75, 100]
    labels = ["<50%", "50-55%", "55-60%", "60-65%", "65-70%", "70-75%", ">75%"]
    merged["hitter_pct_bin"] = pd.cut(
        merged["hitter_pct"], bins=bins, labels=labels, right=False
    )

    binned = merged.groupby("hitter_pct_bin", observed=True)["final_rank"].agg(
        avg_rank="mean",
        team_count="count",
    ).reset_index()

    binned["avg_rank"] = binned["avg_rank"].round(1)

    return binned


def user_team_report(
    picks_df: pd.DataFrame,
    standings_df: pd.DataFrame,
    team_name: str,
) -> dict:
    """Generate a personalized report for a specific team.

    Args:
        picks_df: DataFrame with draft pick data.
        standings_df: DataFrame with standings data.
        team_name: Name of the team to report on.

    Returns:
        Dictionary with team spending vs league averages and rank history.
    """
    split = hitter_pitcher_split(picks_df)
    team_data = split[split["team_name"] == team_name]
    league_avg = split.groupby("season")["hitter_pct"].mean()

    seasons_report = []
    for _, row in team_data.iterrows():
        season = row["season"]
        standing = standings_df[
            (standings_df["season"] == season) & (standings_df["team_name"] == team_name)
        ]
        rank = standing["final_rank"].iloc[0] if not standing.empty else None

        seasons_report.append({
            "season": season,
            "hitter_spend": int(row["hitter_spend"]),
            "pitcher_spend": int(row["pitcher_spend"]),
            "hitter_pct": float(row["hitter_pct"]),
            "league_avg_hitter_pct": round(float(league_avg.get(season, 0)), 1),
            "final_rank": int(rank) if rank is not None else None,
        })

    return {
        "team_name": team_name,
        "seasons": seasons_report,
    }


def price_dropoff_by_position(
    picks_df: pd.DataFrame,
    top_n: int = 5,
) -> pd.DataFrame:
    """Show price drop-off curves per position.

    For each position, ranks players by cost and shows the top N prices
    along with a steepness metric (cost of #1 minus cost of #N).

    Args:
        picks_df: DataFrame with columns: cost, primary_position, season.
        top_n: Number of top players to show per position.

    Returns:
        DataFrame with position, rank, avg_cost (averaged across seasons),
        and steepness for rank 1 rows.
    """
    num_seasons = picks_df["season"].nunique()

    records = []
    for pos in picks_df["primary_position"].unique():
        pos_picks = picks_df[picks_df["primary_position"] == pos]

        # Rank within each season, then average across seasons
        pos_picks = pos_picks.copy()
        pos_picks["rank"] = pos_picks.groupby("season")["cost"].rank(
            ascending=False, method="first"
        ).astype(int)

        for rank in range(1, top_n + 1):
            rank_picks = pos_picks[pos_picks["rank"] == rank]
            if rank_picks.empty:
                continue
            avg_cost = round(rank_picks["cost"].mean(), 1)
            records.append({
                "position": pos,
                "rank": rank,
                "avg_cost": avg_cost,
            })

    result = pd.DataFrame(records)
    if result.empty:
        return result

    # Calculate steepness: cost of #1 minus cost of #top_n
    steepness = {}
    for pos in result["position"].unique():
        pos_data = result[result["position"] == pos]
        cost_1 = pos_data[pos_data["rank"] == 1]["avg_cost"].values
        cost_n = pos_data[pos_data["rank"] == top_n]["avg_cost"].values
        if len(cost_1) > 0 and len(cost_n) > 0:
            steepness[pos] = round(cost_1[0] - cost_n[0], 1)

    result["steepness"] = result.apply(
        lambda r: steepness.get(r["position"]) if r["rank"] == 1 else None,
        axis=1,
    )

    return result.sort_values(["position", "rank"]).reset_index(drop=True)


def overpay_recommendations(picks_df: pd.DataFrame) -> list[dict]:
    """Synthesize analysis into actionable draft guidance.

    Identifies positions where:
    - Steep drop-off = overpay for elite (scarcity premium justified)
    - High market premium = let others overpay (market overprices)
    - Low market premium or discount = target value (market underprices)

    Args:
        picks_df: DataFrame with draft pick data.

    Returns:
        List of recommendation dicts with position, strategy, and reasoning.
    """
    dropoff = price_dropoff_by_position(picks_df)
    spend = position_spend_summary(picks_df)

    recommendations = []
    for pos in spend.index:
        premium = spend.loc[pos, "premium_pct"]
        pos_dropoff = dropoff[dropoff["position"] == pos]
        steep = pos_dropoff[pos_dropoff["rank"] == 1]["steepness"].values
        steepness = steep[0] if len(steep) > 0 and pd.notna(steep[0]) else 0.0

        median_cost = spend.loc[pos, "median_cost"]

        if steepness > median_cost * 0.5 and premium <= 2.0:
            strategy = "overpay_for_elite"
            reasoning = (
                f"Steep drop-off (${steepness:.0f}) means elite {pos} players "
                f"are significantly better than alternatives. Market doesn't "
                f"fully price this scarcity (premium: {premium:+.1f}%)."
            )
        elif premium > 3.0:
            strategy = "let_others_overpay"
            reasoning = (
                f"Market overpays for {pos} ({premium:+.1f}% above fair share). "
                f"Let other managers chase these players."
            )
        elif premium < -2.0:
            strategy = "target_value"
            reasoning = (
                f"{pos} is underpriced by the market ({premium:+.1f}% vs fair share). "
                f"Good place to find bargains."
            )
        else:
            strategy = "draft_at_value"
            reasoning = (
                f"{pos} is priced near fair value ({premium:+.1f}%). "
                f"Draft at model price, no need to overpay or avoid."
            )

        recommendations.append({
            "position": pos,
            "strategy": strategy,
            "steepness": steepness,
            "premium_pct": premium,
            "reasoning": reasoning,
        })

    return recommendations

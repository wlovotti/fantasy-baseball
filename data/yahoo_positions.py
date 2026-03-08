"""Yahoo position eligibility merging for hitter projections."""

from __future__ import annotations

import logging

import pandas as pd

from config.positions import Position, parse_positions

logger = logging.getLogger(__name__)

_PITCHER_POSITIONS = {"P", "SP", "RP"}


def _is_pitcher_only(pos_str: str) -> bool:
    """Return True if every position in a comma-separated string is a pitcher slot."""
    return {p.strip() for p in pos_str.split(",")}.issubset(_PITCHER_POSITIONS)


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
        logger.warning("No Yahoo players found, keeping default positions")
        return hitters, hitters["name"].tolist()

    # Build name->position map, preferring non-pitcher entries for hitters.
    # Yahoo lists dual players like Ohtani twice (Batter + Pitcher) with the
    # same normalized name; we want the batter entry when matching hitters.
    yahoo_pos_map: dict[str, str] = {}
    for _, yrow in yahoo_df.iterrows():
        name = yrow["yahoo_name"]
        pos = yrow["position"]
        if name not in yahoo_pos_map or _is_pitcher_only(yahoo_pos_map[name]):
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

    logger.info("Matched %d/%d hitters to Yahoo positions", matched_count, len(hitters))
    if unmatched_names:
        logger.info("Unmatched (%d):", len(unmatched_names))
        for name in unmatched_names[:10]:
            logger.info("  - %s", name)
        if len(unmatched_names) > 10:
            logger.info("  ... and %d more", len(unmatched_names) - 10)

    return hitters, unmatched_names


def fetch_and_merge_positions(
    hitters: pd.DataFrame,
    league: object,
    threshold: int = 90,
) -> pd.DataFrame:
    """Fetch Yahoo positions and merge them into hitter projections.

    Performs a two-pass fetch: first fetches the full roster, then searches
    Yahoo for any unmatched hitters by last name to catch dual-eligible
    players (like Ohtani) who have synthetic IDs.

    Args:
        hitters: Hitter DataFrame from load_hitters().
        league: Yahoo league object from get_league().
        threshold: Minimum fuzzy match score (0-100) to accept.

    Returns:
        Updated hitters DataFrame with Yahoo position eligibility.
    """
    from yahoo.league_client import fetch_yahoo_players

    logger.info("Fetching Yahoo player positions...")
    yahoo_df = fetch_yahoo_players(league)
    logger.info("Fetched %d players from Yahoo", len(yahoo_df))

    # First pass: merge Yahoo positions into hitters
    logger.info("Matching hitter positions from Yahoo...")
    hitters, unmatched_names = merge_yahoo_positions(
        hitters, yahoo_df, score_threshold=threshold
    )

    # Second pass: search Yahoo for unmatched hitters (catches dual-eligible
    # players like Ohtani who have synthetic IDs)
    if unmatched_names:
        last_names = list({n.split()[-1] for n in unmatched_names})
        logger.info("Searching Yahoo for %d unmatched last names...", len(last_names))
        yahoo_df = fetch_yahoo_players(league, search_names=last_names)
        logger.info("Player pool now %d after search", len(yahoo_df))
        hitters, _ = merge_yahoo_positions(
            hitters, yahoo_df, score_threshold=threshold
        )

    return hitters

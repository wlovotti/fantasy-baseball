"""Yahoo Fantasy league discovery and player ID matching."""

import os

import pandas as pd
from rapidfuzz import fuzz, process

from yahoo.auth import get_yahoo_auth


def get_league():
    """Get the user's Yahoo Fantasy league object.

    Uses YAHOO_GAME_KEY and YAHOO_LEAGUE_ID from environment.

    Returns:
        A yahoo_fantasy_api League object.

    Raises:
        ValueError: If league configuration is missing from .env.
    """
    try:
        import yahoo_fantasy_api as yfa
    except ImportError:
        raise ImportError(
            "yahoo-fantasy-api is required. Install with: pip install yahoo-fantasy-api"
        )

    oauth = get_yahoo_auth()
    game_key = os.getenv("YAHOO_GAME_KEY", "mlb")
    league_id = os.getenv("YAHOO_LEAGUE_ID")

    if not league_id:
        raise ValueError("YAHOO_LEAGUE_ID must be set in .env.")

    game = yfa.Game(oauth, game_key)
    league = game.to_league(league_id)
    return league


def fetch_yahoo_players(league) -> pd.DataFrame:
    """Fetch all players from the Yahoo league with their Yahoo IDs.

    Args:
        league: A yahoo_fantasy_api League object.

    Returns:
        DataFrame with columns: yahoo_id, yahoo_name, position.
    """
    players = []
    # Yahoo paginates player lists in chunks of 25
    start = 0
    while True:
        batch = league.player_list(start=start)
        if not batch:
            break
        for p in batch:
            eligible = p.get("eligible_positions", "")
            if isinstance(eligible, list):
                eligible = ",".join(eligible)
            players.append({
                "yahoo_id": p["player_id"],
                "yahoo_name": p["name"],
                "position": eligible,
            })
        start += 25

    return pd.DataFrame(players)


def match_players(
    values_df: pd.DataFrame,
    yahoo_df: pd.DataFrame,
    score_threshold: int = 90,
) -> pd.DataFrame:
    """Fuzzy match valued players to Yahoo player IDs.

    Uses rapidfuzz token_sort_ratio for robust name matching that handles
    name order differences and minor spelling variations.

    Args:
        values_df: DataFrame with 'name' column from valuations.
        yahoo_df: DataFrame with 'yahoo_name' and 'yahoo_id' from Yahoo.
        score_threshold: Minimum fuzzy match score (0-100) to accept.

    Returns:
        values_df with 'yahoo_id' and 'match_score' columns added.
        Unmatched players will have yahoo_id=None.
    """
    yahoo_names = yahoo_df["yahoo_name"].tolist()
    yahoo_id_map = dict(zip(yahoo_df["yahoo_name"], yahoo_df["yahoo_id"]))

    matched_ids = []
    match_scores = []
    unmatched = []

    for _, row in values_df.iterrows():
        name = row["name"]
        result = process.extractOne(
            name, yahoo_names, scorer=fuzz.token_sort_ratio
        )

        if result and result[1] >= score_threshold:
            matched_name = result[0]
            matched_ids.append(yahoo_id_map[matched_name])
            match_scores.append(result[1])
        else:
            matched_ids.append(None)
            match_scores.append(result[1] if result else 0)
            unmatched.append(name)

    values_df = values_df.copy()
    values_df["yahoo_id"] = matched_ids
    values_df["match_score"] = match_scores

    if unmatched:
        print(f"\nUnmatched players ({len(unmatched)}):")
        for name in unmatched[:20]:
            print(f"  - {name}")
        if len(unmatched) > 20:
            print(f"  ... and {len(unmatched) - 20} more")

    return values_df

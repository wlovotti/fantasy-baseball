"""Yahoo Fantasy league discovery and player ID matching."""

from __future__ import annotations

import os
import re

import pandas as pd
from rapidfuzz import fuzz, process

from yahoo.auth import get_yahoo_auth


# Yahoo appends role suffixes for dual-eligible players (e.g. Ohtani)
_YAHOO_NAME_SUFFIX_RE = re.compile(r"\s*\((?:Batter|Pitcher)\)\s*$")


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
    full_league_key = f"{game.game_id()}.l.{league_id}"
    league = game.to_league(full_league_key)
    return league


def _normalize_yahoo_name(name: str) -> str:
    """Strip Yahoo role suffixes like '(Batter)' or '(Pitcher)' from names."""
    return _YAHOO_NAME_SUFFIX_RE.sub("", name)


def _parse_search_results(raw: dict) -> list[dict]:
    """Parse players from a Yahoo search API response.

    Args:
        raw: Raw JSON response from the Yahoo search endpoint.

    Returns:
        List of player dicts with player_id, name, and eligible_positions.
    """
    players_data = raw.get("fantasy_content", {}).get("league", [{}])[1]
    if not isinstance(players_data, dict) or "players" not in players_data:
        return []

    results = []
    players_section = players_data["players"]
    for key in players_section:
        if key == "count":
            continue
        try:
            player_info = players_section[key]["player"][0]
            pid = player_info[1]["player_id"]
            name = player_info[2]["name"]["full"]
            # Extract eligible positions from the raw data
            positions = []
            for item in player_info:
                if isinstance(item, dict) and "eligible_positions" in item:
                    for pos_entry in item["eligible_positions"]:
                        if isinstance(pos_entry, dict) and "position" in pos_entry:
                            positions.append(pos_entry["position"])
                    break
            if not positions:
                for item in player_info:
                    if isinstance(item, dict) and "display_position" in item:
                        positions = [item["display_position"]]
                        break
            results.append({
                "player_id": pid,
                "name": name,
                "eligible_positions": positions,
            })
        except (KeyError, IndexError):
            continue
    return results


def fetch_yahoo_players(league, search_names: list[str] | None = None) -> pd.DataFrame:
    """Fetch all players from the Yahoo league with their Yahoo IDs.

    Combines available players (batters + pitchers) and taken players.
    Optionally searches for specific player names to catch players with
    synthetic IDs (e.g. Ohtani's split batter/pitcher entries) that don't
    appear in normal player listings.

    Args:
        league: A yahoo_fantasy_api League object.
        search_names: Optional list of player last names to search for
            via the Yahoo search API, catching players missed by the
            normal listing endpoints.

    Returns:
        DataFrame with columns: yahoo_id, yahoo_name, position.
    """
    seen_ids = set()
    players = []

    def _add_player(pid, name, eligible):
        """Add a player to the list if not already seen."""
        if pid in seen_ids:
            return
        seen_ids.add(pid)
        if isinstance(eligible, list):
            eligible = ",".join(eligible)
        players.append({
            "yahoo_id": pid,
            "yahoo_name": _normalize_yahoo_name(name),
            "position": eligible,
        })

    # Use _fetch_players with status 'A' (all available = FA + waivers)
    # for both batters and pitchers, plus taken players.
    # This works in pre-draft when free_agents() may return empty.
    sources = [
        league._fetch_players("A", position="B"),
        league._fetch_players("A", position="P"),
        league.taken_players(),
    ]
    for batch in sources:
        for p in batch:
            _add_player(
                p["player_id"],
                p["name"],
                p.get("eligible_positions", []),
            )

    # Search for specific players that may not appear in normal listings
    # (e.g. dual-eligible players like Ohtani with synthetic IDs)
    if search_names:
        for name in search_names:
            try:
                raw = league.yhandler.get(
                    "league/{}/players;search={}/percent_owned".format(
                        league.league_id, name
                    )
                )
                for p in _parse_search_results(raw):
                    _add_player(
                        p["player_id"],
                        p["name"],
                        p.get("eligible_positions", []),
                    )
            except Exception:
                continue

    return pd.DataFrame(players)


def _fuzzy_match_name(
    name: str,
    yahoo_names: list[str],
    yahoo_id_map: dict[str, str],
    score_threshold: int,
) -> tuple[str | None, float]:
    """Fuzzy match a single player name against Yahoo names.

    Args:
        name: Player name to match.
        yahoo_names: List of Yahoo player names to match against.
        yahoo_id_map: Mapping from Yahoo name to Yahoo player ID.
        score_threshold: Minimum fuzzy match score (0-100) to accept.

    Returns:
        Tuple of (yahoo_id or None, match_score).
    """
    result = process.extractOne(
        name, yahoo_names, scorer=fuzz.token_sort_ratio
    )
    if result and result[1] >= score_threshold:
        return yahoo_id_map[result[0]], result[1]
    return None, result[1] if result else 0


def match_players(
    values_df: pd.DataFrame,
    yahoo_df: pd.DataFrame,
    score_threshold: int = 90,
    league=None,
) -> pd.DataFrame:
    """Fuzzy match valued players to Yahoo player IDs.

    Uses rapidfuzz token_sort_ratio for robust name matching that handles
    name order differences and minor spelling variations.

    When a league object is provided, unmatched players trigger a second
    pass that searches Yahoo by last name. This catches players not in the
    normal FA/taken pools (e.g. NA-status prospects, dual-eligible entries).

    Args:
        values_df: DataFrame with 'name' column from valuations.
        yahoo_df: DataFrame with 'yahoo_name' and 'yahoo_id' from Yahoo.
        score_threshold: Minimum fuzzy match score (0-100) to accept.
        league: Optional Yahoo league object for fallback search of
            unmatched players.

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
        yahoo_id, score = _fuzzy_match_name(
            name, yahoo_names, yahoo_id_map, score_threshold
        )
        matched_ids.append(yahoo_id)
        match_scores.append(score)
        if yahoo_id is None:
            unmatched.append(name)

    # Second pass: search Yahoo for unmatched players by last name,
    # expanding the pool with NA-status and other missing players.
    if unmatched and league is not None:
        last_names = list({n.split()[-1] for n in unmatched})
        expanded_df = fetch_yahoo_players(league, search_names=last_names)
        expanded_names = expanded_df["yahoo_name"].tolist()
        expanded_id_map = dict(
            zip(expanded_df["yahoo_name"], expanded_df["yahoo_id"])
        )

        still_unmatched = []
        for i, (_, row) in enumerate(values_df.iterrows()):
            if matched_ids[i] is not None:
                continue
            name = row["name"]
            yahoo_id, score = _fuzzy_match_name(
                name, expanded_names, expanded_id_map, score_threshold
            )
            if yahoo_id is not None:
                matched_ids[i] = yahoo_id
                match_scores[i] = score
            else:
                still_unmatched.append(name)
        unmatched = still_unmatched

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

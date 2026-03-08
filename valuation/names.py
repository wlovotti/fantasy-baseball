"""Name disambiguation for players with multiple entries (e.g. Ohtani)."""

from __future__ import annotations

import pandas as pd


_TYPE_SUFFIX = {"hitter": "(Batter)", "pitcher": "(Pitcher)"}


def disambiguate_player_names(df: pd.DataFrame) -> pd.DataFrame:
    """Append role suffixes to players who appear as both hitter and pitcher.

    Players like Ohtani have separate hitter and pitcher projection rows with
    the same name.  This causes collisions in the lookup CLI and draft tracker
    (which keys on name).  Appending "(Batter)" / "(Pitcher)" — matching
    Yahoo's own convention — makes each entry unique.

    Args:
        df: Combined player DataFrame with 'name' and 'player_type' columns.

    Returns:
        DataFrame with disambiguated names for dual-entry players.
    """
    # Find names that appear in both hitter and pitcher rows
    names_by_type = df.groupby("name")["player_type"].apply(set)
    dual_names = set(names_by_type[names_by_type.apply(len) > 1].index)

    if not dual_names:
        return df

    df = df.copy()
    mask = df["name"].isin(dual_names)
    df.loc[mask, "name"] = df.loc[mask].apply(
        lambda r: f"{r['name']} {_TYPE_SUFFIX.get(r['player_type'], '')}".strip(),
        axis=1,
    )
    return df

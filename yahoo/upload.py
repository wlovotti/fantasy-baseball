"""Upload auction dollar values to Yahoo Fantasy."""

from __future__ import annotations

import pandas as pd


def upload_values(league, matched_df: pd.DataFrame) -> dict[str, int]:
    """Upload auction values for matched players to Yahoo Fantasy.

    Sets the pre-draft auction values that appear in Yahoo's draft interface.

    Args:
        league: A yahoo_fantasy_api League object.
        matched_df: DataFrame with 'yahoo_id' and 'dollar_value' columns.
            Only rows with non-null yahoo_id will be uploaded.

    Returns:
        Dict with counts: {'uploaded': N, 'skipped': M}.
    """
    to_upload = matched_df.dropna(subset=["yahoo_id"])
    uploaded = 0
    skipped = 0

    for _, row in to_upload.iterrows():
        try:
            player_id = int(row["yahoo_id"])
            value = max(1, int(row["dollar_value"]))
            league.edit_auction_value(player_id, value)
            uploaded += 1
        except Exception as e:
            print(f"  Failed to upload {row.get('name', 'unknown')}: {e}")
            skipped += 1

    return {"uploaded": uploaded, "skipped": skipped}

"""Revaluation engine — recalculates player values after each draft pick."""

import json

from draft.state import DraftState, DraftPick, save_state


def record_pick(
    state: DraftState,
    player_name: str,
    price: int,
    team_id: int,
) -> DraftState:
    """Record a draft pick and recalculate all remaining player values.

    Steps:
    1. Snapshot current state for undo
    2. Remove player from available pool
    3. Update team budget and roster
    4. Recalculate values for all remaining players

    Args:
        state: Current draft state.
        player_name: Name of the drafted player.
        price: Auction price paid.
        team_id: ID of the team that drafted the player.

    Returns:
        Updated draft state with recalculated values.

    Raises:
        ValueError: If player not found or team invalid.
    """
    if player_name not in state.players:
        raise ValueError(f"Player '{player_name}' not found in available pool.")
    if team_id not in state.teams:
        raise ValueError(f"Team {team_id} not found.")

    team = state.teams[team_id]
    if price > team.remaining_budget:
        raise ValueError(
            f"Team {team_id} only has ${team.remaining_budget} remaining "
            f"(tried to spend ${price})."
        )
    if team.roster_size >= state.total_roster_slots:
        raise ValueError(f"Team {team_id} roster is full.")

    # Snapshot for undo (exclude previous snapshots to save memory)
    snapshot_data = state.model_dump()
    snapshot_data["snapshots"] = []
    state.snapshots.append(json.dumps(snapshot_data))
    # Keep only last 50 snapshots to bound memory
    if len(state.snapshots) > 50:
        state.snapshots = state.snapshots[-50:]

    # Record the pick
    pick = DraftPick(
        player_name=player_name,
        price=price,
        team_id=team_id,
        pick_number=len(state.draft_log) + 1,
    )
    state.draft_log.append(pick)
    team.roster.append(pick)

    # Remove player from pool
    del state.players[player_name]

    # Recalculate values for remaining players
    _recalculate_values(state)

    # Auto-save
    save_state(state)

    return state


def undo_last_pick(state: DraftState) -> DraftState:
    """Undo the last draft pick by restoring the previous snapshot.

    Args:
        state: Current draft state.

    Returns:
        Previous draft state.

    Raises:
        ValueError: If there are no picks to undo.
    """
    if not state.snapshots:
        raise ValueError("No picks to undo.")

    snapshot_json = state.snapshots.pop()
    restored = DraftState(**json.loads(snapshot_json))
    # Carry forward any remaining snapshots
    restored.snapshots = state.snapshots

    save_state(restored)
    return restored


def _recalculate_values(state: DraftState) -> None:
    """Recalculate auction values for all remaining players.

    Uses the same proportional VAR method as the initial valuation,
    but based on remaining budget and remaining player pool.

    Modifies state.players in place.
    """
    remaining = state.players
    if not remaining:
        return

    # Total spendable = remaining budgets minus $1 per empty slot
    total_spendable = 0.0
    for team in state.teams.values():
        empty_slots = state.total_roster_slots - team.roster_size
        if empty_slots > 0:
            spendable = team.remaining_budget - empty_slots
            total_spendable += max(0, spendable)

    # Total positive VAR among remaining players
    total_var = sum(max(0, p.var) for p in remaining.values())

    if total_var <= 0 or total_spendable <= 0:
        for p in remaining.values():
            p.current_value = 1.0
        return

    # Count players with positive VAR for the $1 floor
    positive_var_count = sum(1 for p in remaining.values() if p.var > 0)

    # Distribute: each positive-VAR player gets proportional share + $1
    distributable = total_spendable - positive_var_count
    if distributable < 0:
        distributable = 0

    for p in remaining.values():
        if p.var > 0:
            p.current_value = (p.var / total_var) * distributable + 1
        else:
            p.current_value = 0.0

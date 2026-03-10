"""Draft tracker — records picks, assigns positions, and supports edits."""

import json

from draft.state import DraftState, DraftPick, PlayerValue, ROSTER_CONFIG, save_state


def _assign_position_slot(
    team_roster: list[DraftPick],
    player_positions: list[str],
    player_type: str,
) -> str:
    """Assign a drafted player to the scarcest available roster slot.

    Checks which eligible positions still have open slots, and assigns the
    player to the position with the fewest remaining openings (scarcest first).
    Falls back to Util (for hitters) then BN if all specific slots are full.

    Args:
        team_roster: Current roster picks for the team.
        player_positions: List of position strings the player is eligible for.
        player_type: Either "hitter" or "pitcher".

    Returns:
        The assigned position slot string (e.g. "SS", "OF", "P", "Util", "BN").

    Raises:
        ValueError: If no roster slot is available.
    """
    # Count how many of each position are already filled
    filled = {}
    for pick in team_roster:
        pos = pick.assigned_position
        if pos:
            filled[pos] = filled.get(pos, 0) + 1

    # Map player positions to roster slot keys
    eligible_slots = []
    for pos in player_positions:
        if pos in ("SP", "RP"):
            if "P" not in eligible_slots:
                eligible_slots.append("P")
        elif pos == "P":
            if "P" not in eligible_slots:
                eligible_slots.append("P")
        elif pos == "Util":
            continue  # Handle Util as fallback
        elif pos in ROSTER_CONFIG:
            eligible_slots.append(pos)

    # Sort by remaining slots ascending (scarcest first)
    candidates = []
    for slot in eligible_slots:
        max_slots = ROSTER_CONFIG.get(slot, 0)
        used = filled.get(slot, 0)
        remaining = max_slots - used
        if remaining > 0:
            candidates.append((remaining, slot))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    # Fallback: Util for hitters
    if player_type == "hitter":
        util_remaining = ROSTER_CONFIG.get("Util", 0) - filled.get("Util", 0)
        if util_remaining > 0:
            return "Util"

    # Fallback: Bench
    bn_remaining = ROSTER_CONFIG.get("BN", 0) - filled.get("BN", 0)
    if bn_remaining > 0:
        return "BN"

    raise ValueError("No roster slot available for this player.")


def record_pick(
    state: DraftState,
    player_name: str,
    price: int,
    team_id: int,
) -> DraftState:
    """Record a draft pick and assign to the best roster slot.

    Steps:
    1. Snapshot current state for undo
    2. Remove player from available pool
    3. Assign to scarcest open roster slot
    4. Update team budget and roster

    Args:
        state: Current draft state.
        player_name: Name of the drafted player.
        price: Auction price paid.
        team_id: ID of the team that drafted the player.

    Returns:
        Updated draft state.

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

    # Snapshot the player for potential restore on remove
    player = state.players[player_name]
    player_snapshot_json = player.model_dump_json()

    # Assign position slot
    assigned_position = _assign_position_slot(
        team.roster, player.positions, player.player_type
    )

    # Record the pick
    pick = DraftPick(
        player_name=player_name,
        price=price,
        team_id=team_id,
        pick_number=len(state.draft_log) + 1,
        assigned_position=assigned_position,
        player_snapshot=player_snapshot_json,
    )
    state.draft_log.append(pick)
    team.roster.append(pick)

    # Remove player from pool
    del state.players[player_name]

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


def add_unknown_player(
    state: DraftState,
    name: str,
    positions: list[str],
    player_type: str,
) -> None:
    """Add an unknown player to the pool so they can be drafted.

    Creates a PlayerValue with zero value/points and adds it to
    both the player pool and original_values_map.

    Args:
        state: Current draft state.
        name: Player name.
        positions: List of eligible positions (e.g. ["SS", "2B"]).
        player_type: Either "hitter" or "pitcher".

    Raises:
        ValueError: If a player with this name already exists.
    """
    if name in state.players:
        raise ValueError(f"Player '{name}' already exists in pool.")

    player = PlayerValue(
        name=name,
        positions=positions,
        player_type=player_type,
    )
    state.players[name] = player
    state.original_values_map[name] = 0.0


def edit_pick_price(state: DraftState, pick_number: int, new_price: int) -> None:
    """Edit the price of an existing draft pick.

    Args:
        state: Current draft state.
        pick_number: The pick number to edit.
        new_price: New price to set.

    Raises:
        ValueError: If pick not found or new price exceeds team budget.
    """
    # Snapshot for undo
    snapshot_data = state.model_dump()
    snapshot_data["snapshots"] = []
    state.snapshots.append(json.dumps(snapshot_data))
    if len(state.snapshots) > 50:
        state.snapshots = state.snapshots[-50:]

    # Find the pick in draft_log
    log_pick = None
    for pick in state.draft_log:
        if pick.pick_number == pick_number:
            log_pick = pick
            break
    if log_pick is None:
        raise ValueError(f"Pick #{pick_number} not found.")

    team = state.teams[log_pick.team_id]

    # Check budget: remaining + old price - new price >= 0
    price_diff = new_price - log_pick.price
    if team.remaining_budget - price_diff < 0:
        raise ValueError(
            f"Team {team.name} can't afford price change "
            f"(remaining: ${team.remaining_budget}, change: +${price_diff})."
        )

    # Update price in both draft_log and team roster
    log_pick.price = new_price
    for roster_pick in team.roster:
        if roster_pick.pick_number == pick_number:
            roster_pick.price = new_price
            break

    save_state(state)


def remove_pick(state: DraftState, pick_number: int) -> None:
    """Remove a draft pick, returning the player to the pool.

    Args:
        state: Current draft state.
        pick_number: The pick number to remove.

    Raises:
        ValueError: If pick not found.
    """
    # Snapshot for undo
    snapshot_data = state.model_dump()
    snapshot_data["snapshots"] = []
    state.snapshots.append(json.dumps(snapshot_data))
    if len(state.snapshots) > 50:
        state.snapshots = state.snapshots[-50:]

    # Find and remove from draft_log
    log_pick = None
    for i, pick in enumerate(state.draft_log):
        if pick.pick_number == pick_number:
            log_pick = state.draft_log.pop(i)
            break
    if log_pick is None:
        raise ValueError(f"Pick #{pick_number} not found.")

    # Remove from team roster
    team = state.teams[log_pick.team_id]
    team.roster = [p for p in team.roster if p.pick_number != pick_number]

    # Restore player to pool from snapshot
    if log_pick.player_snapshot:
        player = PlayerValue(**json.loads(log_pick.player_snapshot))
        state.players[player.name] = player
    else:
        # Fallback: create minimal player entry
        state.players[log_pick.player_name] = PlayerValue(
            name=log_pick.player_name,
            original_value=state.original_values_map.get(log_pick.player_name, 0),
            current_value=state.original_values_map.get(log_pick.player_name, 0),
        )

    save_state(state)

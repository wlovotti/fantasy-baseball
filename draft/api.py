"""FastAPI routes for the live draft tracker."""

from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from draft.state import DraftState, ROSTER_CONFIG, save_state
from draft.tracker import (
    record_pick,
    undo_last_pick,
    add_unknown_player,
    edit_pick_price,
    remove_pick,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TIER_BOUNDARIES = [30, 20, 10, 5, 1]
TIER_LABELS = ["$30+", "$20-29", "$10-19", "$5-9", "$1-4"]
TIER_POSITIONS = ["C", "1B", "2B", "3B", "SS", "OF", "P"]

# Position slot labels for the position slots table (excludes BN for display)
POSITION_SLOT_LABELS = ["C", "1B", "2B", "3B", "SS", "OF", "Util", "P", "BN"]

app = FastAPI(title="Fantasy Baseball Draft Tracker")
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=PROJECT_ROOT / "templates")

# Global draft state — initialized by run_draft.py before server starts
draft_state: DraftState | None = None


def set_state(state: DraftState) -> None:
    """Set the global draft state (called during startup).

    Args:
        state: Initialized DraftState to use.
    """
    global draft_state
    draft_state = state


def get_state() -> DraftState:
    """Get the current draft state.

    Returns:
        Current DraftState.

    Raises:
        RuntimeError: If state hasn't been initialized.
    """
    if draft_state is None:
        raise RuntimeError("Draft state not initialized")
    return draft_state


class DraftPickRequest(BaseModel):
    """Request body for recording a draft pick."""

    player_name: str
    price: int
    team_id: int


class AddPlayerRequest(BaseModel):
    """Request body for adding an unknown player."""

    name: str
    positions: List[str]
    player_type: str


class EditPriceRequest(BaseModel):
    """Request body for editing a pick's price."""

    price: int


@app.get("/", response_class=HTMLResponse)
async def draft_board(request: Request):
    """Render the draft board HTML page."""
    state = get_state()
    return templates.TemplateResponse(
        "draft.html",
        {
            "request": request,
            "teams": state.teams,
            "num_teams": len(state.teams),
            "my_team_id": state.my_team_id,
        },
    )


@app.get("/api/players")
async def search_players(q: str = "", limit: int = 50):
    """Search available players by name prefix.

    Args:
        q: Search query string.
        limit: Maximum results to return.

    Returns:
        List of matching players with values.
    """
    state = get_state()
    query = q.lower().strip()

    if not query:
        # Return top players by original value
        players = sorted(
            state.players.values(),
            key=lambda p: p.original_value,
            reverse=True,
        )[:limit]
    else:
        players = [
            p for p in state.players.values()
            if query in p.name.lower()
        ]
        players.sort(key=lambda p: p.original_value, reverse=True)
        players = players[:limit]

    return [
        {
            "name": p.name,
            "team": p.team,
            "positions": p.positions,
            "player_type": p.player_type,
            "points": round(p.points, 1),
            "original_value": round(p.original_value, 1),
            "util_value": round(p.util_value, 1),
        }
        for p in players
    ]


@app.post("/api/draft")
async def draft_player(pick: DraftPickRequest):
    """Record a draft pick.

    Args:
        pick: The draft pick details.

    Returns:
        Updated state summary.
    """
    global draft_state
    state = get_state()
    try:
        draft_state = record_pick(state, pick.player_name, pick.price, pick.team_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _state_summary(draft_state)


@app.post("/api/undo")
async def undo():
    """Undo the last draft pick.

    Returns:
        Updated state summary after undo.
    """
    global draft_state
    state = get_state()
    try:
        draft_state = undo_last_pick(state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _state_summary(draft_state)


@app.get("/api/state")
async def full_state():
    """Get the full current draft state.

    Returns:
        Complete state summary.
    """
    return _state_summary(get_state())


@app.get("/api/team/{team_id}")
async def team_detail(team_id: int):
    """Get detailed state for a single team.

    Args:
        team_id: The team ID to look up.

    Returns:
        Team budget, roster, and remaining capacity.
    """
    state = get_state()
    if team_id not in state.teams:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found")

    team = state.teams[team_id]
    projected_value = sum(
        state.original_values_map.get(p.player_name, 0) for p in team.roster
    )
    return {
        "team_id": team.team_id,
        "name": team.name,
        "budget": team.budget,
        "spent": team.spent,
        "remaining_budget": team.remaining_budget,
        "roster_size": team.roster_size,
        "max_roster": state.total_roster_slots,
        "max_bid": team.remaining_budget - (state.total_roster_slots - team.roster_size - 1)
        if team.roster_size < state.total_roster_slots
        else 0,
        "projected_value": round(projected_value, 1),
        "roster": [
            {
                "player_name": p.player_name,
                "price": p.price,
                "pick_number": p.pick_number,
                "assigned_position": p.assigned_position,
                "model_value": round(state.original_values_map.get(p.player_name, 0), 1),
            }
            for p in team.roster
        ],
    }


@app.post("/api/player/add")
async def add_player(req: AddPlayerRequest):
    """Add an unknown player to the pool.

    Args:
        req: Player details (name, positions, type).

    Returns:
        Updated state summary.
    """
    state = get_state()
    try:
        add_unknown_player(state, req.name, req.positions, req.player_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _state_summary(state)


@app.post("/api/pick/{pick_number}/edit")
async def edit_pick(pick_number: int, req: EditPriceRequest):
    """Edit the price of a draft pick.

    Args:
        pick_number: The pick number to edit.
        req: New price.

    Returns:
        Updated state summary.
    """
    state = get_state()
    try:
        edit_pick_price(state, pick_number, req.price)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _state_summary(state)


@app.post("/api/pick/{pick_number}/remove")
async def remove_pick_route(pick_number: int):
    """Remove a draft pick and return the player to the pool.

    Args:
        pick_number: The pick number to remove.

    Returns:
        Updated state summary.
    """
    state = get_state()
    try:
        remove_pick(state, pick_number)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _state_summary(state)


def _build_tier_counts(state: DraftState) -> dict:
    """Build tier depletion counts for remaining players by position.

    Counts undrafted players in each value tier for each position.
    Multi-position players count in each eligible position. Util is excluded.
    Pitchers (any position containing 'P' that isn't a hitter position) pool under 'P'.

    Args:
        state: Current DraftState with remaining player pool.

    Returns:
        Dict with 'tiers' (list of labels) and 'positions' (dict mapping
        position to list of counts per tier).
    """
    counts: dict[str, list[int]] = {pos: [0] * len(TIER_BOUNDARIES) for pos in TIER_POSITIONS}

    for player in state.players.values():
        value = player.original_value
        if value < 1:
            continue

        # Determine which tier this player falls into
        tier_idx = None
        for i, boundary in enumerate(TIER_BOUNDARIES):
            if value >= boundary:
                tier_idx = i
                break
        if tier_idx is None:
            continue

        # Map player positions to tier positions
        mapped_positions: set[str] = set()
        for pos in player.positions:
            if pos == "Util":
                continue
            if pos in TIER_POSITIONS:
                mapped_positions.add(pos)
            elif pos in ("SP", "RP"):
                mapped_positions.add("P")

        for pos in mapped_positions:
            counts[pos][tier_idx] += 1

    return {"tiers": TIER_LABELS, "positions": counts}


def _build_position_slots(state: DraftState) -> dict:
    """Build position slots remaining for each team.

    For each team, counts how many of each roster position slot remain open
    based on assigned_position values of their drafted players.

    Args:
        state: Current DraftState.

    Returns:
        Dict with 'labels' (position names), 'teams' (dict mapping team_id to
        remaining slot counts), and 'opponents_total' (sum of non-my_team slots).
    """
    teams_slots = {}
    opponents_total = {pos: 0 for pos in POSITION_SLOT_LABELS}

    for tid, team in state.teams.items():
        filled = {}
        for pick in team.roster:
            pos = pick.assigned_position
            if pos:
                filled[pos] = filled.get(pos, 0) + 1

        remaining = {}
        for pos in POSITION_SLOT_LABELS:
            max_slots = ROSTER_CONFIG.get(pos, 0)
            used = filled.get(pos, 0)
            remaining[pos] = max(0, max_slots - used)

        teams_slots[tid] = remaining

        if tid != state.my_team_id:
            for pos in POSITION_SLOT_LABELS:
                opponents_total[pos] += remaining[pos]

    return {
        "labels": POSITION_SLOT_LABELS,
        "teams": teams_slots,
        "opponents_total": opponents_total,
    }


def _state_summary(state: DraftState) -> dict:
    """Build a summary dict of the current draft state.

    Args:
        state: Current DraftState.

    Returns:
        Summary including top players, team budgets, picks remaining, and
        position slot data.
    """
    top_players = sorted(
        state.players.values(),
        key=lambda p: p.original_value,
        reverse=True,
    )[:100]

    total_picks = state.total_roster_slots * len(state.teams)

    return {
        "picks_remaining": total_picks - len(state.draft_log),
        "picks_made": len(state.draft_log),
        "my_team_id": state.my_team_id,
        "top_players": [
            {
                "name": p.name,
                "team": p.team,
                "positions": p.positions,
                "player_type": p.player_type,
                "points": round(p.points, 1),
                "original_value": round(p.original_value, 1),
                "util_value": round(p.util_value, 1),
            }
            for p in top_players
        ],
        "teams": {
            tid: {
                "name": t.name,
                "remaining_budget": t.remaining_budget,
                "roster_size": t.roster_size,
                "max_bid": t.remaining_budget - (state.total_roster_slots - t.roster_size - 1)
                if t.roster_size < state.total_roster_slots
                else 0,
                "projected_value": round(
                    sum(state.original_values_map.get(p.player_name, 0) for p in t.roster),
                    1,
                ),
            }
            for tid, t in state.teams.items()
        },
        "tier_counts": _build_tier_counts(state),
        "position_slots": _build_position_slots(state),
        "recent_picks": [
            {
                "player_name": p.player_name,
                "price": p.price,
                "team_id": p.team_id,
                "team_name": state.teams[p.team_id].name if p.team_id in state.teams else f"Team {p.team_id}",
                "pick_number": p.pick_number,
            }
            for p in reversed(state.draft_log[-10:])
        ],
    }

"""FastAPI routes for the live draft tracker."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from draft.state import DraftState, save_state
from draft.tracker import record_pick, undo_last_pick

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TIER_BOUNDARIES = [30, 20, 10, 5, 1]
TIER_LABELS = ["$30+", "$20-29", "$10-19", "$5-9", "$1-4"]
TIER_POSITIONS = ["C", "1B", "2B", "3B", "SS", "OF", "P"]

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
        },
    )


@app.get("/api/players")
async def search_players(q: str = "", limit: int = 50):
    """Search available players by name prefix.

    Args:
        q: Search query string.
        limit: Maximum results to return.

    Returns:
        List of matching players with current values.
    """
    state = get_state()
    query = q.lower().strip()

    if not query:
        # Return top players by current value
        players = sorted(
            state.players.values(),
            key=lambda p: p.current_value,
            reverse=True,
        )[:limit]
    else:
        players = [
            p for p in state.players.values()
            if query in p.name.lower()
        ]
        players.sort(key=lambda p: p.current_value, reverse=True)
        players = players[:limit]

    return [
        {
            "name": p.name,
            "team": p.team,
            "positions": p.positions,
            "player_type": p.player_type,
            "points": round(p.points, 1),
            "original_value": round(p.original_value, 1),
            "current_value": round(p.current_value, 1),
            "util_value": round(p.util_value, 1),
        }
        for p in players
    ]


@app.post("/api/draft")
async def draft_player(pick: DraftPickRequest):
    """Record a draft pick and recalculate values.

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
        Complete state including players, teams, and inflation.
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
        "roster": [
            {"player_name": p.player_name, "price": p.price, "pick_number": p.pick_number}
            for p in team.roster
        ],
    }


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


def _state_summary(state: DraftState) -> dict:
    """Build a summary dict of the current draft state.

    Args:
        state: Current DraftState.

    Returns:
        Summary including top players, team budgets, and inflation.
    """
    top_players = sorted(
        state.players.values(),
        key=lambda p: p.current_value,
        reverse=True,
    )[:100]

    return {
        "inflation_factor": round(state.inflation_factor, 3),
        "players_remaining": len(state.players),
        "picks_made": len(state.draft_log),
        "top_players": [
            {
                "name": p.name,
                "team": p.team,
                "positions": p.positions,
                "player_type": p.player_type,
                "points": round(p.points, 1),
                "original_value": round(p.original_value, 1),
                "current_value": round(p.current_value, 1),
                "util_value": round(p.util_value, 1),
                "value_change": round(p.current_value - p.original_value, 1),
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
            }
            for tid, t in state.teams.items()
        },
        "tier_counts": _build_tier_counts(state),
        "recent_picks": [
            {
                "player_name": p.player_name,
                "price": p.price,
                "team_id": p.team_id,
                "pick_number": p.pick_number,
            }
            for p in reversed(state.draft_log[-10:])
        ],
    }

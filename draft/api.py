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

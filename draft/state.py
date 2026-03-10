"""Draft state data model with JSON persistence and undo support."""

import json
import copy
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel


class PlayerValue(BaseModel):
    """A player with their current auction valuation."""

    name: str
    team: str = ""
    positions: List[str] = []
    player_type: str = "hitter"
    points: float = 0.0
    original_value: float = 0.0
    current_value: float = 0.0
    var: float = 0.0
    allocation_var: float = 0.0
    util_value: float = 0.0


class DraftPick(BaseModel):
    """A single draft pick record."""

    player_name: str
    price: int
    team_id: int
    pick_number: int
    assigned_position: str = ""
    player_snapshot: str = ""  # JSON of PlayerValue at time of draft, for restore on remove


class TeamState(BaseModel):
    """State of a single fantasy team during the draft."""

    team_id: int
    name: str = ""
    budget: int = 260
    roster: List[DraftPick] = []

    @property
    def spent(self) -> int:
        """Total dollars spent so far."""
        return sum(p.price for p in self.roster)

    @property
    def remaining_budget(self) -> int:
        """Budget remaining."""
        return self.budget - self.spent

    @property
    def roster_size(self) -> int:
        """Number of players drafted."""
        return len(self.roster)


class DraftState(BaseModel):
    """Complete draft state with player pool, teams, and history."""

    players: Dict[str, PlayerValue] = {}
    teams: Dict[int, TeamState] = {}
    draft_log: List[DraftPick] = []
    snapshots: List[str] = []  # JSON strings of previous states for undo
    total_roster_slots: int = 24
    budget_per_team: int = 260
    my_team_id: int = 0
    original_values_map: Dict[str, float] = {}


# Roster slot configuration for position assignment
ROSTER_CONFIG = {
    "C": 1,
    "1B": 1,
    "2B": 1,
    "3B": 1,
    "SS": 1,
    "OF": 4,
    "Util": 2,
    "P": 8,
    "BN": 4,
}


def initialize_state(
    values_csv: Union[str, Path],
    num_teams: int = 14,
    budget: int = 260,
    roster_slots: int = 24,
    team_names: Optional[Dict[int, str]] = None,
    my_team_id: int = 0,
) -> DraftState:
    """Initialize draft state from a player values CSV.

    Args:
        values_csv: Path to CSV with columns: name, team, positions, player_type,
            points, dollar_value.
        num_teams: Number of teams in the league.
        budget: Auction budget per team.
        roster_slots: Total roster spots per team.
        team_names: Optional mapping of team_id -> team name. If None, uses
            "Team 1", "Team 2", etc.
        my_team_id: ID of the user's team (for highlighting in the UI).

    Returns:
        Initialized DraftState ready for drafting.
    """
    import pandas as pd

    df = pd.read_csv(values_csv)
    players = {}
    original_values_map = {}
    for _, row in df.iterrows():
        name = row["name"]
        pos_str = str(row.get("positions", ""))
        positions = [p.strip() for p in pos_str.split(",") if p.strip()]
        dollar_val = float(row.get("dollar_value", 0))
        players[name] = PlayerValue(
            name=name,
            team=str(row.get("team", "")),
            positions=positions,
            player_type=str(row.get("player_type", "hitter")),
            points=float(row.get("points", 0)),
            original_value=dollar_val,
            current_value=dollar_val,
            var=float(row.get("var", 0)),
            allocation_var=float(row.get("allocation_var", 0)),
            util_value=float(row.get("util_value", 0)),
        )
        original_values_map[name] = dollar_val

    teams = {}
    for i in range(1, num_teams + 1):
        name = team_names[i] if team_names and i in team_names else f"Team {i}"
        teams[i] = TeamState(team_id=i, name=name, budget=budget)

    return DraftState(
        players=players,
        teams=teams,
        total_roster_slots=roster_slots,
        budget_per_team=budget,
        my_team_id=my_team_id,
        original_values_map=original_values_map,
    )


def save_state(state: DraftState, path: Union[str, Path] = "draft_state.json") -> None:
    """Save draft state to JSON file.

    Args:
        state: Current draft state.
        path: File path to save to.
    """
    # Don't persist snapshots to disk (they can be large)
    data = state.model_dump()
    data["snapshots"] = []
    Path(path).write_text(json.dumps(data, indent=2))


def load_state(path: Union[str, Path] = "draft_state.json") -> DraftState:
    """Load draft state from JSON file.

    Args:
        path: File path to load from.

    Returns:
        Restored DraftState.

    Raises:
        FileNotFoundError: If the state file doesn't exist.
    """
    data = json.loads(Path(path).read_text())
    return DraftState(**data)

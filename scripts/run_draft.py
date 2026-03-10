#!/usr/bin/env python3
"""CLI: Launch the live draft tracker web app."""

import sys
import webbrowser
from pathlib import Path
from typing import Optional

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fetch_yahoo_team_names(my_team_name: str) -> tuple[dict[int, str], int]:
    """Fetch team names from Yahoo and find the user's team ID.

    Args:
        my_team_name: Name of the user's team to match.

    Returns:
        Tuple of (team_names dict mapping 1-indexed ID to name, my_team_id).
    """
    from yahoo.league_client import get_league

    click.echo("Fetching Yahoo league team names...")
    league = get_league()
    teams_data = league.teams()

    team_names = {}
    my_team_id = 0
    # teams_data is a dict keyed by team_key, each value has team_id and name
    for team_info in teams_data.values():
        tid = int(team_info["team_id"])
        name = team_info["name"]
        team_names[tid] = name
        if name.lower() == my_team_name.lower():
            my_team_id = tid

    if my_team_id == 0:
        click.echo(f"  Warning: '{my_team_name}' not found in league teams.")
        click.echo(f"  Available teams: {', '.join(team_names.values())}")
    else:
        click.echo(f"  Found {len(team_names)} teams. Your team: {team_names[my_team_id]} (#{my_team_id})")

    return team_names, my_team_id


@click.command()
@click.argument("values_csv", type=click.Path(exists=True))
@click.option("--teams", "-t", default=14, help="Number of teams (default: 14)")
@click.option("--budget", "-b", default=260, help="Budget per team (default: 260)")
@click.option("--roster", "-r", default=24, help="Roster slots per team (default: 24)")
@click.option("--port", "-p", default=8000, help="Server port (default: 8000)")
@click.option("--resume", is_flag=True, help="Resume from saved draft state")
@click.option("--no-browser", is_flag=True, help="Don't auto-open browser")
@click.option("--my-team", default="BK Whoppers", help="Your team name (default: BK Whoppers)")
@click.option("--no-yahoo", is_flag=True, help="Skip Yahoo API for team names (use generic names)")
def main(
    values_csv: str,
    teams: int,
    budget: int,
    roster: int,
    port: int,
    resume: bool,
    no_browser: bool,
    my_team: str,
    no_yahoo: bool,
) -> None:
    """Launch the live draft tracker web app.

    VALUES_CSV: Path to player values CSV (output of generate_values.py).
    """
    from draft.state import initialize_state, load_state
    from draft.api import app, set_state

    state_file = Path("draft_state.json")

    if resume and state_file.exists():
        click.echo("Resuming from saved draft state...")
        state = load_state(state_file)
        click.echo(
            f"  {state.players.__len__()} players remaining, "
            f"{len(state.draft_log)} picks made"
        )
        # Allow updating my_team_id on resume
        if my_team:
            for tid, team in state.teams.items():
                if team.name.lower() == my_team.lower():
                    state.my_team_id = tid
                    click.echo(f"  Your team: {team.name} (#{tid})")
                    break
    else:
        # Fetch Yahoo team names unless --no-yahoo
        team_names = None
        my_team_id = 0
        if not no_yahoo:
            try:
                team_names, my_team_id = _fetch_yahoo_team_names(my_team)
            except Exception as e:
                click.echo(f"  Yahoo fetch failed: {e}")
                click.echo("  Falling back to generic team names.")

        click.echo("Initializing fresh draft state...")
        state = initialize_state(
            values_csv,
            num_teams=teams,
            budget=budget,
            roster_slots=roster,
            team_names=team_names,
            my_team_id=my_team_id,
        )
        click.echo(f"  {len(state.players)} players loaded")

    set_state(state)

    url = f"http://localhost:{port}"
    click.echo(f"\nDraft tracker running at {url}")
    click.echo("Press Ctrl+C to stop.\n")

    if not no_browser:
        webbrowser.open(url)

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()

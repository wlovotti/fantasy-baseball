#!/usr/bin/env python3
"""CLI: Launch the live draft tracker web app."""

import sys
import webbrowser
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@click.command()
@click.argument("values_csv", type=click.Path(exists=True))
@click.option("--teams", "-t", default=14, help="Number of teams (default: 14)")
@click.option("--budget", "-b", default=260, help="Budget per team (default: 260)")
@click.option("--roster", "-r", default=24, help="Roster slots per team (default: 24)")
@click.option("--port", "-p", default=8000, help="Server port (default: 8000)")
@click.option("--resume", is_flag=True, help="Resume from saved draft state")
@click.option("--no-browser", is_flag=True, help="Don't auto-open browser")
def main(
    values_csv: str,
    teams: int,
    budget: int,
    roster: int,
    port: int,
    resume: bool,
    no_browser: bool,
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
    else:
        click.echo("Initializing fresh draft state...")
        state = initialize_state(values_csv, num_teams=teams, budget=budget, roster_slots=roster)
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

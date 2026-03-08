"""CLI entry point for Monte Carlo draft simulation.

Simulates auction drafts to evaluate whether our model's values produce
better rosters than Yahoo-anchored competitors.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path for absolute imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import click

from config.league import LEAGUE
from simulation.engine import run_simulations


@click.command()
@click.option(
    "--values",
    default="player_values.csv",
    type=click.Path(exists=True),
    help="Our player values CSV.",
)
@click.option(
    "--yahoo",
    default="projections/yahoo_auction_values.txt",
    type=click.Path(exists=True),
    help="Yahoo auction values file.",
)
@click.option(
    "-n",
    "--simulations",
    default=10,
    type=int,
    help="Number of simulations to run.",
)
@click.option(
    "--noise",
    default=0.18,
    type=float,
    help="Bid noise std dev as fraction of base value.",
)
@click.option(
    "--seed",
    default=None,
    type=int,
    help="Random seed for reproducibility.",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Show detailed roster for each simulation.",
)
def main(
    values: str,
    yahoo: str,
    simulations: int,
    noise: float,
    seed: int | None,
    verbose: bool,
) -> None:
    """Run Monte Carlo draft simulations to evaluate our model vs Yahoo values."""
    click.echo(f"Running {simulations} draft simulations...")
    click.echo(f"  Our values: {values}")
    click.echo(f"  Yahoo values: {yahoo}")
    click.echo(f"  Noise: {noise:.0%}")
    if seed is not None:
        click.echo(f"  Seed: {seed}")
    click.echo()

    results = run_simulations(values, yahoo, n=simulations, seed=seed, noise_std=noise)

    if verbose:
        for i, dr in enumerate(results.draft_results):
            user = dr.user_team
            click.echo(f"=== Simulation {i + 1} ===")
            click.echo(f"User rank: {dr.user_rank}/14  |  "
                        f"Points: {user.total_points:.0f}  |  "
                        f"Budget left: ${user.budget}  |  "
                        f"Roster: {LEAGUE.roster_size - user.remaining_slots}/{LEAGUE.roster_size}")
            click.echo()

            # Group roster by slot
            slot_groups: dict[str, list] = {}
            for dp in user.roster:
                slot_key = dp.slot.value if hasattr(dp.slot, "value") else str(dp.slot)
                slot_groups.setdefault(slot_key, []).append(dp)

            slot_order = ["C", "1B", "2B", "3B", "SS", "OF", "Util", "P", "Bench"]
            for slot_name in slot_order:
                drafted = slot_groups.get(slot_name, [])
                for dp in sorted(drafted, key=lambda d: d.player.points, reverse=True):
                    click.echo(
                        f"  {slot_name:<5} {dp.player.name:<30} "
                        f"${dp.price:<4} {dp.player.points:>7.0f} pts  "
                        f"(our=${dp.player.our_value}, yahoo=${dp.player.yahoo_value})"
                    )

            if dr.undrafted:
                click.echo(f"\n  Undrafted: {len(dr.undrafted)} players")

            click.echo()

    # Summary
    click.echo("=" * 60)
    click.echo("AGGREGATE RESULTS")
    click.echo("=" * 60)
    click.echo()
    click.echo(f"Simulations: {results.n_simulations}")
    click.echo()
    click.echo("Total Projected Points:")
    click.echo(f"  User:        {results.mean_user_points:>8.0f} +/- {results.std_user_points:.0f}")
    click.echo(f"  Competitors: {results.mean_competitor_points:>8.0f} +/- {results.std_competitor_points:.0f}")
    diff = results.mean_user_points - results.mean_competitor_points
    click.echo(f"  Advantage:   {diff:>+8.0f} points ({diff / results.mean_competitor_points:+.1%})")
    click.echo()
    click.echo("Rankings:")
    click.echo(f"  Average rank:  {results.mean_user_rank:.1f} / 14")
    click.echo(f"  Win rate:      {results.win_rate:.0%}")
    click.echo(f"  Top-4 rate:    {results.top4_rate:.0%}")
    click.echo()
    click.echo("Budget Utilization:")
    click.echo(f"  User avg remaining:       ${results.mean_user_budget_remaining:.1f}")
    click.echo(f"  Competitor avg remaining:  ${results.mean_competitor_budget_remaining:.1f}")
    click.echo()

    # Roster fill check
    for i, dr in enumerate(results.draft_results):
        for team in dr.teams:
            filled = LEAGUE.roster_size - team.remaining_slots
            if filled != LEAGUE.roster_size:
                click.echo(
                    f"  WARNING: Sim {i+1} Team {team.team_id} only filled "
                    f"{filled}/{LEAGUE.roster_size} slots"
                )


if __name__ == "__main__":
    main()

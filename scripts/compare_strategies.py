"""CLI tool to compare bidding strategies via Monte Carlo draft simulation.

Runs three strategies head-to-head and prints a side-by-side comparison:
- Static: pre-computed model values (baseline, bench_hitters=1)
- Personal: custom bench allocation (bench_hitters=0)
- Dynamic: recalculates values after each user pick
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

# Add project root to path for absolute imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import click

from config.league import LEAGUE, LeagueSettings
from simulation.engine import (
    DraftResult,
    SimPlayer,
    SimTeam,
    load_simulation_players,
    parse_yahoo_values,
    run_one_draft,
)
from simulation.strategies import (
    dynamic_strategy,
    load_player_dataframe,
    personal_strategy,
    static_strategy,
)


def _run_strategy(
    strategy_name: str,
    players: list[SimPlayer],
    player_df,
    base_seed: int,
    n: int,
    noise_std: float,
) -> dict:
    """Run n simulations for a single strategy and collect results.

    Args:
        strategy_name: One of 'static', 'personal', 'dynamic'.
        players: List of SimPlayer objects for the simulation.
        player_df: Player DataFrame (needed for personal/dynamic strategies).
        base_seed: Base random seed for reproducibility.
        n: Number of simulations to run.
        noise_std: Bid noise standard deviation.

    Returns:
        Dictionary with lists of per-simulation metrics.
    """
    user_points: list[float] = []
    user_ranks: list[int] = []
    user_budgets: list[int] = []

    for i in range(n):
        rng = random.Random(base_seed + i)

        if strategy_name == "static":
            bid_fn = static_strategy(players)
            on_pick_fn = None
        elif strategy_name == "personal":
            bid_fn = personal_strategy(player_df, LeagueSettings(bench_hitters=0))
            on_pick_fn = None
        elif strategy_name == "dynamic":
            bid_fn, dynamic_on_pick = dynamic_strategy(player_df, LEAGUE)

            def _on_pick_wrapper(
                player: SimPlayer,
                winner: SimTeam,
                available: list[SimPlayer],
                _cb=dynamic_on_pick,
            ) -> None:
                """Fire dynamic revaluation only when user wins a player."""
                if winner.is_user:
                    _cb(player.name)

            on_pick_fn = _on_pick_wrapper
        else:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        result = run_one_draft(
            players, rng, noise_std,
            user_strategy=bid_fn,
            on_pick=on_pick_fn,
        )

        user = result.user_team
        user_points.append(user.total_points)
        user_ranks.append(result.user_rank)
        user_budgets.append(user.budget)

    return {
        "points": user_points,
        "ranks": user_ranks,
        "budgets": user_budgets,
    }


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
    help="Number of simulations per strategy.",
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
def main(
    values: str,
    yahoo: str,
    simulations: int,
    noise: float,
    seed: int | None,
) -> None:
    """Compare three bidding strategies via Monte Carlo draft simulation."""
    base_seed = seed if seed is not None else random.randint(0, 2**31)

    click.echo(f"Strategy Comparison ({simulations} simulations, seed={base_seed})")
    click.echo("=" * 64)
    click.echo()

    # Load data
    yahoo_values = parse_yahoo_values(yahoo)
    players = load_simulation_players(values, yahoo_values)
    player_df = load_player_dataframe(values)

    strategies = ["static", "personal", "dynamic"]
    labels = {
        "static": "Static (bh=1)",
        "personal": "Personal (bh=0)",
        "dynamic": "Dynamic (revalue)",
    }

    all_results: dict[str, dict] = {}
    for strat in strategies:
        click.echo(f"  Running {labels[strat]}...")
        all_results[strat] = _run_strategy(
            strat, players, player_df, base_seed, simulations, noise,
        )

    click.echo()

    # Compute summary stats
    def _mean(vals: list[float]) -> float:
        """Compute mean of a list of values."""
        return sum(vals) / len(vals)

    def _std(vals: list[float]) -> float:
        """Compute standard deviation of a list of values."""
        m = _mean(vals)
        return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))

    # Print comparison table
    header = f"{'':>20}  {'Static':>10}  {'Personal':>10}  {'Dynamic':>10}"
    subheader = f"{'':>20}  {'(bh=1)':>10}  {'(bh=0)':>10}  {'(revalue)':>10}"

    click.echo(header)
    click.echo(subheader)
    click.echo("-" * 64)

    # Mean Points
    row = f"{'Mean Points':>20}"
    for strat in strategies:
        row += f"  {_mean(all_results[strat]['points']):>10,.0f}"
    click.echo(row)

    # Std Points
    row = f"{'Std Points':>20}"
    for strat in strategies:
        row += f"  {_std(all_results[strat]['points']):>10,.0f}"
    click.echo(row)

    # Mean Rank
    row = f"{'Mean Rank':>20}"
    for strat in strategies:
        row += f"  {_mean(all_results[strat]['ranks']):>10.1f}"
    click.echo(row)

    # Win Rate
    row = f"{'Win Rate':>20}"
    for strat in strategies:
        wins = sum(1 for r in all_results[strat]["ranks"] if r == 1)
        rate = wins / simulations
        row += f"  {rate:>9.0%} "
    click.echo(row)

    # Top-4 Rate
    row = f"{'Top-4 Rate':>20}"
    for strat in strategies:
        top4 = sum(1 for r in all_results[strat]["ranks"] if r <= 4)
        rate = top4 / simulations
        row += f"  {rate:>9.0%} "
    click.echo(row)

    # Budget Remaining
    row = f"{'Budget Remaining':>20}"
    for strat in strategies:
        row += f"  {_mean(all_results[strat]['budgets']):>9.1f} "
    click.echo(row)

    click.echo("=" * 64)


if __name__ == "__main__":
    main()

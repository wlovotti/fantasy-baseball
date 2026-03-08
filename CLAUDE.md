# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fantasy baseball auction draft toolkit: valuation engine, Yahoo Fantasy API integration, and live draft tracker. Configured for a 14-team Yahoo league, $260/team budget, 24 roster spots, custom points scoring.

## Commands

```bash
# Install dependencies
.venv/bin/pip install -e ".[dev]"

# Run all tests
.venv/bin/pytest

# Run a single test file or specific test
.venv/bin/pytest tests/test_points.py
.venv/bin/pytest tests/test_points.py::test_batting_points -v

# Generate auction values (requires Yahoo auth for position eligibility)
.venv/bin/python scripts/generate_values.py projections/hitters.csv projections/pitchers.csv

# Run live draft tracker (FastAPI app on localhost:8000)
.venv/bin/python scripts/run_draft.py player_values.csv
.venv/bin/python scripts/run_draft.py player_values.csv --resume draft_state.json

# Analyze past Yahoo drafts to calibrate bench allocation
.venv/bin/python scripts/analyze_past_drafts.py 2023 2024 2025 --team "BK Whoppers"

# Interactive player value lookup (shows util_value for Util-only players)
.venv/bin/python scripts/lookup_player.py

# Monte Carlo draft simulation (evaluates model values vs Yahoo-anchored competitors)
.venv/bin/python scripts/simulate_draft.py --seed 42 -n 50
.venv/bin/python scripts/simulate_draft.py --seed 42 -n 50 -v  # verbose per-sim rosters
```

## Architecture

### Valuation Pipeline

```
FanGraphs ATC CSVs
  → data/fangraphs.py (parse stats, warn if no position column)
  → data/yahoo_positions.py (fetch Yahoo eligibility, fuzzy-match → merge)
  → valuation/points.py (project fantasy points from stats)
  → valuation/replacement.py (projected-draft replacement levels)
  → valuation/auction.py (VAR → proportional dollars → integer rounding via largest-remainder)
  → CSV output
```

Yahoo position eligibility is **required** — FanGraphs ATC CSVs have no position column, so without Yahoo data all hitters default to Util and valuations are wildly inaccurate. A validation guard in `replacement.py` raises `ValueError` if >50% of hitters are Util-only.

All pitchers share a single P pool (no SP/RP split). Position scarcity is driven by projected-draft replacement levels: a realistic drafted pool is built respecting all roster constraints (position slots, Util, bench), then each position's replacement level is the minimum points among drafted players eligible at that position. Multi-position players are assigned to their scarcest position for pool construction but count toward all positions for replacement level calculation.
Players like Ohtani appear as two separate entries (hitter + pitcher) — this is intentional, matching how the Yahoo league treats them.
Dual-entry names are disambiguated with "(Batter)"/"(Pitcher)" suffixes by `valuation/names.py`, matching Yahoo's convention. The draft tracker keys on name, so unique names are required.
Dollar values are rounded to whole integers (largest-remainder method) to match auction bidding rules while preserving exact budget totals.

#### Key valuation columns
- `var`: value above replacement — player's points minus replacement level at their scarcest eligible position
- `allocation_var`: equals `var` (kept for draft tracker compatibility)
- `dollar_value`: auction price (accounts for positional scarcity via projected-draft replacement levels)
- `util_value`: position-blind auction price (useful during draft when evaluating a hitter for Util-only slot)

### Draft Tracker

- **State** (`draft/state.py`): Pydantic models — `DraftState`, `PlayerValue`, `TeamState`, `DraftPick`. Auto-saves to `draft_state.json`. Snapshot-based undo (last 50 in memory).
- **Revaluation** (`draft/tracker.py`): Recalculates auction values on remaining player pool after each pick using the same VAR method.
- **API** (`draft/api.py`): FastAPI routes (`/api/players`, `/api/draft`, `/api/undo`, `/api/state`, `/api/team/{team_id}`).
- **Frontend**: `templates/draft.html` + `static/draft.js` + `static/style.css`.

### Draft History Analysis

- `analysis/draft_history.py`: Position spend summaries, hitter/pitcher splits, standings correlation, price drop-off curves, overpay recommendations.
- `scripts/analyze_past_drafts.py`: CLI that fetches draft results + standings from Yahoo across multiple seasons and prints a full report. Supports `--team` for personalized report, `--output` for CSV export.

### Draft Simulation

- `simulation/engine.py`: Monte Carlo auction draft simulator. User team bids at exact model values; competitor teams bid at Yahoo league values with Gaussian noise. True ascending auction mechanic: winner pays second-highest bid + $1.
- `scripts/simulate_draft.py`: CLI with `--seed`, `-n`, `--noise`, `-v` options. Reports points advantage, rank distribution, win/top-4 rates, budget utilization.
- Key design: round-robin nomination (each team nominates their most-wanted player), scarcest-first slot assignment, filler players for unfilled roster spots.

### Yahoo Integration

- **Auth** (`yahoo/auth.py`): OAuth2 with token persistence in `oauth2.json`.
- **Matching** (`yahoo/league_client.py`): Two-pass fuzzy matching (rapidfuzz) to handle NA-status players and dual-eligible players like Ohtani.

### Configuration

- `config/scoring.py`: Frozen dataclasses for batting/pitching scoring weights. Module-level instances (`BATTING_SCORING`, `PITCHING_SCORING`).
- `config/league.py`: `LeagueSettings` dataclass (teams, budget, roster size, `bench_hitters` default=1 calibrated from draft history). Module-level `LEAGUE` instance.
- `config/positions.py`: `Position` enum with `FANGRAPHS_POSITION_MAP` for normalizing position strings.
- `valuation/names.py`: Disambiguates dual-entry players (e.g. Ohtani) by appending "(Batter)"/"(Pitcher)" suffixes.

## Code Conventions

- Python 3.9 baseline. Most modules use `from __future__ import annotations` for type hints.
- **Exception**: `draft/state.py` uses `typing.Dict`/`typing.List` instead of `__future__` annotations because Pydantic needs runtime type resolution.
- **Exception**: Click-decorated functions cannot use `from __future__ import annotations` (Click inspects signatures at runtime). Use `typing.Optional` instead of `X | None` in Click command signatures.
- Scripts add project root to `sys.path` for absolute imports across packages.
- Config objects use `@dataclass(frozen=True)` for immutability.
- All functions, classes, and methods must have docstrings.

## Yahoo Fantasy API Notes

- `league.league_ids(year=N)` takes a single int year, not a list.
- `league.draft_results()` returns `player_id` (int), not `player_key`.
- `league.player_details(id)` accepts int IDs and supports batch via list: `player_details([id1, id2])`.
- `eligible_positions` in player details is `[{"position": "OF"}, ...]` — extract with `p["position"]`.
- Yahoo returns pitcher positions as `"SP"`, `"RP"`, `"SP,RP"` — never just `"P"`. Use `_is_pitcher_only()` from `data/yahoo_positions.py` to check, not `== "P"`.
- `league.standings()` returns teams in rank order; each entry has `team_key`, `name`, `rank`.

## Environment Variables

Set in `.env` (not committed):
- `YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`
- `YAHOO_LEAGUE_ID`, `YAHOO_GAME_KEY`

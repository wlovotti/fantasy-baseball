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

# Generate auction values from FanGraphs CSVs
.venv/bin/python scripts/generate_values.py projections/hitters.csv projections/pitchers.csv

# Generate Yahoo-enhanced values (merges Yahoo position eligibility)
.venv/bin/python scripts/generate_values_yahoo.py projections/hitters.csv projections/pitchers.csv

# Upload values to Yahoo
.venv/bin/python scripts/upload_to_yahoo.py player_values.csv

# Run live draft tracker (FastAPI app on localhost:8000)
.venv/bin/python scripts/run_draft.py player_values.csv
.venv/bin/python scripts/run_draft.py player_values.csv --resume draft_state.json
```

## Architecture

### Valuation Pipeline

```
FanGraphs ATC CSVs
  → data/fangraphs.py (parse, normalize positions via Position enum)
  → valuation/points.py (project fantasy points from stats)
  → valuation/replacement.py (greedy position assignment → replacement levels)
  → valuation/auction.py (value above replacement → proportional dollar values)
  → CSV output
```

All pitchers share a single P pool (no SP/RP split). Bench slots are allocated proportionally between hitters and pitchers. Position scarcity is driven by greedy assignment.

### Draft Tracker

- **State** (`draft/state.py`): Pydantic models — `DraftState`, `PlayerValue`, `TeamState`, `DraftPick`. Auto-saves to `draft_state.json`. Snapshot-based undo (last 50 in memory).
- **Revaluation** (`draft/tracker.py`): Recalculates auction values on remaining player pool after each pick using the same VAR method.
- **API** (`draft/api.py`): FastAPI routes (`/api/players`, `/api/draft`, `/api/undo`, `/api/state`, `/api/team/{team_id}`).
- **Frontend**: `templates/draft.html` + `static/draft.js` + `static/style.css`.

### Yahoo Integration

- **Auth** (`yahoo/auth.py`): OAuth2 with token persistence in `oauth2.json`.
- **Matching** (`yahoo/league_client.py`): Two-pass fuzzy matching (rapidfuzz) to handle NA-status players and dual-eligible players like Ohtani.
- **Upload** (`yahoo/upload.py`): Pushes dollar values to Yahoo pre-draft interface.

### Configuration

- `config/scoring.py`: Frozen dataclasses for batting/pitching scoring weights. Module-level instances (`BATTING_SCORING`, `PITCHING_SCORING`).
- `config/league.py`: `LeagueSettings` dataclass (teams, budget, roster size). Module-level `LEAGUE` instance.
- `config/positions.py`: `Position` enum with `FANGRAPHS_POSITION_MAP` for normalizing position strings.

## Code Conventions

- Python 3.9 baseline. Most modules use `from __future__ import annotations` for type hints.
- **Exception**: `draft/state.py` and `config/` use `typing.Dict`/`typing.List` instead of `__future__` annotations because Pydantic needs runtime type resolution.
- Scripts add project root to `sys.path` for absolute imports across packages.
- Config objects use `@dataclass(frozen=True)` for immutability.
- All functions, classes, and methods must have docstrings.

## Environment Variables

Set in `.env` (not committed):
- `YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`
- `YAHOO_LEAGUE_ID`, `YAHOO_GAME_KEY`

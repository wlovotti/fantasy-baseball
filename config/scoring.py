"""Batting and pitching scoring rules — single source of truth for the league."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BattingScoring:
    """Point values for batting categories."""

    single: float = 1.0
    double: float = 2.0
    triple: float = 3.0
    home_run: float = 4.0
    run: float = 2.0
    rbi: float = 2.0
    walk: float = 1.0
    hbp: float = 1.0
    stolen_base: float = 2.5
    caught_stealing: float = -1.0
    strikeout: float = -1.0
    gidp: float = -2.0
    # Bonus events (not projected — included for completeness)
    cycle: float = 20.0
    grand_slam: float = 8.0


@dataclass(frozen=True)
class PitchingScoring:
    """Point values for pitching categories."""

    inning_pitched: float = 1.0
    win: float = 4.5
    loss: float = -2.0
    save: float = 7.0
    hold: float = 5.5
    earned_run: float = -1.0
    strikeout: float = 1.2
    hit_allowed: float = -0.25
    walk_allowed: float = -0.35
    quality_start: float = 5.0
    complete_game: float = 7.0
    shutout: float = 10.0
    blown_save: float = -2.0
    # Bonus events (not projected)
    no_hitter: float = 20.0
    perfect_game: float = 35.0


# Default instances
BATTING_SCORING = BattingScoring()
PITCHING_SCORING = PitchingScoring()

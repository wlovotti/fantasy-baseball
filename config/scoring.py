"""Batting and pitching scoring rules — single source of truth for the league."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BattingScoring:
    """Point values for batting categories."""

    single: float = 2.5
    double: float = 5.0
    triple: float = 7.5
    home_run: float = 10.0
    run: float = 2.0
    rbi: float = 2.0
    walk: float = 2.5
    hbp: float = 2.5
    stolen_base: float = 5.0
    caught_stealing: float = -2.5
    strikeout: float = -1.0
    # Bonus events (not projected — included for completeness)
    cycle: float = 25.0
    grand_slam: float = 10.0


@dataclass(frozen=True)
class PitchingScoring:
    """Point values for pitching categories."""

    inning_pitched: float = 3.0
    win: float = 4.5
    loss: float = -4.5
    save: float = 7.0
    hold: float = 5.5
    earned_run: float = -2.0
    strikeout: float = 1.5
    hit_allowed: float = -1.0
    walk_allowed: float = -1.0
    hbp_allowed: float = -1.0
    quality_start: float = 3.0
    complete_game: float = 5.0
    shutout: float = 5.0
    blown_save: float = -2.0
    # Bonus events (not projected)
    no_hitter: float = 25.0
    perfect_game: float = 50.0


# Default instances
BATTING_SCORING = BattingScoring()
PITCHING_SCORING = PitchingScoring()

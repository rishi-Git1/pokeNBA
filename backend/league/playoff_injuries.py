"""Backwards-compatible re-exports — prefer ``backend.league.injuries``."""
from backend.league.injuries import (  # noqa: F401
    BASE_INJURY_CHANCE,
    INJURY_STACK_PER_PRIOR,
    InjuryReport,
    PlayoffInjuryReport,
    advance_injury_clocks,
    injury_probability,
    merge_reports,
    prepare_team_roster,
)

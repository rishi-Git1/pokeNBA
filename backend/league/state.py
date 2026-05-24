"""League singleton accessor.

Every read/write of the league phase, dynamic cap, current season, or
champion goes through here so we have a single source of truth.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.models import LeagueState, Phase


def get_state(db: Session) -> LeagueState:
    """Fetch the singleton league state, creating it lazily if missing.

    Lazy-create makes life easier when the user resets to an old DB schema or
    spins up a brand new SQLite file: callers can just ``get_state(db)`` and
    trust that a row exists.
    """
    state = db.get(LeagueState, 1)
    if state is None:
        state = LeagueState(
            id=1,
            current_season=1,
            phase=Phase.REGULAR_SEASON,
            bst_cap=settings.bst_cap,
            champion_team_id=None,
            last_champion_season=None,
            draft_current_pick=0,
            draft_total_picks=0,
        )
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def reset_state(db: Session) -> LeagueState:
    """Used by the seed script to (re)initialize the league row."""
    state = db.get(LeagueState, 1)
    if state is None:
        state = LeagueState(id=1)
        db.add(state)
    state.current_season = 1
    state.phase = Phase.REGULAR_SEASON
    state.bst_cap = settings.bst_cap
    state.champion_team_id = None
    state.last_champion_season = None
    state.draft_current_pick = 0
    state.draft_total_picks = 0
    db.commit()
    db.refresh(state)
    return state

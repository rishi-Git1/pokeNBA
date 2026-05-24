"""Phase transitions for the league state machine.

```
REGULAR_SEASON
    | (last regular-season game played)
    v
PLAYOFFS  ──── (champion crowned) ────►  end_of_season → cap inflation
    |                                     |
    +─────────────────────────────────────+
                                          |
                                          v
                                       DRAFT
                                          |  (last pick made)
                                          v
                                     PRE_SEASON
                                          |  ("Start Next Season" click)
                                          v
                                  REGULAR_SEASON  (season + 1)
```

Every transition is idempotent — calling it twice is a no-op so a flaky UI
click can't double-trigger a stage.
"""
from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.league.aging import end_of_season, reset_team_records
from backend.league.state import get_state
from backend.models import Game, LeagueState, Phase, Series
from backend.sim.schedule import generate_schedule


# Cap-inflation knobs
CAP_INFLATION_MIN: float = 0.05
CAP_INFLATION_MAX: float = 0.12


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _regular_season_done(db: Session, season: int) -> bool:
    remaining = db.scalar(
        select(Game.id)
        .where(
            Game.season == season,
            Game.is_completed.is_(False),
            Game.is_playoff.is_(False),
        )
        .limit(1)
    )
    return remaining is None


def _finals_complete(db: Session, season: int) -> bool:
    finals = db.scalars(
        select(Series).where(
            Series.season == season,
            Series.bracket == "Finals",
            Series.round == 4,
        )
    ).first()
    return finals is not None and bool(finals.is_completed)


def _all_picks_made(state: LeagueState) -> bool:
    return state.draft_total_picks > 0 and state.draft_current_pick >= state.draft_total_picks


# ----------------------------------------------------------------------------
# Public transitions
# ----------------------------------------------------------------------------
def maybe_advance_phase(db: Session) -> dict | None:
    """Inspect the current phase + reality and bump to the next phase if appropriate.

    Called after any sim/pick action. Returns a small dict if a transition
    actually happened (frontend uses this to refresh aggressively), or
    ``None`` if nothing changed.
    """
    state = get_state(db)

    if state.phase == Phase.REGULAR_SEASON and _regular_season_done(db, state.current_season):
        from backend.league.playoffs import start_playoffs
        start_playoffs(db, state.current_season)
        state = get_state(db)
        state.phase = Phase.PLAYOFFS
        db.commit()
        return {"transition": "regular_season -> playoffs", "season": state.current_season}

    if state.phase == Phase.PLAYOFFS and _finals_complete(db, state.current_season):
        finalize_playoffs(db)
        return {"transition": "playoffs -> draft", "season": state.current_season}

    if state.phase == Phase.DRAFT and _all_picks_made(state):
        state.phase = Phase.PRE_SEASON
        db.commit()
        return {"transition": "draft -> pre_season", "season": state.current_season}

    return None


def finalize_playoffs(db: Session, *, rng: random.Random | None = None) -> None:
    """Champion is crowned. Run aging, inflate cap, prepare draft order."""
    rng = rng or random.Random()
    state = get_state(db)
    if state.phase != Phase.PLAYOFFS:
        return  # idempotent

    season = state.current_season
    finals = db.scalars(
        select(Series).where(Series.season == season, Series.bracket == "Finals")
    ).first()
    if finals is None or not finals.is_completed:
        return

    state.champion_team_id = finals.winner_team_id
    state.last_champion_season = season

    # 1) age + retire + spawn regens + mint next-year picks
    end_of_season(db, season=season, rng=rng)

    # 2) cap inflation 5–12%
    inflation = rng.uniform(CAP_INFLATION_MIN, CAP_INFLATION_MAX)
    state.bst_cap = int(round(state.bst_cap * (1 + inflation)))

    # 3) initialize draft (worst -> best, coin-flip ties)
    from backend.league.draft import initialize_draft_order
    initialize_draft_order(db, season=season, rng=rng)

    state = get_state(db)
    state.phase = Phase.DRAFT
    db.commit()


def start_next_season(db: Session, *, rng: random.Random | None = None) -> dict:
    """Player clicked "Start Next Season" — generate schedule, increment season."""
    rng = rng or random.Random()
    state = get_state(db)
    if state.phase != Phase.PRE_SEASON:
        raise ValueError(f"Can't start next season from phase {state.phase.value!r}")

    next_season = state.current_season + 1
    reset_team_records(db)
    n_games = generate_schedule(db, season=next_season, rng=rng)

    state.current_season = next_season
    state.phase = Phase.REGULAR_SEASON
    state.draft_current_pick = 0
    state.draft_total_picks = 0
    db.commit()

    return {
        "season": next_season,
        "games_generated": n_games,
        "phase": state.phase.value,
        "bst_cap": state.bst_cap,
    }

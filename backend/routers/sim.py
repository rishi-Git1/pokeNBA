"""Simulation control endpoints.

POST endpoints mutate league state; GET endpoints read schedule + box scores.
"""
from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.league.cpu_gm import run_cpu_gm_moves
from backend.league.gm_mode import TEAM_GM
from backend.league.lifecycle import maybe_advance_phase
from backend.league.state import get_state
from backend.models import BoxScore, Game, Phase
from backend.schemas import BoxScoreOut, DayResultOut, GameOut
from backend.sim.league_day import sim_day, sim_until_done
from backend.sim.schedule import generate_schedule

router = APIRouter(prefix="/api/sim", tags=["sim"])


# ----------------------------------------------------------------------------
# Schedule
# ----------------------------------------------------------------------------
@router.post("/schedule", response_model=dict)
def post_schedule(season: int = 1, db: Session = Depends(get_db)) -> dict:
    """(Re)generate the schedule for ``season``. Wipes existing games first."""
    n = generate_schedule(db, season=season)
    return {"season": season, "games_generated": n}


@router.get("/schedule", response_model=list[GameOut])
def get_schedule(
    season: int | None = None,
    db: Session = Depends(get_db),
    completed: bool | None = Query(None, description="Filter by completion status"),
    team_id: int | None = None,
    limit: int = Query(200, ge=1, le=2000),
) -> list[Game]:
    target_season = season if season is not None else get_state(db).current_season
    stmt = select(Game).where(Game.season == target_season, Game.is_playoff.is_(False))
    if completed is not None:
        stmt = stmt.where(Game.is_completed.is_(completed))
    if team_id is not None:
        stmt = stmt.where((Game.home_team_id == team_id) | (Game.away_team_id == team_id))
    stmt = stmt.order_by(Game.game_date, Game.id).limit(limit)
    return list(db.scalars(stmt))


# ----------------------------------------------------------------------------
# Advance time
# ----------------------------------------------------------------------------
@router.post("/day")
def post_sim_day(
    season: int | None = None,
    seed: int | None = None,
    game_mode: str = Query("league_gm", description="league_gm or team_gm"),
    user_team_id: int | None = Query(None, description="Human-controlled team in team_gm mode"),
    db: Session = Depends(get_db),
) -> dict:
    """Sim one game day of the regular season for the current league season.

    When the regular season finishes on this call we auto-transition the
    league to PLAYOFFS and surface that in the response so the frontend can
    refresh aggressively.
    """
    state = get_state(db)
    if state.phase != Phase.REGULAR_SEASON:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot sim a regular-season day from phase {state.phase.value!r}.",
        )
    target_season = season if season is not None else state.current_season
    rng = random.Random(seed) if seed is not None else random.Random()
    result = sim_day(db, season=target_season, rng=rng)
    if result is None:
        # Regular season is exhausted — transition to playoffs.
        transition = maybe_advance_phase(db)
        return {"games_played": 0, "transition": transition}

    games = list(
        db.scalars(
            select(Game).where(Game.season == target_season, Game.game_date == result.sim_date)
        )
    )
    cpu_moves: list[dict] = []
    if game_mode == TEAM_GM:
        if user_team_id is None:
            raise HTTPException(
                status_code=400,
                detail="Team GM mode requires user_team_id when simming days.",
            )
        cpu_moves = run_cpu_gm_moves(db, user_team_id=user_team_id, rng=rng)
        for move in cpu_moves:
            move["sim_date"] = str(result.sim_date)

    transition = maybe_advance_phase(db)
    return {
        "sim_date": str(result.sim_date),
        "season": result.season,
        "games_played": result.games_played,
        "box_scores_written": result.box_scores_written,
        "games": [GameOut.model_validate(g).model_dump(mode="json") for g in games],
        "injury_report": result.injury_report,
        "cpu_moves": cpu_moves,
        "transition": transition,
    }


@router.post("/season", response_model=dict)
def post_sim_season(
    season: int | None = None,
    seed: int | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Sim the rest of the regular season. Returns aggregate counts.

    Stops at the playoff boundary — does NOT run playoffs.
    """
    state = get_state(db)
    if state.phase != Phase.REGULAR_SEASON:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot sim regular season from phase {state.phase.value!r}.",
        )
    target_season = season if season is not None else state.current_season
    rng = random.Random(seed) if seed is not None else random.Random()
    days = sim_until_done(db, season=target_season, rng=rng)
    transition = maybe_advance_phase(db)
    return {
        "season": target_season,
        "days_played": len(days),
        "games_played": sum(d.games_played for d in days),
        "transition": transition,
    }


# ----------------------------------------------------------------------------
# Box scores
# ----------------------------------------------------------------------------
@router.get("/games/{game_id}/box", response_model=list[BoxScoreOut])
def get_box_score(game_id: int, db: Session = Depends(get_db)) -> list[BoxScore]:
    rows = list(
        db.scalars(
            select(BoxScore).where(BoxScore.game_id == game_id).order_by(BoxScore.team_id, BoxScore.points.desc())
        )
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No box score found for that game.")
    return rows


@router.get("/recent-results", response_model=list[GameOut])
def get_recent_results(
    season: int | None = None,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[Game]:
    target_season = season if season is not None else get_state(db).current_season
    return list(
        db.scalars(
            select(Game)
            .where(
                Game.season == target_season,
                Game.is_completed.is_(True),
                Game.is_playoff.is_(False),
            )
            .order_by(desc(Game.game_date), desc(Game.id))
            .limit(limit)
        )
    )


@router.get("/upcoming-games", response_model=list[GameOut])
def get_upcoming_games(
    season: int | None = None,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[Game]:
    target_season = season if season is not None else get_state(db).current_season
    return list(
        db.scalars(
            select(Game)
            .where(
                Game.season == target_season,
                Game.is_completed.is_(False),
                Game.is_playoff.is_(False),
            )
            .order_by(Game.game_date, Game.id)
            .limit(limit)
        )
    )

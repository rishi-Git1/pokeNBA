"""Playoff endpoints: bracket view, sim one game, sim one round."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.league.lifecycle import maybe_advance_phase
from backend.league.playoffs import (
    get_bracket,
    sim_next_playoff_game,
    sim_next_playoff_round,
    sim_round_slate,
)
from backend.league.state import get_state
from backend.models import Phase

router = APIRouter(prefix="/api/playoffs", tags=["playoffs"])


@router.get("/bracket")
def bracket(season: int | None = None, db: Session = Depends(get_db)) -> dict:
    state = get_state(db)
    return get_bracket(db, season or state.current_season)


@router.post("/game")
def post_game(db: Session = Depends(get_db)) -> dict:
    state = get_state(db)
    if state.phase != Phase.PLAYOFFS:
        raise HTTPException(status_code=400, detail=f"Not in playoffs (phase={state.phase.value}).")
    try:
        result = sim_next_playoff_game(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    transition = maybe_advance_phase(db)
    return {"result": result, "transition": transition}


@router.post("/round")
def post_round(db: Session = Depends(get_db)) -> dict:
    state = get_state(db)
    if state.phase != Phase.PLAYOFFS:
        raise HTTPException(status_code=400, detail=f"Not in playoffs (phase={state.phase.value}).")
    summary = sim_next_playoff_round(db)
    transition = maybe_advance_phase(db)
    return {"summary": summary, "transition": transition}


@router.post("/slate")
def post_slate(db: Session = Depends(get_db)) -> dict:
    """Sim the next game number across every active series in the current round."""
    state = get_state(db)
    if state.phase != Phase.PLAYOFFS:
        raise HTTPException(status_code=400, detail=f"Not in playoffs (phase={state.phase.value}).")
    try:
        summary = sim_round_slate(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    transition = maybe_advance_phase(db)
    return {"summary": summary, "transition": transition}

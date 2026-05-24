"""Draft room endpoints: state, manual pick, auto-pick, sim-rest."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.league.draft import (
    DraftError,
    auto_pick,
    get_draft_state,
    make_pick,
    sim_rest_of_draft,
)
from backend.league.lifecycle import maybe_advance_phase
from backend.league.state import get_state
from backend.models import Phase

router = APIRouter(prefix="/api/draft", tags=["draft"])


def _require_draft_phase(db: Session) -> None:
    state = get_state(db)
    if state.phase != Phase.DRAFT:
        raise HTTPException(status_code=400, detail=f"Not in draft (phase={state.phase.value}).")


@router.get("/state")
def state(db: Session = Depends(get_db)) -> dict:
    return get_draft_state(db)


@router.post("/pick")
def pick(player_id: int = Body(..., embed=True), db: Session = Depends(get_db)) -> dict:
    _require_draft_phase(db)
    try:
        result = make_pick(db, player_id=player_id)
    except DraftError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    transition = maybe_advance_phase(db)
    return {"pick": result, "transition": transition}


@router.post("/auto-pick")
def post_auto(db: Session = Depends(get_db)) -> dict:
    _require_draft_phase(db)
    try:
        result = auto_pick(db)
    except DraftError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    transition = maybe_advance_phase(db)
    return {"pick": result, "transition": transition}


@router.post("/sim-rest")
def post_sim_rest(db: Session = Depends(get_db)) -> dict:
    _require_draft_phase(db)
    summary = sim_rest_of_draft(db)
    transition = maybe_advance_phase(db)
    return {"summary": summary, "transition": transition}

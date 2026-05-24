"""Trade + free-agent endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.league.projections import project_after_release, project_after_sign
from backend.league.transactions import (
    TradeProposal,
    TransactionError,
    execute_trade,
    release_player,
    sign_free_agent,
)
from backend.schemas import PlayerOut

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


class TradeRequest(BaseModel):
    team_a_id: int
    team_b_id: int
    team_a_player_ids: list[int] = Field(default_factory=list)
    team_b_player_ids: list[int] = Field(default_factory=list)
    team_a_pick_ids: list[int] = Field(default_factory=list)
    team_b_pick_ids: list[int] = Field(default_factory=list)


@router.post("/trade")
def post_trade(payload: TradeRequest, db: Session = Depends(get_db)) -> dict:
    try:
        report = execute_trade(
            db,
            TradeProposal(
                team_a_id=payload.team_a_id,
                team_b_id=payload.team_b_id,
                team_a_player_ids=payload.team_a_player_ids,
                team_b_player_ids=payload.team_b_player_ids,
                team_a_pick_ids=payload.team_a_pick_ids,
                team_b_pick_ids=payload.team_b_pick_ids,
            ),
        )
    except TransactionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "ok": True,
        "team_a": {
            "id": report.team_a_id,
            "bst_before": report.team_a_bst_before,
            "bst_after": report.team_a_bst_after,
        },
        "team_b": {
            "id": report.team_b_id,
            "bst_before": report.team_b_bst_before,
            "bst_after": report.team_b_bst_after,
        },
        "players_moved": report.players_moved,
        "picks_moved": report.picks_moved,
    }


@router.post("/sign", response_model=PlayerOut)
def post_sign(team_id: int, player_id: int, db: Session = Depends(get_db)):
    try:
        return sign_free_agent(db, team_id=team_id, player_id=player_id)
    except TransactionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/release", response_model=PlayerOut)
def post_release(team_id: int, player_id: int, db: Session = Depends(get_db)):
    try:
        return release_player(db, team_id=team_id, player_id=player_id)
    except TransactionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/projection/release")
def get_release_projection(team_id: int, player_id: int, db: Session = Depends(get_db)) -> dict:
    """Preview what cutting this player would do to the team's projected wins."""
    try:
        return project_after_release(db, team_id=team_id, player_id=player_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/projection/sign")
def get_sign_projection(team_id: int, player_id: int, db: Session = Depends(get_db)) -> dict:
    """Preview what signing this free agent would do to the team's projected wins."""
    try:
        return project_after_sign(db, team_id=team_id, player_id=player_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

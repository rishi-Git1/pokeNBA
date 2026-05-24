"""Team endpoints: list, detail (with roster + cap)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.database import get_db
from backend.league.state import get_state
from backend.models import Player, Team
from backend.schemas import PlayerSummary, TeamOut, TeamSummary

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("", response_model=list[TeamSummary])
def list_teams(db: Session = Depends(get_db)) -> list[Team]:
    return list(db.scalars(select(Team).order_by(Team.conference, Team.division, Team.name)))


@router.get("/{team_id}", response_model=TeamOut)
def get_team(team_id: int, db: Session = Depends(get_db)) -> dict:
    team = db.scalars(
        select(Team).where(Team.id == team_id).options(selectinload(Team.players))
    ).first()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    roster = [p for p in team.players if not p.is_retired]
    bst_used = sum(p.effective_bst for p in roster)
    state = get_state(db)

    return {
        "id": team.id,
        "name": team.name,
        "abbreviation": team.abbreviation,
        "city": team.city,
        "conference": team.conference,
        "division": team.division,
        "wins": team.wins,
        "losses": team.losses,
        "bst_cap": state.bst_cap,
        "bst_used": bst_used,
        "roster": [PlayerSummary.model_validate(p) for p in roster],
    }

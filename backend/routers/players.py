"""Player endpoints: paginated list, single detail."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Player
from backend.schemas import PlayerOut, PlayerSummary

router = APIRouter(prefix="/api/players", tags=["players"])


@router.get("", response_model=list[PlayerSummary])
def list_players(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    badge: str | None = None,
    team_id: int | None = None,
    free_agents_only: bool = False,
    include_retired: bool = False,
) -> list[Player]:
    stmt = select(Player)
    if not include_retired:
        stmt = stmt.where(Player.is_retired.is_(False))
    if badge:
        stmt = stmt.where(Player.badge == badge)
    if team_id is not None:
        stmt = stmt.where(Player.team_id == team_id)
    if free_agents_only:
        stmt = stmt.where(Player.team_id.is_(None))
    stmt = stmt.order_by(Player.bst.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


@router.get("/{player_id}", response_model=PlayerOut)
def get_player(player_id: int, db: Session = Depends(get_db)) -> Player:
    player = db.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return player

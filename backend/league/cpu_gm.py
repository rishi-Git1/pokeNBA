"""CPU general-manager roster moves for Team GM mode.

After each regular-season day, every AI-controlled team has a small chance to
drop its worst player and sign the best available free agent that fits under
the cap. Teams are processed worst-to-first in the standings so struggling
clubs get the first crack at talent.
"""
from __future__ import annotations

import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.league.injuries import fa_signable_clause, handle_player_release
from backend.league.state import get_state
from backend.league.transactions import (
    ROSTER_MIN_AFTER_TRADE,
    TRADE_CAP_LEEWAY,
    _bst_total,
    _team_roster,
)
from backend.models import Player, Team


def _teams_worst_first(db: Session) -> list[Team]:
    teams = list(db.scalars(select(Team)))
    teams.sort(key=lambda t: (t.wins, -t.losses, t.id))
    return teams


def _best_affordable_fa(db: Session, *, cap_room: int, season: int) -> Player | None:
    fas = list(
        db.scalars(
            select(Player)
            .where(
                Player.team_id.is_(None),
                Player.is_retired.is_(False),
                fa_signable_clause(season),
            )
            .order_by(Player.bst.desc(), Player.id.asc())
        )
    )
    for fa in fas:
        if fa.effective_bst <= cap_room:
            return fa
    return None


def _try_waiver_move(db: Session, team: Team) -> dict[str, Any] | None:
    """Drop the roster's lowest-BST player and sign the best fitting FA."""
    roster = _team_roster(db, team.id)
    if len(roster) <= ROSTER_MIN_AFTER_TRADE:
        return None

    worst = min(roster, key=lambda p: (p.bst, p.id))
    roster_after = [p for p in roster if p.id != worst.id]
    state = get_state(db)
    cap_ceiling = state.bst_cap + TRADE_CAP_LEEWAY
    cap_room = cap_ceiling - _bst_total(roster_after)

    fa = _best_affordable_fa(db, cap_room=cap_room, season=state.current_season)
    if fa is None:
        return None

    handle_player_release(db, player=worst, season=state.current_season)
    worst.team_id = None
    fa.team_id = team.id
    db.flush()

    return {
        "team_id": team.id,
        "team_abbr": team.abbreviation,
        "team_name": f"{team.city} {team.name}",
        "released": {"id": worst.id, "name": worst.name, "bst": worst.bst},
        "signed": {"id": fa.id, "name": fa.name, "bst": fa.bst},
    }


def run_cpu_gm_moves(
    db: Session,
    *,
    user_team_id: int | None,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """Run daily AI waiver-wire activity for all teams except the human's."""
    rng = rng or random.Random()
    moves: list[dict[str, Any]] = []

    for team in _teams_worst_first(db):
        if user_team_id is not None and team.id == user_team_id:
            continue
        if rng.random() >= settings.cpu_gm_move_chance:
            continue
        move = _try_waiver_move(db, team)
        if move is not None:
            moves.append(move)

    if moves:
        db.commit()
    return moves

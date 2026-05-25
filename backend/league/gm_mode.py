"""Helpers for League GM vs Team GM authorization."""
from __future__ import annotations

from fastapi import HTTPException

LEAGUE_GM = "league_gm"
TEAM_GM = "team_gm"


def assert_can_manage_team(
    *,
    team_id: int,
    game_mode: str | None,
    user_team_id: int | None,
) -> None:
    """Reject transaction requests that target a team the user doesn't control."""
    if game_mode != TEAM_GM:
        return
    if user_team_id is None:
        raise HTTPException(
            status_code=400,
            detail="Team GM mode requires a user team (pick your franchise first).",
        )
    if team_id != user_team_id:
        raise HTTPException(
            status_code=403,
            detail="In Team GM mode you can only manage your own team.",
        )

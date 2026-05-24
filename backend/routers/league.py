"""League-level endpoints: standings, free agents, badge directory, end-of-season."""
from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.badges import all_badges
from backend.core.config import settings
from backend.database import get_db
from backend.league.aging import end_of_season, reset_team_records
from backend.league.lifecycle import start_next_season as lifecycle_start_next_season
from backend.league.state import get_state
from backend.league.transactions import (
    ROSTER_MAX_AFTER_TRADE,
    ROSTER_MIN_AFTER_TRADE,
    TRADE_CAP_LEEWAY,
)
from backend.models import BoxScore, Phase, Player, Series, Team
from backend.schemas import PlayerSummary, StandingsRow
from backend.sim.schedule import generate_schedule

router = APIRouter(prefix="/api/league", tags=["league"])


@router.get("/standings", response_model=list[StandingsRow])
def standings(db: Session = Depends(get_db)) -> list[Team]:
    return list(
        db.scalars(
            select(Team).order_by(Team.conference, Team.wins.desc(), Team.losses.asc())
        )
    )


@router.get("/free-agents", response_model=list[PlayerSummary])
def free_agents(db: Session = Depends(get_db), limit: int = 100) -> list[Player]:
    stmt = (
        select(Player)
        .where(Player.team_id.is_(None), Player.is_retired.is_(False))
        .order_by(Player.bst.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


@router.get("/badges")
def badges() -> dict:
    """Static reference: all badges + their effect modifiers."""
    return all_badges()


@router.get("/cap-config")
def cap_config(db: Session = Depends(get_db)) -> dict:
    """Cap rule numbers a frontend needs to render meters and validate inputs."""
    state = get_state(db)
    return {
        "bst_cap": state.bst_cap,
        "base_bst_cap": settings.bst_cap,
        "trade_cap_leeway": TRADE_CAP_LEEWAY,
        "max_total_with_leeway": state.bst_cap + TRADE_CAP_LEEWAY,
        "roster_size_target": settings.roster_size,
        "roster_max_after_trade": ROSTER_MAX_AFTER_TRADE,
        "roster_min_after_trade": ROSTER_MIN_AFTER_TRADE,
        "season_games": settings.season_games,
    }


_LEADER_STATS = {
    "points", "rebounds", "assists", "steals", "blocks",
    "fg_made", "three_made", "minutes",
}


@router.get("/leaders")
def leaders(
    season: int | None = None,
    stat: str = Query("points", description=f"One of: {sorted(_LEADER_STATS)}"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[dict]:
    if stat not in _LEADER_STATS:
        raise HTTPException(status_code=400, detail=f"Unknown stat. Use one of {sorted(_LEADER_STATS)}.")

    target_season = season if season is not None else get_state(db).current_season
    col = getattr(BoxScore, stat)
    rows = db.execute(
        select(
            BoxScore.player_id,
            func.sum(col).label("total"),
            func.count(BoxScore.id).label("games"),
            func.sum(BoxScore.minutes).label("minutes"),
            func.sum(BoxScore.points).label("points_total"),
        )
        .where(BoxScore.season == target_season)
        .group_by(BoxScore.player_id)
        .order_by(func.sum(col).desc())
        .limit(limit)
    ).all()

    out = []
    for player_id, total, games, minutes, points_total in rows:
        p = db.get(Player, player_id)
        if p is None:
            continue
        out.append({
            "player_id": p.id,
            "name": p.name,
            "species": p.species,
            "team_id": p.team_id,
            "sprite_url": p.sprite_url,
            "position": p.position.value,
            "badge": p.badge,
            "games": games,
            "total": int(total or 0),
            "per_game": round((total or 0) / max(1, games), 1),
            "minutes_per_game": round((minutes or 0) / max(1, games), 1),
            "points_per_game": round((points_total or 0) / max(1, games), 1),
        })
    return out


@router.post("/end-season")
def post_end_season(season: int = 1, seed: int | None = None, db: Session = Depends(get_db)) -> dict:
    """Run aging, retire vets, generate same-species regens, mint next-year picks."""
    rng = random.Random(seed) if seed is not None else None
    report = end_of_season(db, season=season, rng=rng)
    return {
        "season": report.season,
        "next_season": report.next_season,
        "aged_players": report.aged_players,
        "retired_players": report.retired_players,
        "regens_generated": report.regens_generated,
        "new_picks_generated": report.new_picks_generated,
    }


@router.post("/advance-season")
def post_advance_season(season: int = 1, db: Session = Depends(get_db)) -> dict:
    """Reset W/L counters and generate a fresh schedule for ``season + 1``.

    Call **after** ``/end-season`` so the new schedule is built against the
    aged-and-regenned roster state.
    """
    reset_team_records(db)
    n = generate_schedule(db, season=season + 1)
    return {"season": season + 1, "games_generated": n}


@router.post("/reset")
def post_reset(seed: int | None = None) -> dict:
    """Wipe every table and re-seed a fresh league.

    Destructive — kills all teams, players, schedules, box scores, and trade
    history. Used by the frontend's "Reset" button. Pass ``seed`` to override
    the deterministic default (useful for "give me a different league").
    """
    from backend.seed import SEED, reset_database
    return reset_database(seed=seed if seed is not None else SEED)


@router.get("/state")
def get_league_state(db: Session = Depends(get_db)) -> dict:
    """Singleton league state: phase, season, dynamic cap, champion."""
    state = get_state(db)
    champ = db.get(Team, state.champion_team_id) if state.champion_team_id else None
    last_finals = None
    if state.last_champion_season is not None:
        finals = db.scalars(
            select(Series).where(
                Series.season == state.last_champion_season,
                Series.bracket == "Finals",
                Series.round == 4,
            )
        ).first()
        if finals is not None and finals.is_completed:
            runner_up_id = (
                finals.low_seed_team_id
                if finals.winner_team_id == finals.high_seed_team_id
                else finals.high_seed_team_id
            )
            ru = db.get(Team, runner_up_id)
            last_finals = {
                "season": state.last_champion_season,
                "champion_team_id": finals.winner_team_id,
                "runner_up_team_id": runner_up_id,
                "runner_up_abbr": ru.abbreviation if ru else None,
                "high_seed_wins": finals.high_seed_wins,
                "low_seed_wins": finals.low_seed_wins,
            }
    return {
        "current_season": state.current_season,
        "phase": state.phase.value,
        "bst_cap": state.bst_cap,
        "base_bst_cap": settings.bst_cap,
        "champion_team_id": state.champion_team_id,
        "champion_team_abbr": champ.abbreviation if champ else None,
        "last_champion_season": state.last_champion_season,
        "last_finals": last_finals,
        "draft_current_pick": state.draft_current_pick,
        "draft_total_picks": state.draft_total_picks,
    }


@router.post("/start-next-season")
def post_start_next_season(db: Session = Depends(get_db)) -> dict:
    """Generate a fresh schedule, reset records, increment the season counter.

    Only valid when the league is in PRE_SEASON (i.e. draft is finished).
    """
    state = get_state(db)
    if state.phase != Phase.PRE_SEASON:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start next season from phase {state.phase.value!r}.",
        )
    return lifecycle_start_next_season(db)

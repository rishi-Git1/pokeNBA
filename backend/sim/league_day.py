"""Macro engine: simulate one game day across the league.

Performance contract:
- Rosters are loaded **once per day** with two queries (Teams + Players).
- Games run in pure Python memory (no ORM during the possession loop).
- Box scores flush via a single ``executemany`` per day; Game/Team rows update
  in the same transaction.

For a 30-team / 82-game season this is ~1230 games / ~170 game days. A typical
day has 10-15 games and resolves in well under a second on commodity hardware.
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from backend.models import BoxScore, Game, Player, Team
from backend.sim.game import GameResult, players_to_pigs, run_game


@dataclass(slots=True)
class DayResult:
    sim_date: date
    season: int
    games_played: int
    box_scores_written: int
    results: list[GameResult]


def _load_rosters(db: Session, team_ids: set[int]) -> dict[int, list[Player]]:
    """One query, in-memory bucket by team_id."""
    rows = db.scalars(
        select(Player).where(Player.team_id.in_(team_ids), Player.is_retired.is_(False))
    ).all()
    rosters: dict[int, list[Player]] = defaultdict(list)
    for p in rows:
        if p.team_id is not None:
            rosters[p.team_id].append(p)
    return rosters


def _next_unplayed_day(db: Session, season: int) -> date | None:
    row = db.scalars(
        select(Game.game_date)
        .where(
            Game.season == season,
            Game.is_completed.is_(False),
            Game.is_playoff.is_(False),
        )
        .order_by(Game.game_date)
        .limit(1)
    ).first()
    return row


def sim_day(
    db: Session,
    *,
    season: int,
    target_date: date | None = None,
    rng: random.Random | None = None,
    capture_play_log: bool = False,
    parallel: bool = False,
    max_workers: int | None = None,
    executor=None,  # concurrent.futures.Executor or None
) -> DayResult | None:
    """Sim every unplayed game on ``target_date`` (or the next unplayed day).

    Set ``parallel=True`` to spread games across CPU cores. Pass an explicit
    ``executor`` to share a long-lived ``ProcessPoolExecutor`` across many
    days (recommended — pool startup is expensive on Windows). Returns
    ``None`` if there are no remaining games for the season.
    """
    rng = rng or random.Random()
    if target_date is None:
        target_date = _next_unplayed_day(db, season)
        if target_date is None:
            return None

    games: list[Game] = list(
        db.scalars(
            select(Game).where(
                Game.season == season,
                Game.game_date == target_date,
                Game.is_completed.is_(False),
                Game.is_playoff.is_(False),
            )
        )
    )
    if not games:
        return None

    team_ids = {g.home_team_id for g in games} | {g.away_team_id for g in games}
    rosters = _load_rosters(db, team_ids)
    teams: dict[int, Team] = {t.id: t for t in db.scalars(select(Team).where(Team.id.in_(team_ids)))}

    box_score_payload: list[dict] = []

    if parallel or executor is not None:
        # Build picklable worker jobs in the main process, then fan out.
        from backend.sim.parallel import GameJob, _run_one, run_jobs_in_parallel

        jobs: list[GameJob] = []
        for game in games:
            home = teams[game.home_team_id]
            away = teams[game.away_team_id]
            jobs.append(GameJob(
                game_id=game.id,
                season=season,
                home_id=home.id,
                home_abbr=home.abbreviation,
                home_pigs=players_to_pigs(rosters[home.id]),
                away_id=away.id,
                away_abbr=away.abbreviation,
                away_pigs=players_to_pigs(rosters[away.id]),
                seed=rng.randrange(0, 2**31 - 1),
            ))
        if executor is not None:
            # chunksize > 1 amortizes pipe-IPC across multiple jobs per worker
            chunksize = max(1, len(jobs) // (max_workers or 8) // 2)
            results = list(executor.map(_run_one, jobs, chunksize=chunksize))
        else:
            results = run_jobs_in_parallel(jobs, max_workers=max_workers)
    else:
        results = []
        for game in games:
            home = teams[game.home_team_id]
            away = teams[game.away_team_id]
            results.append(run_game(
                game_id=game.id,
                season=season,
                home_id=home.id,
                home_abbr=home.abbreviation,
                home_players=rosters[home.id],
                away_id=away.id,
                away_abbr=away.abbreviation,
                away_players=rosters[away.id],
                rng=rng,
                capture_play_log=capture_play_log,
            ))

    # Persist results (sequentially, since SQLAlchemy session lives here).
    for game, result in zip(games, results):
        home = teams[game.home_team_id]
        away = teams[game.away_team_id]
        box_score_payload.extend(result.box_scores)

        # Update Game row + standings counters
        game.home_score = result.home_score
        game.away_score = result.away_score
        game.overtime_periods = result.overtime_periods
        game.is_completed = True
        if result.home_score > result.away_score:
            home.wins += 1
            away.losses += 1
        else:
            away.wins += 1
            home.losses += 1

    # Single bulk insert for all box scores in the day
    if box_score_payload:
        db.execute(insert(BoxScore), box_score_payload)
    db.commit()

    return DayResult(
        sim_date=target_date,
        season=season,
        games_played=len(results),
        box_scores_written=len(box_score_payload),
        results=results,
    )


def sim_until_done(
    db: Session,
    *,
    season: int,
    rng: random.Random | None = None,
    max_days: int | None = None,
    parallel: bool = False,
    max_workers: int | None = None,
) -> list[DayResult]:
    """Drive the macro engine forward until the season is complete (or ``max_days``).

    When ``parallel=True`` we spin up **one** ProcessPoolExecutor for the whole
    run instead of recreating it per day — Windows ``spawn`` startup is ~5s
    per pool, so a fresh pool every day would dwarf the actual sim cost.
    """
    rng = rng or random.Random()
    days: list[DayResult] = []

    if parallel:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            while True:
                if max_days is not None and len(days) >= max_days:
                    break
                result = sim_day(db, season=season, rng=rng, executor=ex)
                if result is None:
                    break
                days.append(result)
        return days

    while True:
        if max_days is not None and len(days) >= max_days:
            break
        result = sim_day(db, season=season, rng=rng)
        if result is None:
            break
        days.append(result)
    return days

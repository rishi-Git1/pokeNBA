"""Schedule generator.

Produces ``settings.season_games`` (82) matchups per team across distinct game
days, then writes ``Game`` rows to the DB. This is intentionally simpler than
real NBA scheduling — every team plays every other team a balanced number of
times, ordered randomly.

Run standalone with::

    python -m backend.sim.schedule

Or call ``generate_schedule(db, season=1)`` from another module.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.database import SessionLocal, create_all
from backend.models import Game, Team


SEASON_START = date(2026, 10, 22)


def _build_matchup_pairs(team_ids: list[int], games_per_team: int, rng: random.Random) -> list[tuple[int, int]]:
    """Return ``games_per_team * n / 2`` (home, away) pairs such that every team
    appears in exactly ``games_per_team`` games.

    Algorithm: always pair the two teams with the highest remaining "needs".
    With balanced equal needs across all teams this trivially produces a valid
    schedule. Ties are broken with a random shuffle, and we accept that some
    pairs may meet slightly more often than others — this is a scaffold, not
    a real NBA scheduler.
    """
    n = len(team_ids)
    if (n * games_per_team) % 2 != 0:
        raise ValueError("Schedule generator requires n * games_per_team to be even.")

    needs: dict[int, int] = {tid: games_per_team for tid in team_ids}
    pairs: list[tuple[int, int]] = []

    while sum(needs.values()) >= 2:
        # Greedy pairing: shuffle for tie-break, then take the two largest.
        ranked = list(needs.items())
        rng.shuffle(ranked)
        ranked.sort(key=lambda item: item[1], reverse=True)
        if ranked[0][1] == 0:
            break
        a = ranked[0][0]
        # Pair with the top non-self team that still needs games.
        partner = next(((tid, n_) for tid, n_ in ranked[1:] if n_ > 0), None)
        if partner is None:
            break
        b = partner[0]

        home, away = (a, b) if rng.random() < 0.5 else (b, a)
        pairs.append((home, away))
        needs[a] -= 1
        needs[b] -= 1

    return pairs


def _distribute_across_days(
    pairs: list[tuple[int, int]],
    rng: random.Random,
) -> list[tuple[date, int, int]]:
    """Assign each matchup to a date such that no team plays twice on the same day.

    Strategy: shuffle the matchups, then walk the list once. For each pair,
    advance day-by-day from ``SEASON_START`` until we find the first day where
    neither team is already scheduled. This guarantees every pair is placed.
    """
    rng.shuffle(pairs)
    schedule: list[tuple[date, int, int]] = []
    teams_playing_today: dict[date, set[int]] = defaultdict(set)

    for home, away in pairs:
        cursor = SEASON_START
        while True:
            playing = teams_playing_today[cursor]
            if home not in playing and away not in playing:
                schedule.append((cursor, home, away))
                playing.add(home)
                playing.add(away)
                break
            cursor += timedelta(days=1)

    schedule.sort(key=lambda row: (row[0], row[1]))
    return schedule


def generate_schedule(db: Session, *, season: int = 1, rng: random.Random | None = None) -> int:
    """Wipe any existing games for ``season`` and produce a fresh schedule.

    Returns the number of games written.
    """
    rng = rng or random.Random(season)
    db.execute(delete(Game).where(Game.season == season))

    team_ids = [t.id for t in db.scalars(select(Team).order_by(Team.id))]
    pairs = _build_matchup_pairs(team_ids, settings.season_games, rng)
    rows = _distribute_across_days(pairs, rng)

    db.bulk_save_objects(
        [
            Game(season=season, game_date=d, home_team_id=h, away_team_id=a)
            for d, h, a in rows
        ]
    )
    db.commit()
    return len(rows)


def main() -> None:
    create_all()
    with SessionLocal() as db:
        n = generate_schedule(db, season=1)
        print(f"Generated {n} games for season 1.")


if __name__ == "__main__":
    main()

"""Smoke test injury rolls and roster filtering."""
from __future__ import annotations

import random

from backend.database import SessionLocal, create_all
from backend.league.injuries import (
    BASE_INJURY_CHANCE,
    INJURY_STACK_PER_PRIOR,
    advance_injury_clocks,
    injury_probability,
    prepare_team_roster,
)
from backend.models import Player, PlayerSeasonInjury
from sqlalchemy import select


def main() -> None:
    create_all()
    rng = random.Random(42)

    with SessionLocal() as db:
        roster = list(db.scalars(select(Player).where(Player.team_id.is_not(None)).limit(15)))
        team_id = roster[0].team_id
        season = 99

        for s in db.scalars(select(PlayerSeasonInjury).where(PlayerSeasonInjury.season == season)):
            db.delete(s)
        db.commit()

        total_new = 0
        for game in range(1, 8):
            available, report = prepare_team_roster(
                db, season=season, roster=roster, rng=rng, phase="regular_season",
            )
            total_new += len(report.new_injuries)
            advance_injury_clocks(db, season=season, team_ids={team_id})  # type: ignore[arg-type]
            db.commit()
            print(
                f"Game {game}: available={len(available)}/{len(roster)} "
                f"new_inj={len(report.new_injuries)} sidelined={len(report.unavailable)}"
            )

        states = list(db.scalars(select(PlayerSeasonInjury).where(PlayerSeasonInjury.season == season)))
        print(f"Total new injuries over 7 games: {total_new}")
        print(f"Players with injury history: {len(states)}")

    assert injury_probability(0) == BASE_INJURY_CHANCE
    assert injury_probability(2) == BASE_INJURY_CHANCE + 2 * INJURY_STACK_PER_PRIOR
    print("OK")


if __name__ == "__main__":
    main()

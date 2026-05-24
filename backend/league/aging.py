"""End-of-season state machine: aging, retirement, regens, fresh draft picks.

Run via the API (``POST /api/league/end-season``) or the CLI
(``python -m backend.league.cli end-season``). The function is idempotent in
the sense that callers should bump the season counter themselves; this module
just performs the cleanup pass.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.player_factory import build_regen
from backend.models import DraftPick, Player, Team


# Aging curve constants (tweak freely)
AGING_PEAK_AGE: int = 28          # no decay before this
AGING_DECAY_PER_YEAR_PAST_PEAK: float = 0.04  # speed/HP decay rate
AGING_OTHER_STATS_DECAY: float = 0.015        # gentler decay for ATK/DEF/SPA/SPD


@dataclass(slots=True)
class EndOfSeasonReport:
    season: int
    next_season: int
    aged_players: int
    retired_players: int
    regens_generated: int
    new_picks_generated: int


def _apply_aging(player: Player) -> None:
    """One season older. Speed and HP decay first; other stats degrade slowly."""
    player.age += 1
    player.seasons_played += 1

    if player.age <= AGING_PEAK_AGE:
        return  # still in their prime

    years_past_peak = player.age - AGING_PEAK_AGE
    speed_decay = AGING_DECAY_PER_YEAR_PAST_PEAK * years_past_peak
    other_decay = AGING_OTHER_STATS_DECAY * years_past_peak

    player.cur_speed = max(1, int(round(player.base_speed * (1.0 - speed_decay))))
    player.cur_hp = max(1, int(round(player.base_hp * (1.0 - speed_decay))))
    player.cur_attack = max(1, int(round(player.base_attack * (1.0 - other_decay))))
    player.cur_defense = max(1, int(round(player.base_defense * (1.0 - other_decay))))
    player.cur_sp_attack = max(1, int(round(player.base_sp_attack * (1.0 - other_decay))))
    player.cur_sp_defense = max(1, int(round(player.base_sp_defense * (1.0 - other_decay))))


def _retire_if_done(player: Player) -> bool:
    """Mark retired if they hit their career_length. Returns ``True`` if retired."""
    if player.seasons_played >= player.career_length:
        player.is_retired = True
        player.team_id = None  # vacate roster slot
        return True
    return False


def _tick_rookie_deal(player: Player) -> None:
    """Burn one season of rookie-deal eligibility. Roll off the deal at zero."""
    if player.on_rookie_deal and player.rookie_seasons_remaining > 0:
        player.rookie_seasons_remaining -= 1
        if player.rookie_seasons_remaining <= 0:
            player.on_rookie_deal = False


def end_of_season(db: Session, *, season: int, rng: random.Random | None = None) -> EndOfSeasonReport:
    """Execute every end-of-season transition for ``season``.

    Order matters:
    1. Age every active player and apply stat decay.
    2. Retire any player who hit their career length cap.
    3. For each retired player, spawn a regen of the same species into the
       free-agent pool (next season's draft eligible).
    4. Generate two rounds of fresh draft picks for the next season.
    """
    rng = rng or random.Random(season + 12345)

    active_players = db.scalars(
        select(Player).where(Player.is_retired.is_(False))
    ).all()

    aged = 0
    retiring: list[Player] = []
    for p in active_players:
        _apply_aging(p)
        _tick_rookie_deal(p)
        aged += 1
        if _retire_if_done(p):
            retiring.append(p)

    regens: list[Player] = []
    for retiree in retiring:
        regen = build_regen(
            retiree=retiree,
            next_generation=retiree.generation + 1,
            rng=rng,
        )
        regens.append(regen)

    if regens:
        db.add_all(regens)

    # Fresh draft picks for the next season
    next_season = season + 1
    teams = list(db.scalars(select(Team).order_by(Team.id)))
    new_picks = [
        DraftPick(
            season=next_season,
            round=rd,
            pick_number=None,
            original_team_id=team.id,
            owning_team_id=team.id,
            is_used=False,
        )
        for team in teams
        for rd in (1, 2)
    ]
    db.add_all(new_picks)
    db.commit()

    return EndOfSeasonReport(
        season=season,
        next_season=next_season,
        aged_players=aged,
        retired_players=len(retiring),
        regens_generated=len(regens),
        new_picks_generated=len(new_picks),
    )


def reset_team_records(db: Session) -> None:
    """Wipe last season's W/L from all teams. Call before generating a new schedule."""
    for team in db.scalars(select(Team)):
        team.wins = 0
        team.losses = 0
    db.commit()

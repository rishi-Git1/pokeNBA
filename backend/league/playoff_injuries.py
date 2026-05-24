"""Playoff injury rolls, roster filtering, and per-game reports.

Before each playoff game:
1. Exclude anyone still on the injury list (``games_remaining > 0``).
2. Roll a fresh injury for every remaining roster player in the series.
3. Anyone who rolls injured sits **this game** and for 1–6 more playoff games.

Stacking: a player who has already been hurt this postseason gets +5% flat
per prior injury on top of the 10% base rate.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Player, PlayoffPlayerState

BASE_INJURY_CHANCE: float = 0.10
INJURY_STACK_PER_PRIOR: float = 0.05
MIN_GAMES_OUT: int = 1
MAX_GAMES_OUT: int = 6


@dataclass(slots=True)
class InjuryEvent:
    player_id: int
    player_name: str
    team_id: int
    pokedex_id: int
    sprite_url: str
    games_out: int
    prior_injuries: int
    roll_probability: float

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "team_id": self.team_id,
            "pokedex_id": self.pokedex_id,
            "sprite_url": self.sprite_url,
            "games_out": self.games_out,
        }


@dataclass(slots=True)
class UnavailablePlayer:
    player_id: int
    player_name: str
    team_id: int
    pokedex_id: int
    sprite_url: str
    games_remaining: int
    reason: str  # "existing" | "new"

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "team_id": self.team_id,
            "pokedex_id": self.pokedex_id,
            "sprite_url": self.sprite_url,
            "games_remaining": self.games_remaining,
            "reason": self.reason,
        }


@dataclass(slots=True)
class PlayoffInjuryReport:
    new_injuries: list[InjuryEvent] = field(default_factory=list)
    unavailable: list[UnavailablePlayer] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "new_injuries": [e.to_dict() for e in self.new_injuries],
            "unavailable": [u.to_dict() for u in self.unavailable],
        }


def injury_probability(prior_injuries: int) -> float:
    """10% base + 5% per prior injury this postseason (capped at 100%)."""
    return min(1.0, BASE_INJURY_CHANCE + INJURY_STACK_PER_PRIOR * prior_injuries)


def _get_or_create_state(
    db: Session, *, season: int, player: Player
) -> PlayoffPlayerState:
    state = db.scalars(
        select(PlayoffPlayerState).where(
            PlayoffPlayerState.season == season,
            PlayoffPlayerState.player_id == player.id,
        )
    ).first()
    if state is None:
        state = PlayoffPlayerState(
            season=season,
            player_id=player.id,
            team_id=player.team_id,  # type: ignore[arg-type]
            injury_count=0,
            games_remaining=0,
        )
        db.add(state)
        db.flush()
    elif player.team_id is not None:
        state.team_id = player.team_id
    return state


def _load_states_for_roster(
    db: Session, *, season: int, roster: list[Player]
) -> dict[int, PlayoffPlayerState]:
    if not roster:
        return {}
    ids = [p.id for p in roster]
    rows = list(db.scalars(
        select(PlayoffPlayerState).where(
            PlayoffPlayerState.season == season,
            PlayoffPlayerState.player_id.in_(ids),
        )
    ))
    by_player = {s.player_id: s for s in rows}
    for p in roster:
        if p.id not in by_player:
            by_player[p.id] = _get_or_create_state(db, season=season, player=p)
    return by_player


def prepare_team_roster(
    db: Session,
    *,
    season: int,
    roster: list[Player],
    rng: random.Random,
) -> tuple[list[Player], PlayoffInjuryReport]:
    """Filter injuries and roll new ones before a playoff game."""
    report = PlayoffInjuryReport()
    if not roster:
        return [], report

    states = _load_states_for_roster(db, season=season, roster=roster)
    available: list[Player] = []

    for player in roster:
        state = states[player.id]
        if state.games_remaining > 0:
            report.unavailable.append(UnavailablePlayer(
                player_id=player.id,
                player_name=player.name,
                team_id=player.team_id,  # type: ignore[arg-type]
                pokedex_id=player.pokedex_id,
                sprite_url=player.sprite_url,
                games_remaining=state.games_remaining,
                reason="existing",
            ))
            continue

        prob = injury_probability(state.injury_count)
        if rng.random() < prob:
            games_out = rng.randint(MIN_GAMES_OUT, MAX_GAMES_OUT)
            prior = state.injury_count
            state.injury_count += 1
            state.games_remaining = games_out
            report.new_injuries.append(InjuryEvent(
                player_id=player.id,
                player_name=player.name,
                team_id=player.team_id,  # type: ignore[arg-type]
                pokedex_id=player.pokedex_id,
                sprite_url=player.sprite_url,
                games_out=games_out,
                prior_injuries=prior,
                roll_probability=prob,
            ))
            report.unavailable.append(UnavailablePlayer(
                player_id=player.id,
                player_name=player.name,
                team_id=player.team_id,  # type: ignore[arg-type]
                pokedex_id=player.pokedex_id,
                sprite_url=player.sprite_url,
                games_remaining=games_out,
                reason="new",
            ))
            continue

        available.append(player)

    return available, report


def advance_injury_clocks(db: Session, *, season: int, team_ids: set[int]) -> None:
    """After a playoff game, tick down injury timers for both teams."""
    if not team_ids:
        return
    rows = list(db.scalars(
        select(PlayoffPlayerState).where(
            PlayoffPlayerState.season == season,
            PlayoffPlayerState.team_id.in_(team_ids),
            PlayoffPlayerState.games_remaining > 0,
        )
    ))
    for state in rows:
        state.games_remaining = max(0, state.games_remaining - 1)


def merge_reports(*reports: PlayoffInjuryReport) -> PlayoffInjuryReport:
    merged = PlayoffInjuryReport()
    for r in reports:
        merged.new_injuries.extend(r.new_injuries)
        merged.unavailable.extend(r.unavailable)
    return merged

"""Injury rolls, roster filtering, history, and season resets.

Rates: 1% base + 1.5% per prior injury this season (regular season + playoffs).
Injuries persist from the regular season into the postseason and reset during
the offseason (after the champion is crowned, before the draft).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.league.state import get_state
from backend.models import Player, PlayerInjuryEvent, PlayerSeasonInjury

BASE_INJURY_CHANCE: float = 0.01
INJURY_STACK_PER_PRIOR: float = 0.015
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
class InjuryReport:
    new_injuries: list[InjuryEvent] = field(default_factory=list)
    unavailable: list[UnavailablePlayer] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "new_injuries": [e.to_dict() for e in self.new_injuries],
            "unavailable": [u.to_dict() for u in self.unavailable],
        }


# Backwards-compatible alias for playoff code.
PlayoffInjuryReport = InjuryReport


def injury_probability(prior_injuries: int) -> float:
    """1% base + 1.5% per prior injury this season (capped at 100%)."""
    return min(1.0, BASE_INJURY_CHANCE + INJURY_STACK_PER_PRIOR * prior_injuries)


def _get_or_create_state(
    db: Session, *, season: int, player: Player
) -> PlayerSeasonInjury:
    state = db.scalars(
        select(PlayerSeasonInjury).where(
            PlayerSeasonInjury.season == season,
            PlayerSeasonInjury.player_id == player.id,
        )
    ).first()
    if state is None:
        state = PlayerSeasonInjury(
            season=season,
            player_id=player.id,
            team_id=player.team_id,
            injury_count=0,
            games_remaining=0,
            stint_games_total=0,
        )
        db.add(state)
        db.flush()
    elif player.team_id is not None:
        state.team_id = player.team_id
    return state


def _log_event(
    db: Session,
    *,
    season: int,
    player_id: int,
    team_id: int | None,
    phase: str,
    event_date: date,
    event_type: str,
    games_out: int = 0,
) -> None:
    db.add(PlayerInjuryEvent(
        season=season,
        player_id=player_id,
        team_id=team_id,
        phase=phase,
        event_date=event_date,
        event_type=event_type,
        games_out=games_out,
    ))


def _load_states_for_roster(
    db: Session, *, season: int, roster: list[Player]
) -> dict[int, PlayerSeasonInjury]:
    if not roster:
        return {}
    ids = [p.id for p in roster]
    rows = list(db.scalars(
        select(PlayerSeasonInjury).where(
            PlayerSeasonInjury.season == season,
            PlayerSeasonInjury.player_id.in_(ids),
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
    phase: str = "playoffs",
    event_date: date | None = None,
) -> tuple[list[Player], InjuryReport]:
    """Filter injuries and roll new ones before a game."""
    report = InjuryReport()
    if not roster:
        return [], report

    when = event_date or date.today()
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
            state.stint_games_total = games_out
            _log_event(
                db,
                season=season,
                player_id=player.id,
                team_id=player.team_id,
                phase=phase,
                event_date=when,
                event_type="injured",
                games_out=games_out,
            )
            report.new_injuries.append(InjuryEvent(
                player_id=player.id,
                player_name=player.name,
                team_id=player.team_id,  # type: ignore[arg-type]
                pokedex_id=player.pokedex_id,
                sprite_url=player.sprite_url,
                games_out=games_out,
                prior_injuries=prior,
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


def advance_injury_clocks(
    db: Session,
    *,
    season: int,
    team_ids: set[int],
    phase: str = "playoffs",
    event_date: date | None = None,
) -> None:
    """After a game, tick down injury timers."""
    if not team_ids:
        return
    when = event_date or date.today()
    rows = list(db.scalars(
        select(PlayerSeasonInjury).where(
            PlayerSeasonInjury.season == season,
            PlayerSeasonInjury.team_id.in_(team_ids),
            PlayerSeasonInjury.games_remaining > 0,
        )
    ))
    for state in rows:
        state.games_remaining = max(0, state.games_remaining - 1)
        if state.games_remaining == 0:
            state.stint_games_total = 0
            _log_event(
                db,
                season=season,
                player_id=state.player_id,
                team_id=state.team_id,
                phase=phase,
                event_date=when,
                event_type="recovered",
            )


def merge_reports(*reports: InjuryReport) -> InjuryReport:
    merged = InjuryReport()
    for r in reports:
        merged.new_injuries.extend(r.new_injuries)
        merged.unavailable.extend(r.unavailable)
    return merged


def load_injury_map(
    db: Session, *, season: int, player_ids: list[int]
) -> dict[int, PlayerSeasonInjury]:
    if not player_ids:
        return {}
    rows = list(db.scalars(
        select(PlayerSeasonInjury).where(
            PlayerSeasonInjury.season == season,
            PlayerSeasonInjury.player_id.in_(player_ids),
        )
    ))
    return {r.player_id: r for r in rows}


def injury_status_dict(state: PlayerSeasonInjury | None) -> dict:
    if state is None:
        return {
            "is_injured": False,
            "games_remaining": 0,
            "stint_games_total": 0,
            "season_injury_count": 0,
        }
    return {
        "is_injured": state.games_remaining > 0,
        "games_remaining": state.games_remaining,
        "stint_games_total": state.stint_games_total,
        "season_injury_count": state.injury_count,
    }


def get_player_injury_profile(
    db: Session, *, player_id: int, season: int | None = None
) -> dict:
    season = season if season is not None else get_state(db).current_season
    state = db.scalars(
        select(PlayerSeasonInjury).where(
            PlayerSeasonInjury.season == season,
            PlayerSeasonInjury.player_id == player_id,
        )
    ).first()
    events = list(db.scalars(
        select(PlayerInjuryEvent)
        .where(
            PlayerInjuryEvent.season == season,
            PlayerInjuryEvent.player_id == player_id,
        )
        .order_by(PlayerInjuryEvent.event_date, PlayerInjuryEvent.id)
    ))
    return {
        "season": season,
        "current": injury_status_dict(state),
        "events": [
            {
                "event_date": str(ev.event_date),
                "phase": ev.phase,
                "event_type": ev.event_type,
                "games_out": ev.games_out,
                "team_id": ev.team_id,
            }
            for ev in events
        ],
    }


def clear_player_injury_data(db: Session, *, player_id: int, season: int) -> None:
    db.execute(
        delete(PlayerInjuryEvent).where(
            PlayerInjuryEvent.season == season,
            PlayerInjuryEvent.player_id == player_id,
        )
    )
    db.execute(
        delete(PlayerSeasonInjury).where(
            PlayerSeasonInjury.season == season,
            PlayerSeasonInjury.player_id == player_id,
        )
    )


def handle_player_release(db: Session, *, player: Player, season: int) -> bool:
    """Clear injury data on cut. Returns True if the player was injured when cut."""
    state = db.scalars(
        select(PlayerSeasonInjury).where(
            PlayerSeasonInjury.season == season,
            PlayerSeasonInjury.player_id == player.id,
        )
    ).first()
    was_injured = state is not None and state.games_remaining > 0
    clear_player_injury_data(db, player_id=player.id, season=season)
    return was_injured


def apply_waiver_wire_penalty(player: Player) -> None:
    """Halve every current stat after being cut while injured."""
    player.cur_hp = max(1, player.cur_hp // 2)
    player.cur_attack = max(1, player.cur_attack // 2)
    player.cur_defense = max(1, player.cur_defense // 2)
    player.cur_sp_attack = max(1, player.cur_sp_attack // 2)
    player.cur_sp_defense = max(1, player.cur_sp_defense // 2)
    player.cur_speed = max(1, player.cur_speed // 2)
    player.bst = (
        player.cur_hp + player.cur_attack + player.cur_defense
        + player.cur_sp_attack + player.cur_sp_defense + player.cur_speed
    )


def reset_season_injuries(db: Session, *, season: int) -> None:
    """Wipe all injury state/history for a completed season (offseason reset)."""
    db.execute(delete(PlayerInjuryEvent).where(PlayerInjuryEvent.season == season))
    db.execute(delete(PlayerSeasonInjury).where(PlayerSeasonInjury.season == season))
    for player in db.scalars(select(Player)):
        if player.injury_penalty_pending:
            player.injury_penalty_pending = False


def enrich_players(db: Session, players: list[Player], *, season: int | None = None) -> list[dict]:
    """Serialize players with embedded injury status."""
    from backend.schemas.player import PlayerSummary

    season = season if season is not None else get_state(db).current_season
    injury_map = load_injury_map(db, season=season, player_ids=[p.id for p in players])
    out: list[dict] = []
    for player in players:
        payload = PlayerSummary.model_validate(player).model_dump(mode="json")
        payload["injury"] = injury_status_dict(injury_map.get(player.id))
        out.append(payload)
    return out

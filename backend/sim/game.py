"""Whole-game runner: builds lineups, loops possessions, applies subs.

Output is a ``GameResult`` containing the final score and a list of player box
score dicts that the Macro engine flushes to SQLite via ``executemany``.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from backend.core.config import settings
from backend.models.player import Player, Position
from backend.sim import tuning as t
from backend.sim.possession import resolve_possession
from backend.sim.rotation import apply_substitutions, end_quarter_recovery
from backend.sim.state import GameState, PlayerInGame, TeamInGame


# Position priority for picking starters (1 of each, tallest position last)
STARTER_POSITION_ORDER: tuple[Position, ...] = (
    Position.PG, Position.SG, Position.SF, Position.PF, Position.C,
)


@dataclass(slots=True)
class GameResult:
    home_team_id: int
    away_team_id: int
    home_score: int
    away_score: int
    box_scores: list[dict]   # per-player, ready for executemany
    play_log: list[str]      # play-by-play for the UI / debugging
    overtime_periods: int = 0


# ----------------------------------------------------------------------------
# Lineup construction
# ----------------------------------------------------------------------------
def _pick_starters(roster: list[PlayerInGame]) -> tuple[list[PlayerInGame], list[PlayerInGame]]:
    """Take the highest-stamina player at each position; rest go to the bench.

    Falls back to "best by inside+outside rating" if no player at a position
    exists (small mocks may lack a true PG).
    """
    by_pos: dict[Position, list[PlayerInGame]] = {pos: [] for pos in Position}
    for p in roster:
        by_pos[p.position].append(p)

    starters: list[PlayerInGame] = []
    for pos in STARTER_POSITION_ORDER:
        bucket = sorted(
            by_pos[pos],
            key=lambda p: p.inside + p.outside + p.interior_d + p.perimeter_d,
            reverse=True,
        )
        if bucket:
            starters.append(bucket.pop(0))
            by_pos[pos] = bucket  # leftover at this pos goes to bench

    # Fill any missing positions with the best leftover overall.
    leftovers = [p for bucket in by_pos.values() for p in bucket if p not in starters]
    leftovers.sort(
        key=lambda p: p.inside + p.outside + p.interior_d + p.perimeter_d,
        reverse=True,
    )
    while len(starters) < 5 and leftovers:
        starters.append(leftovers.pop(0))

    bench = [p for p in roster if p not in starters]
    for s in starters:
        s.is_starter = True
        s.on_court = True
    return starters, bench


def _build_team_in_game(team_id: int, abbr: str, players: list[Player]) -> TeamInGame:
    in_game = [PlayerInGame.from_orm(p) for p in players]
    return _build_team_from_pigs(team_id, abbr, in_game)


def _build_team_from_pigs(team_id: int, abbr: str, pigs: list[PlayerInGame]) -> TeamInGame:
    """Build a TeamInGame from already-built PlayerInGame instances.

    Exposed for the parallel worker path: the main process builds PIGs
    (cheap, just reads ORM scalar attrs) and ships them to workers.
    """
    starters, bench = _pick_starters(pigs)
    return TeamInGame(team_id=team_id, abbreviation=abbr, on_court=starters, bench=bench)


def players_to_pigs(players: list[Player]) -> list[PlayerInGame]:
    """Convert ORM Players to PlayerInGame snapshots (decouples from session)."""
    return [PlayerInGame.from_orm(p) for p in players]


# ----------------------------------------------------------------------------
# Box score serialization
# ----------------------------------------------------------------------------
def _serialize_box(p: PlayerInGame, game_id: int, season: int) -> dict:
    usage_rate = 0.0
    # Approximate USG% as personal possessions / team possessions.
    return {
        "game_id": game_id,
        "player_id": p.player_id,
        "team_id": p.team_id,
        "season": season,
        "is_starter": p.is_starter,
        "minutes": round(p.minutes, 2),
        "points": p.points,
        "rebounds": p.rebounds,
        "assists": p.assists,
        "steals": p.steals,
        "blocks": p.blocks,
        "turnovers": p.turnovers,
        "fouls": p.fouls,
        "fg_made": p.fg_made,
        "fg_attempted": p.fg_attempted,
        "three_made": p.three_made,
        "three_attempted": p.three_attempted,
        "ft_made": p.ft_made,
        "ft_attempted": p.ft_attempted,
        "plus_minus": p.plus_minus,
        "usage_rate": usage_rate,
    }


def _finalize_plus_minus(state: GameState) -> None:
    """+/- = team net while player was on court. We approximate using minutes share."""
    home_net = state.home.score - state.away.score
    away_net = -home_net
    total_minutes = settings.quarters_per_game * 5 * (settings.quarter_length_seconds / 60.0)
    if total_minutes <= 0:
        return
    for team, net in ((state.home, home_net), (state.away, away_net)):
        for p in team.all_players:
            share = p.minutes / total_minutes
            p.plus_minus = round(net * share)


def _finalize_usage(state: GameState, payload: list[dict]) -> None:
    """Set usage_rate per player based on team possessions used while on court."""
    payload_by_id = {row["player_id"]: row for row in payload}
    for team in (state.home, state.away):
        team_total = max(1, sum(p.possessions_used for p in team.all_players))
        for p in team.all_players:
            row = payload_by_id.get(p.player_id)
            if row is not None:
                row["usage_rate"] = round(p.possessions_used / team_total, 3)


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------
def run_game(
    *,
    game_id: int,
    season: int,
    home_id: int,
    home_abbr: str,
    home_players: list[Player],
    away_id: int,
    away_abbr: str,
    away_players: list[Player],
    rng: random.Random | None = None,
    capture_play_log: bool = False,
) -> GameResult:
    """Run one game start to finish from ORM Player lists."""
    home = _build_team_in_game(home_id, home_abbr, home_players)
    away = _build_team_in_game(away_id, away_abbr, away_players)
    return _run_prepared(
        game_id=game_id,
        season=season,
        home=home,
        away=away,
        rng=rng or random.Random(),
        capture_play_log=capture_play_log,
    )


def run_prepared_game(
    *,
    game_id: int,
    season: int,
    home: TeamInGame,
    away: TeamInGame,
    seed: int,
    capture_play_log: bool = False,
) -> GameResult:
    """Worker-friendly variant: takes pre-built lineups and a deterministic seed.

    Used by the parallel executor so worker inputs are fully picklable.
    """
    return _run_prepared(
        game_id=game_id,
        season=season,
        home=home,
        away=away,
        rng=random.Random(seed),
        capture_play_log=capture_play_log,
    )


def _run_prepared(
    *,
    game_id: int,
    season: int,
    home: TeamInGame,
    away: TeamInGame,
    rng: random.Random,
    capture_play_log: bool,
) -> GameResult:
    home_id = home.team_id
    away_id = away.team_id
    state = GameState(home=home, away=away, possession_team_id=home_id)

    for q in range(1, settings.quarters_per_game + 1):
        state.quarter = q
        state.clock_seconds = float(settings.quarter_length_seconds)
        # Tip-off alternates by quarter (home Q1/Q4, away Q2/Q3) — simplification.
        state.possession_team_id = home_id if q in (1, 4) else away_id
        _play_period(state, rng, capture_play_log)
        end_quarter_recovery(state)

    # --- Overtime ----------------------------------------------------------
    overtime_periods = 0
    while state.home.score == state.away.score and overtime_periods < t.MAX_OVERTIME_PERIODS:
        overtime_periods += 1
        state.quarter = settings.quarters_per_game + overtime_periods
        state.clock_seconds = float(t.OVERTIME_LENGTH_SECONDS)
        # Alternate possession in OT: even periods home, odd periods away.
        state.possession_team_id = home_id if overtime_periods % 2 else away_id
        _play_period(state, rng, capture_play_log)
        end_quarter_recovery(state)

    _finalize_plus_minus(state)
    box_scores = [
        _serialize_box(p, game_id=game_id, season=season)
        for team in (state.home, state.away)
        for p in team.all_players
        if p.minutes > 0  # skip players who never checked in (too small a roster)
    ]
    _finalize_usage(state, box_scores)

    return GameResult(
        home_team_id=home_id,
        away_team_id=away_id,
        home_score=state.home.score,
        away_score=state.away.score,
        box_scores=box_scores,
        play_log=state.log,
        overtime_periods=overtime_periods,
    )


def _play_period(state: GameState, rng: random.Random, capture_play_log: bool) -> None:
    """Run one period (quarter or OT) until the clock hits zero."""
    while state.clock_seconds > 0:
        result = resolve_possession(state, rng)
        if capture_play_log:
            label = "Q" + str(state.quarter) if state.quarter <= 4 else f"OT{state.quarter - 4}"
            state.log.append(
                f"{label:<4} {int(state.clock_seconds):>3}s | "
                f"{state.home.score:>3}-{state.away.score:<3} | {result.description}"
            )
        if result.is_dead_ball and not result.ends_quarter:
            sub_log = apply_substitutions(state)
            if capture_play_log:
                state.log.extend(sub_log)
        if result.ends_quarter:
            break

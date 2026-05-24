"""Mid engine: substitution logic that runs at every dead ball.

Strategy:
1. Force-sub anyone who fouled out or whose stamina dropped below the hard
   threshold.
2. For each tired player, pull them if a fresher backup at the same position
   exists on the bench. Otherwise fall back to any fresh bench player.
3. At quarter breaks, fully refresh: stamina rebounds and starters return.

This is intentionally simple — once the user has roster management UIs we can
slot in a per-team depth chart here without changing the contract.
"""
from __future__ import annotations

from backend.sim import tuning as t
from backend.sim.state import GameState, PlayerInGame, TeamInGame


def _pick_replacement(team: TeamInGame, out: PlayerInGame) -> PlayerInGame | None:
    """Find the freshest viable bench player. Prefer same position."""
    eligible = [p for p in team.bench if not p.fouled_out and p.current_stamina > 0.5 * p.max_stamina]
    if not eligible:
        eligible = [p for p in team.bench if not p.fouled_out]
    if not eligible:
        return None
    same_pos = [p for p in eligible if p.position == out.position]
    pool = same_pos or eligible
    # Pick the one with the most stamina remaining (in pct terms).
    return max(pool, key=lambda p: p.stamina_pct)


def _swap(team: TeamInGame, out: PlayerInGame, in_: PlayerInGame) -> None:
    team.on_court.remove(out)
    team.bench.remove(in_)
    out.on_court = False
    in_.on_court = True
    team.on_court.append(in_)
    team.bench.append(out)


def _apply_team_subs(team: TeamInGame) -> list[tuple[str, str]]:
    swaps: list[tuple[str, str]] = []
    # Iterate over a snapshot — _swap mutates team.on_court.
    for player in list(team.on_court):
        force = player.fouled_out or player.stamina_pct < t.STAMINA_FORCE_SUB_THRESHOLD
        soft = player.stamina_pct < t.STAMINA_SUB_THRESHOLD or player.fouls >= t.FOULS_TO_FOUL_OUT - 1
        if not (force or soft):
            continue
        replacement = _pick_replacement(team, player)
        if replacement is None:
            continue
        # If only soft-tired and no significantly fresher option, skip.
        if not force and replacement.stamina_pct <= player.stamina_pct + 0.10:
            continue
        _swap(team, player, replacement)
        swaps.append((player.name, replacement.name))
    return swaps


def apply_substitutions(state: GameState) -> list[str]:
    """Run subs for both teams. Returns play-by-play strings for logging."""
    out: list[str] = []
    for team in (state.home, state.away):
        for player_out, player_in in _apply_team_subs(team):
            out.append(f"SUB ({team.abbreviation}): {player_in} for {player_out}")
    return out


def end_quarter_recovery(state: GameState) -> None:
    """Between quarters, pump some stamina back into everyone."""
    for team in (state.home, state.away):
        for p in team.all_players:
            recovery = p.max_stamina * 0.25
            p.current_stamina = min(float(p.max_stamina), p.current_stamina + recovery)
        team.fouls_quarter = 0

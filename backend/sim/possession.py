"""Micro engine: resolve a single 5v5 possession.

Pure function:
    resolve_possession(state, rng) -> PossessionResult

Does NOT mutate the DB. It mutates the in-memory ``GameState`` (clock, score,
box-score accumulators, stamina). The Mid engine listens for ``ends_quarter``
or ``is_dead_ball`` to know when to run substitutions.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from backend.sim import tuning as t
from backend.sim.modifiers import (
    Modifiers,
    aggregate_for_player,
    aggregate_team_modifiers,
)
from backend.sim.state import GameState, PlayerInGame, TeamInGame


# ----------------------------------------------------------------------------
# Public result type
# ----------------------------------------------------------------------------
@dataclass(slots=True)
class PossessionResult:
    seconds_used: float
    points_scored: int
    is_dead_ball: bool       # made FG, foul, OOB, end-of-quarter — sub trigger
    ends_quarter: bool
    description: str


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _possession_seconds(offense: TeamInGame, team_mods: Modifiers, rng: random.Random) -> float:
    """How long this possession takes off the clock."""
    avg_speed = offense.avg_speed_on_court
    base = t.POSSESSION_BASE_SECONDS + (avg_speed - 60) * t.POSSESSION_SECONDS_PER_SPEED_PT
    base /= max(0.5, team_mods.team_pace)  # Fast Break Threat shrinks possession length
    # Add a touch of noise for realism.
    base += rng.uniform(-2.0, 2.0)
    return _clamp(base, t.POSSESSION_MIN_SECONDS, t.POSSESSION_MAX_SECONDS)


def _pick_shooter(
    offense: TeamInGame,
    state: GameState,
    rng: random.Random,
) -> PlayerInGame:
    """USG% selection: weighted-random pick of who takes the shot.

    Weight = (inside + outside) / 2 + self_usage_rate badge bumps.
    Defender always-on Lockdown badges shrink the matchup's USG via
    ``opp_usage_rate``, but for v1 we apply that as a flat team-wide nerf.
    """
    weights: list[float] = []
    for p in offense.on_court:
        base = (p.inside + p.outside) / 2.0
        # Self badges that bump usage (Sniper, Slasher, Volume Scorer, Heat Check)
        bump = 0.0
        for ctx in ("always", "on_shot_inside", "on_shot_outside", "after_made_shot"):
            bump += aggregate_for_player(p, ctx, state).self_usage_rate
        if p.is_fatigued:
            base *= 0.7  # tired players touch the ball less
        weights.append(max(1.0, base * (1.0 + bump)))
    return rng.choices(offense.on_court, weights=weights, k=1)[0]


def _pick_defender(defense: TeamInGame, shooter: PlayerInGame, rng: random.Random) -> PlayerInGame:
    """Match defender by position when possible, else fall back to a random."""
    same_pos = [d for d in defense.on_court if d.position == shooter.position]
    if same_pos:
        return same_pos[0]
    return rng.choice(defense.on_court)


def _is_outside_shot(shooter: PlayerInGame, rng: random.Random) -> bool:
    """Inside (2PT) vs outside (3PT) selection using attack/sp_attack ratio."""
    total = shooter.inside + shooter.outside
    if total <= 0:
        return False
    sp_share = shooter.outside / total  # 0..1 — leans outside if Sp.Atk > Atk
    prob = t.OUTSIDE_SHOT_BASE + (sp_share - 0.5) * 2 * t.OUTSIDE_SHOT_RATIO_WEIGHT
    prob = _clamp(prob, t.OUTSIDE_SHOT_FLOOR, t.OUTSIDE_SHOT_CEIL)
    return rng.random() < prob


def _shot_pct(
    shooter: PlayerInGame,
    defender: PlayerInGame,
    is_outside: bool,
    state: GameState,
    rng: random.Random,
) -> float:
    """Resolved FG% for this attempt, including badges and fatigue."""
    shooter_rating = shooter.outside if is_outside else shooter.inside
    defender_rating = defender.perimeter_d if is_outside else defender.interior_d

    base = t.OUTSIDE_FG_BASE if is_outside else t.INSIDE_FG_BASE
    diff = (shooter_rating - defender_rating) * t.RATING_DIFF_WEIGHT
    pct = base + diff

    # Shooter self-badges (Sniper, Slasher, Heat Check, Clutch Performer)
    ctx = "on_shot_outside" if is_outside else "on_shot_inside"
    self_mods = aggregate_for_player(shooter, ctx, state)
    pct += self_mods.self_outside_fg_pct if is_outside else self_mods.self_inside_fg_pct

    if state.is_clutch():
        clutch = aggregate_for_player(shooter, "4th_quarter", state)
        pct += clutch.self_outside_fg_pct if is_outside else clutch.self_inside_fg_pct

    # Defender always-on badges (Lockdown Defender, Glass Cannon liability)
    def_mods = aggregate_for_player(defender, "always", state)
    pct += def_mods.opp_outside_fg_pct if is_outside else def_mods.opp_inside_fg_pct
    # Post Anchor (on_defense_inside) for big men contesting the rim
    if not is_outside:
        post_mods = aggregate_for_player(defender, "on_defense_inside", state)
        pct += post_mods.opp_inside_fg_pct

    # Fatigue penalty
    if shooter.is_fatigued:
        pct -= t.STAMINA_FATIGUE_PENALTY

    return _clamp(pct, t.FG_PCT_FLOOR, t.FG_PCT_CEIL)


def _pick_assist_man(
    offense: TeamInGame,
    shooter: PlayerInGame,
    state: GameState,
    rng: random.Random,
) -> PlayerInGame | None:
    """Probabilistically award an assist to a non-shooting teammate."""
    team_mods = aggregate_team_modifiers(offense, state)
    prob = t.ASSIST_PROB_BASE + team_mods.team_assist_rate
    if rng.random() > prob:
        return None
    candidates = [p for p in offense.on_court if p is not shooter]
    if not candidates:
        return None
    # Weight by speed + sp_attack as a proxy for playmaking ability.
    weights = [max(1, p.speed + p.outside) for p in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0]


def _resolve_rebound(
    offense: TeamInGame,
    defense: TeamInGame,
    state: GameState,
    rng: random.Random,
) -> tuple[PlayerInGame, bool]:
    """Return (rebounder, was_offensive_rebound)."""
    def_int = sum(p.interior_d for p in defense.on_court)
    off_int = sum(p.interior_d for p in offense.on_court)
    diff = (def_int - off_int) * t.INTERIOR_D_RATING_WEIGHT
    def_prob = _clamp(t.DEF_REB_BASE + diff, 0.45, 0.95)

    if rng.random() < def_prob:
        candidates = defense.on_court
        was_off = False
    else:
        candidates = offense.on_court
        was_off = True
    weights = [max(1, p.interior_d) for p in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0], was_off


def _drain_stamina(team: TeamInGame, state: GameState) -> None:
    """All on-court players spend stamina; bench rests."""
    for p in team.on_court:
        mult = aggregate_for_player(p, "stamina_drain", state).self_stamina_drain_multiplier
        if mult <= 0:
            mult = 1.0
        p.current_stamina = max(0.0, p.current_stamina - t.STAMINA_DRAIN_PER_POSSESSION * mult)
    for p in team.bench:
        if not p.fouled_out:
            p.current_stamina = min(float(p.max_stamina), p.current_stamina + t.STAMINA_REST_PER_POSSESSION)


def _credit_minutes(team: TeamInGame, seconds: float) -> None:
    minutes = seconds / 60.0
    for p in team.on_court:
        p.minutes += minutes


def _try_steal(
    offense: TeamInGame,
    defense: TeamInGame,
    state: GameState,
    rng: random.Random,
) -> PlayerInGame | None:
    """Pickpocket-style turnover detection (defender perimeter D vs offense)."""
    pickpockets = [
        d for d in defense.on_court
        if aggregate_for_player(d, "on_defense_outside", state).self_steal_rate > 0
    ]
    if not pickpockets:
        return None
    # Best pickpocket on the floor.
    best = max(pickpockets, key=lambda d: aggregate_for_player(d, "on_defense_outside", state).self_steal_rate)
    bonus = aggregate_for_player(best, "on_defense_outside", state).self_steal_rate
    perim_diff = (best.perimeter_d - 80) * 0.001
    if rng.random() < bonus + perim_diff:
        return best
    return None


def _try_block(
    shooter: PlayerInGame,
    defender: PlayerInGame,
    is_outside: bool,
    state: GameState,
    rng: random.Random,
) -> bool:
    """Post Anchor block check. Only inside attempts can be blocked here."""
    if is_outside:
        return False
    block_bonus = aggregate_for_player(defender, "on_defense_inside", state).self_block_rate
    base = (defender.interior_d - shooter.inside) * 0.0015
    return rng.random() < max(0.0, base + block_bonus)


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------
def resolve_possession(state: GameState, rng: random.Random) -> PossessionResult:
    """Resolve one possession; mutate state; return a PossessionResult."""
    offense = state.offense()
    defense = state.defense()

    team_mods = aggregate_team_modifiers(offense, state)
    seconds = _possession_seconds(offense, team_mods, rng)

    # Don't bleed past the quarter boundary; cap and end the quarter cleanly.
    ends_quarter = False
    if seconds >= state.clock_seconds:
        seconds = state.clock_seconds
        ends_quarter = True

    state.clock_seconds = max(0.0, state.clock_seconds - seconds)
    state.possessions_played += 1
    _credit_minutes(state.home, seconds)
    _credit_minutes(state.away, seconds)

    description = ""
    points_scored = 0
    is_dead_ball = ends_quarter

    # --- Steal check (turnover before the shot) -----------------------------
    thief = _try_steal(offense, defense, state, rng)
    base_to_prob = t.TURNOVER_BASE_PROB + team_mods.team_turnover_rate
    if thief is not None or rng.random() < base_to_prob:
        # Pick the offensive ball-handler (highest USG candidate) as turnover credit
        loser = _pick_shooter(offense, state, rng)
        loser.turnovers += 1
        loser.possessions_used += 1
        if thief is not None:
            thief.steals += 1
            description = f"STEAL by {thief.name} from {loser.name}"
        else:
            description = f"TURNOVER by {loser.name}"
        _drain_stamina(state.home, state)
        _drain_stamina(state.away, state)
        state.flip_possession()
        return PossessionResult(seconds, 0, True, ends_quarter, description)

    # --- Shot setup ---------------------------------------------------------
    shooter = _pick_shooter(offense, state, rng)
    defender = _pick_defender(defense, shooter, rng)
    is_outside = _is_outside_shot(shooter, rng)
    shooter.possessions_used += 1

    # --- Block check (interior only) ----------------------------------------
    if _try_block(shooter, defender, is_outside, state, rng):
        defender.blocks += 1
        shooter.fg_attempted += 1  # blocked attempts still count as attempts
        description = f"BLOCK by {defender.name} on {shooter.name}"
        rebounder, was_off = _resolve_rebound(offense, defense, state, rng)
        rebounder.rebounds += 1
        if was_off:
            description += f"; OFF REB by {rebounder.name}"
            is_dead_ball = False  # offense keeps possession
        else:
            description += f"; DEF REB by {rebounder.name}"
            state.flip_possession()
            is_dead_ball = True
        _drain_stamina(state.home, state)
        _drain_stamina(state.away, state)
        return PossessionResult(seconds, 0, is_dead_ball, ends_quarter, description)

    # --- Foul on the shot? -------------------------------------------------
    if rng.random() < t.SHOOTING_FOUL_PROB:
        defender.fouls += 1
        attempts = t.THREE_PT_VALUE if is_outside else t.TWO_PT_VALUE
        for _ in range(attempts):
            shooter.ft_attempted += 1
            if rng.random() < t.FT_PCT_BASE:
                shooter.ft_made += 1
                shooter.points += 1
                points_scored += 1
        offense.score += points_scored
        description = f"FOUL on {defender.name}; {shooter.name} hits {points_scored}/{attempts} FTs"
        _drain_stamina(state.home, state)
        _drain_stamina(state.away, state)
        state.flip_possession()
        return PossessionResult(seconds, points_scored, True, ends_quarter, description)

    # --- Resolve the shot ---------------------------------------------------
    pct = _shot_pct(shooter, defender, is_outside, state, rng)
    shooter.fg_attempted += 1
    if is_outside:
        shooter.three_attempted += 1

    if rng.random() < pct:
        # Made it
        shooter.fg_made += 1
        if is_outside:
            shooter.three_made += 1
            shooter.points += t.THREE_PT_VALUE
            points_scored = t.THREE_PT_VALUE
        else:
            shooter.points += t.TWO_PT_VALUE
            points_scored = t.TWO_PT_VALUE
        offense.score += points_scored

        # Possible AND-1
        if rng.random() < t.AND_ONE_PROB:
            defender.fouls += 1
            shooter.ft_attempted += 1
            if rng.random() < t.FT_PCT_BASE:
                shooter.ft_made += 1
                shooter.points += 1
                offense.score += 1
                points_scored += 1

        # Assist credit?
        passer = _pick_assist_man(offense, shooter, state, rng)
        if passer is not None:
            passer.assists += 1

        description = f"{shooter.name} {'3PT' if is_outside else '2PT'} +{points_scored}"
        is_dead_ball = True
        _drain_stamina(state.home, state)
        _drain_stamina(state.away, state)
        state.flip_possession()
        return PossessionResult(seconds, points_scored, True, ends_quarter, description)

    # --- Missed shot → rebound battle ---------------------------------------
    rebounder, was_off = _resolve_rebound(offense, defense, state, rng)
    rebounder.rebounds += 1
    description = f"{shooter.name} miss ({'3PT' if is_outside else '2PT'}); "
    if was_off:
        description += f"OFF REB by {rebounder.name}"
        is_dead_ball = False
    else:
        description += f"DEF REB by {rebounder.name}"
        state.flip_possession()
        is_dead_ball = True

    _drain_stamina(state.home, state)
    _drain_stamina(state.away, state)
    return PossessionResult(seconds, 0, is_dead_ball, ends_quarter, description)

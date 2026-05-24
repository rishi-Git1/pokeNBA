"""Aggregates badge effects into a flat dict of multipliers/additions.

The simulation engine never reads ``abilities_db.json`` directly; it asks this
module for an aggregated ``Modifiers`` snapshot for a given trigger context.
That keeps the possession resolver clean — every badge contribution is rolled
up once per resolution.

Effect keys (all optional):
    self_inside_fg_pct, self_outside_fg_pct       → additive shifts
    self_usage_rate                               → additive USG% bias
    self_steal_rate, self_block_rate              → additive
    self_rebound_rate                             → additive
    self_stamina_drain_multiplier                 → multiplicative
    opp_inside_fg_pct, opp_outside_fg_pct         → additive (defender side)
    opp_usage_rate, opp_turnover_rate             → additive (defender side)
    team_pace, team_assist_rate, team_turnover_rate → team-wide
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.core.badges import badge_effects, badge_trigger
from backend.sim.state import GameState, PlayerInGame, TeamInGame


@dataclass(slots=True)
class Modifiers:
    self_inside_fg_pct: float = 0.0
    self_outside_fg_pct: float = 0.0
    self_usage_rate: float = 0.0
    self_steal_rate: float = 0.0
    self_block_rate: float = 0.0
    self_rebound_rate: float = 0.0
    self_stamina_drain_multiplier: float = 1.0
    opp_inside_fg_pct: float = 0.0
    opp_outside_fg_pct: float = 0.0
    opp_usage_rate: float = 0.0
    opp_turnover_rate: float = 0.0
    team_pace: float = 1.0
    team_assist_rate: float = 0.0
    team_turnover_rate: float = 0.0

    def absorb(self, effects: dict[str, float]) -> None:
        """Fold a single badge's effects into this aggregate."""
        for key, value in effects.items():
            if key == "self_stamina_drain_multiplier" or key == "team_pace":
                # multiplicative
                cur = getattr(self, key)
                setattr(self, key, cur * value)
            else:
                cur = getattr(self, key, 0.0)
                setattr(self, key, cur + value)


def _badge_active(badge: str, trigger_ctx: str) -> bool:
    """Does this badge fire for the current possession context?"""
    trig = badge_trigger(badge)
    if trig in ("always", "none"):
        return trig == "always"
    return trig == trigger_ctx


def aggregate_for_player(
    player: PlayerInGame,
    trigger_ctx: str,
    state: GameState | None = None,
) -> Modifiers:
    """Sum a single player's *self_/team_* badge contributions.

    ``trigger_ctx`` is one of: ``"on_shot_inside"``, ``"on_shot_outside"``,
    ``"after_made_shot"``, ``"4th_quarter"``, ``"stamina_drain"``,
    ``"on_defense_inside"``, ``"on_defense_outside"``.
    """
    mods = Modifiers()
    fires = _badge_active(player.badge, trigger_ctx)
    if not fires and badge_trigger(player.badge) == "4th_quarter" and state and state.is_clutch():
        fires = True
    if fires:
        mods.absorb(badge_effects(player.badge))
    return mods


def aggregate_team_modifiers(team: TeamInGame, state: GameState) -> Modifiers:
    """Aggregate every on-court player's ``team_*`` badge contributions."""
    mods = Modifiers()
    for p in team.on_court:
        # Always-on team-wide badges (Floor General, Fast Break Threat, etc.)
        if badge_trigger(p.badge) == "always":
            effects = badge_effects(p.badge)
            mods.absorb({k: v for k, v in effects.items() if k.startswith("team_")})
    return mods

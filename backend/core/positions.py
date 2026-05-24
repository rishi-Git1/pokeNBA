"""Derive a basketball position from a Pokémon's 6 base stats.

Heuristic, not a science:
- C  : huge HP + Defense, slow Speed (Snorlax, Steelix, Rhyperior)
- PF : high Attack + Defense, mid Speed (Machamp, Tyranitar)
- SF : balanced offense + defense, mid speed (Arcanine, Lucario)
- SG : high Sp.Attack + Speed (Alakazam, Gengar, Greninja)
- PG : top-tier Speed, ball-mover (Jolteon, Crobat, Dragapult)

Each candidate gets a weighted score; highest wins. Weights were tuned against
the curated minidex so that Snorlax → C, Tyranitar → PF, Arcanine → SF,
Alakazam → SG, Crobat → PG.
"""
from __future__ import annotations

from backend.models.player import Position


def derive_position(
    *,
    hp: int,
    attack: int,
    defense: int,
    sp_attack: int,
    sp_defense: int,
    speed: int,
) -> Position:
    scores: dict[Position, float] = {
        Position.C:  1.5 * hp + 1.5 * defense + 0.5 * sp_defense - 0.7 * speed,
        Position.PF: 0.6 * hp + 1.5 * attack + 1.0 * defense - 0.5 * speed,
        Position.SF: 0.8 * attack + 0.7 * sp_attack + 0.5 * defense + 0.5 * sp_defense + 0.4 * speed,
        Position.SG: 1.4 * sp_attack + 1.0 * speed + 0.3 * sp_defense,
        # PG is the pure speed archetype. Heavy speed weighting + bigman penalty
        # so Crobat / Jolteon / Dragapult class beat out the SG slot.
        Position.PG: 3.0 * speed - 0.4 * hp - 0.4 * defense - 0.4 * attack,
    }
    return max(scores, key=scores.get)

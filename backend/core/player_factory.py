"""Shared player construction logic.

Both the seeder (rookie pool) and the aging pipeline (regens) call into this
module. Putting it here keeps a single source of truth for stat math, badge
mapping, position derivation, and career meta defaults.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from functools import lru_cache

from backend.core.badges import map_ability_to_badge
from backend.core.config import settings
from backend.core.positions import derive_position
from backend.models import Player


# ----------------------------------------------------------------------------
# StatBlock: tiny helper around the 6 base stats
# ----------------------------------------------------------------------------
@dataclass(slots=True)
class StatBlock:
    hp: int
    attack: int
    defense: int
    sp_attack: int
    sp_defense: int
    speed: int

    @property
    def bst(self) -> int:
        return self.hp + self.attack + self.defense + self.sp_attack + self.sp_defense + self.speed

    def varied(self, pct: float, rng: random.Random) -> "StatBlock":
        """Return a new StatBlock with each stat jittered by ±pct (clamped >=1)."""
        def jitter(value: int) -> int:
            delta = rng.uniform(-pct, pct)
            return max(1, int(round(value * (1.0 + delta))))
        return StatBlock(
            hp=jitter(self.hp),
            attack=jitter(self.attack),
            defense=jitter(self.defense),
            sp_attack=jitter(self.sp_attack),
            sp_defense=jitter(self.sp_defense),
            speed=jitter(self.speed),
        )


def roman(n: int) -> str:
    """Roman-numeral helper for clone/regen suffixes (covers 1-39 cleanly)."""
    table = [(40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out: list[str] = []
    for value, symbol in table:
        while n >= value:
            out.append(symbol)
            n -= value
    return "".join(out)


# ----------------------------------------------------------------------------
# Minidex loader (cached)
# ----------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_minidex() -> dict[int, dict]:
    """All Pokémon entries from the minidex, keyed by pokedex_id."""
    with settings.minidex_path.open(encoding="utf-8") as f:
        data = json.load(f)
    return {entry["id"]: entry for entry in data["pokemon"]}


# ----------------------------------------------------------------------------
# Player builder
# ----------------------------------------------------------------------------
def build_player(
    *,
    pokedex_id: int,
    species: str,
    name: str,
    stats: StatBlock,
    primary_ability: str,
    generation: int,
    rng: random.Random,
    age: int | None = None,
    career_length: int | None = None,
    seasons_played: int | None = None,
    is_regen: bool | None = None,
) -> Player:
    """Build a fresh ORM ``Player`` row.

    All career meta has sensible defaults; pass explicit values for regens
    (which should always be ``age=rookie_min_age``, ``seasons_played=0``).
    """
    badge = map_ability_to_badge(primary_ability)
    position = derive_position(
        hp=stats.hp,
        attack=stats.attack,
        defense=stats.defense,
        sp_attack=stats.sp_attack,
        sp_defense=stats.sp_defense,
        speed=stats.speed,
    )
    if age is None:
        age = rng.randint(settings.rookie_min_age, settings.rookie_max_age + 8)
    if career_length is None:
        career_length = rng.randint(settings.career_length_min, settings.career_length_max)
    if seasons_played is None:
        seasons_played = max(0, age - settings.rookie_min_age - rng.randint(0, 3))
    if is_regen is None:
        is_regen = generation > 1

    return Player(
        pokedex_id=pokedex_id,
        species=species,
        name=name,
        base_hp=stats.hp,
        base_attack=stats.attack,
        base_defense=stats.defense,
        base_sp_attack=stats.sp_attack,
        base_sp_defense=stats.sp_defense,
        base_speed=stats.speed,
        cur_hp=stats.hp,
        cur_attack=stats.attack,
        cur_defense=stats.defense,
        cur_sp_attack=stats.sp_attack,
        cur_sp_defense=stats.sp_defense,
        cur_speed=stats.speed,
        bst=stats.bst,
        ability_name=primary_ability,
        badge=badge,
        age=age,
        seasons_played=seasons_played,
        career_length=career_length,
        is_retired=False,
        is_regen=is_regen,
        generation=generation,
        position=position,
        team_id=None,
    )


def build_regen(
    *,
    retiree: Player,
    next_generation: int,
    rng: random.Random,
) -> Player:
    """Build a same-species rookie regen with ±10% stat variance.

    Reads canonical base stats from the minidex when available; falls back to
    the retiree's own base stats so the pipeline still works for any custom
    Pokémon added at runtime.
    """
    minidex = load_minidex()
    base_entry = minidex.get(retiree.pokedex_id)
    if base_entry is not None:
        base_stats = StatBlock(**base_entry["stats"])
        ability = base_entry["primary_ability"]
    else:
        base_stats = StatBlock(
            hp=retiree.base_hp,
            attack=retiree.base_attack,
            defense=retiree.base_defense,
            sp_attack=retiree.base_sp_attack,
            sp_defense=retiree.base_sp_defense,
            speed=retiree.base_speed,
        )
        ability = retiree.ability_name

    varied = base_stats.varied(settings.regen_stat_variance, rng)
    return build_player(
        pokedex_id=retiree.pokedex_id,
        species=retiree.species,
        name=f"{retiree.species} {roman(next_generation)}",
        stats=varied,
        primary_ability=ability,
        generation=next_generation,
        rng=rng,
        age=settings.rookie_min_age,
        seasons_played=0,
        is_regen=True,
    )

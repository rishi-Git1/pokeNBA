"""Pydantic schemas for player payloads."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backend.models.player import Position


class PlayerInjuryStatus(BaseModel):
    is_injured: bool = False
    games_remaining: int = 0
    stint_games_total: int = 0
    season_injury_count: int = 0


class PlayerSummary(BaseModel):
    """Lightweight player blob used in roster lists."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    species: str
    pokedex_id: int
    position: Position
    bst: int
    effective_bst: int
    badge: str
    age: int
    sprite_url: str
    artwork_url: str
    team_id: int | None = None
    on_rookie_deal: bool = False
    rookie_seasons_remaining: int = 0
    injury: PlayerInjuryStatus = PlayerInjuryStatus()


class PlayerOut(PlayerSummary):
    """Full player detail."""
    ability_name: str
    seasons_played: int
    career_length: int
    is_retired: bool
    is_regen: bool
    generation: int

    base_hp: int
    base_attack: int
    base_defense: int
    base_sp_attack: int
    base_sp_defense: int
    base_speed: int

    cur_hp: int
    cur_attack: int
    cur_defense: int
    cur_sp_attack: int
    cur_sp_defense: int
    cur_speed: int

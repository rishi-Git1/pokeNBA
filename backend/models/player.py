"""Player ORM model.

A Player is the basketball-game incarnation of a single Pokémon. The 6 base
stats are stored verbatim from the minidex; ``bst`` is materialized so the cap
math doesn't recompute on every read. The mapped basketball Badge is also
stored so the simulation engine can lookup modifiers without re-resolving the
ability string at runtime.
"""
from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core import sprites
from backend.database import Base

if TYPE_CHECKING:
    from backend.models.box_score import BoxScore
    from backend.models.team import Team


class Position(str, enum.Enum):
    """Basketball position, derived from stat distribution at draft time."""
    PG = "PG"
    SG = "SG"
    SF = "SF"
    PF = "PF"
    C = "C"


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # --- Pokémon identity ---
    pokedex_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    species: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Display name. Regens append a generation suffix (e.g. "Charizard II").
    name: Mapped[str] = mapped_column(String(96), nullable=False)

    # --- 6 base stats (raw, unmodified by aging/regen variance) ---
    base_hp: Mapped[int] = mapped_column(Integer, nullable=False)
    base_attack: Mapped[int] = mapped_column(Integer, nullable=False)
    base_defense: Mapped[int] = mapped_column(Integer, nullable=False)
    base_sp_attack: Mapped[int] = mapped_column(Integer, nullable=False)
    base_sp_defense: Mapped[int] = mapped_column(Integer, nullable=False)
    base_speed: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- Current effective stats (after aging decay applied each season) ---
    cur_hp: Mapped[int] = mapped_column(Integer, nullable=False)
    cur_attack: Mapped[int] = mapped_column(Integer, nullable=False)
    cur_defense: Mapped[int] = mapped_column(Integer, nullable=False)
    cur_sp_attack: Mapped[int] = mapped_column(Integer, nullable=False)
    cur_sp_defense: Mapped[int] = mapped_column(Integer, nullable=False)
    cur_speed: Mapped[int] = mapped_column(Integer, nullable=False)

    bst: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # = sum of base stats; salary

    # --- Ability / Badge ---
    ability_name: Mapped[str] = mapped_column(String(48), nullable=False)
    badge: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # --- Career meta ---
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    seasons_played: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    career_length: Mapped[int] = mapped_column(Integer, nullable=False)
    is_retired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_regen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1 = original, 2+ = regens

    # --- Position (derived from stat distribution; stored for fast queries) ---
    position: Mapped[Position] = mapped_column(Enum(Position), nullable=False)

    # --- Team membership (NULL = free agent / draft pool) ---
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)

    # --- Rookie deal (set at draft time, decremented by aging pipeline) ---
    # Counts half against the cap while ``rookie_seasons_remaining > 0``.
    on_rookie_deal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rookie_seasons_remaining: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    drafted_pick_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drafted_season: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Set when a player is cut while injured; halves stats on next signing.
    injury_penalty_pending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    team: Mapped["Team | None"] = relationship(back_populates="players", foreign_keys=[team_id])
    box_scores: Mapped[list["BoxScore"]] = relationship(back_populates="player")

    # ------------------------------------------------------------------
    # Sprite URLs (computed; no DB columns needed)
    # ------------------------------------------------------------------
    @property
    def sprite_url(self) -> str:
        """96x96 pixel sprite — fast to load, perfect for roster grids."""
        return sprites.front_default(self.pokedex_id)

    @property
    def artwork_url(self) -> str:
        """High-resolution official artwork — used on player detail pages."""
        return sprites.official_artwork(self.pokedex_id)

    # ------------------------------------------------------------------
    # Cap math: rookies count for half-BST during their first 3 seasons.
    # ------------------------------------------------------------------
    @property
    def is_rookie_contract_active(self) -> bool:
        return bool(self.on_rookie_deal) and self.rookie_seasons_remaining > 0

    @property
    def effective_bst(self) -> int:
        """BST that counts against the cap; halved while a rookie deal is live."""
        return self.bst // 2 if self.is_rookie_contract_active else self.bst

    # ------------------------------------------------------------------
    # Convenience accessors used by the simulation engine
    # ------------------------------------------------------------------
    @property
    def inside_rating(self) -> int:
        """Attack drives finishing at the rim."""
        return self.cur_attack

    @property
    def outside_rating(self) -> int:
        """Sp. Attack drives perimeter / 3PT shooting."""
        return self.cur_sp_attack

    @property
    def interior_d_rating(self) -> int:
        """Defense → blocks/rebounds."""
        return self.cur_defense

    @property
    def perimeter_d_rating(self) -> int:
        """Sp. Defense → steals/contests."""
        return self.cur_sp_defense

    @property
    def stamina_pool(self) -> int:
        """HP → minutes endurance."""
        return self.cur_hp

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Player {self.name} [{self.position.value}] BST={self.bst} {self.badge}>"

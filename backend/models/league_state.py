"""League-wide state machine: which phase the league is in.

There's only ever one row in this table (id=1). Every server endpoint that
mutates league state pivots on the ``phase`` column.
"""
from __future__ import annotations

import enum

from sqlalchemy import Boolean, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Phase(str, enum.Enum):
    """Where the league is in the annual cycle."""
    REGULAR_SEASON = "regular_season"  # 82-game schedule actively being simmed
    PLAYOFFS       = "playoffs"        # bracket up; sim by game or by round
    DRAFT          = "draft"           # rookie pool open, picks being made
    PRE_SEASON     = "pre_season"      # awaiting "Start Next Season" click


class LeagueState(Base):
    __tablename__ = "league_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    current_season: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    phase: Mapped[Phase] = mapped_column(
        Enum(Phase, name="league_phase"),
        default=Phase.REGULAR_SEASON,
        nullable=False,
    )

    # Dynamic cap that grows season-over-season (5–12% on each transition).
    bst_cap: Mapped[int] = mapped_column(Integer, nullable=False)

    # Hall-of-fame trail
    champion_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id"), nullable=True
    )
    last_champion_season: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Draft progress (set when phase=DRAFT)
    draft_current_pick: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    draft_total_picks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LeagueState season={self.current_season} phase={self.phase.value} cap={self.bst_cap}>"

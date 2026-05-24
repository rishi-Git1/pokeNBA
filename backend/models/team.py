"""Team ORM model. The 30 franchises that own rosters and pick draft picks."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

if TYPE_CHECKING:
    from backend.models.box_score import BoxScore
    from backend.models.draft_pick import DraftPick
    from backend.models.player import Player


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    abbreviation: Mapped[str] = mapped_column(String(4), unique=True, nullable=False)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    conference: Mapped[str] = mapped_column(String(8), nullable=False)  # "East" / "West"
    division: Mapped[str] = mapped_column(String(16), nullable=False)

    # Cached season record (rebuilt by the macro engine each game day)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    players: Mapped[list["Player"]] = relationship(
        back_populates="team",
        foreign_keys="Player.team_id",
        cascade="save-update, merge",
    )
    box_scores: Mapped[list["BoxScore"]] = relationship(back_populates="team")
    draft_picks: Mapped[list["DraftPick"]] = relationship(
        back_populates="owning_team",
        foreign_keys="DraftPick.owning_team_id",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Team {self.abbreviation} ({self.city} {self.name})>"

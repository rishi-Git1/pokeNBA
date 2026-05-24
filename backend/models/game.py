"""Game ORM model. One row per scheduled / completed matchup."""
from __future__ import annotations

from datetime import date as date_type
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

if TYPE_CHECKING:
    from backend.models.box_score import BoxScore
    from backend.models.team import Team


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    game_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)

    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)

    home_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    away_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    overtime_periods: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Playoff games tag back to a Series row + sequence number (1..7).
    # NULL = regular-season game.
    series_id: Mapped[int | None] = mapped_column(
        ForeignKey("series.id"), nullable=True, index=True
    )
    series_game_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_playoff: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    home_team: Mapped["Team"] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped["Team"] = relationship(foreign_keys=[away_team_id])
    box_scores: Mapped[list["BoxScore"]] = relationship(back_populates="game")

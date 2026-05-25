"""Season injury state and event log for players."""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class PlayerSeasonInjury(Base):
    """Current injury state for one player in one season."""

    __tablename__ = "player_season_injuries"
    __table_args__ = (
        UniqueConstraint("season", "player_id", name="uq_player_season_injury"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)

    injury_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    games_remaining: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stint_games_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PlayerInjuryEvent(Base):
    """Historical injury log entry for a season."""

    __tablename__ = "player_injury_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)

    phase: Mapped[str] = mapped_column(String(24), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)  # injured | recovered | cleared
    games_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

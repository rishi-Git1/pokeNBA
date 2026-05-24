"""BoxScore ORM model.

One row per (game, player). The macro engine flushes these via a single
``executemany`` per simulated day to keep the SQLite write path tight.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

if TYPE_CHECKING:
    from backend.models.game import Game
    from backend.models.player import Player
    from backend.models.team import Team


class BoxScore(Base):
    __tablename__ = "box_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    is_starter: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    minutes: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Counting stats
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rebounds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assists: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    steals: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    turnovers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fouls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Shooting splits
    fg_made: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fg_attempted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    three_made: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    three_attempted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ft_made: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ft_attempted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Advanced
    plus_minus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    game: Mapped["Game"] = relationship(back_populates="box_scores")
    player: Mapped["Player"] = relationship(back_populates="box_scores")
    team: Mapped["Team"] = relationship(back_populates="box_scores")

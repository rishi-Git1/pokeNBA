"""Playoff injury state — tracks who is out and how many times they've been hurt.

One row per player per playoff season. ``injury_count`` drives the stacking
+5% roll penalty; ``games_remaining`` is how many more playoff games they sit.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class PlayoffPlayerState(Base):
    __tablename__ = "playoff_player_states"
    __table_args__ = (
        UniqueConstraint("season", "player_id", name="uq_playoff_player_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)

    # Times this player has been injured this postseason (drives stacking odds).
    injury_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Playoff games still to sit out (0 = available).
    games_remaining: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<PlayoffPlayerState s{self.season} pid={self.player_id} "
            f"inj={self.injury_count} out={self.games_remaining}>"
        )

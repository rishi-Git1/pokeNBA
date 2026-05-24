"""Playoff series. One row per matchup across the bracket.

Best-of-7 with 1-8 seeding per conference. The bracket is materialized as
soon as the regular season ends; subsequent rounds are created lazily as
each lower-round series resolves.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

if TYPE_CHECKING:
    from backend.models.team import Team


class Series(Base):
    __tablename__ = "series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # 1=first round, 2=conf semis, 3=conf finals, 4=NBA Finals
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    bracket: Mapped[str] = mapped_column(String(8), nullable=False)  # "East" / "West" / "Finals"
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-based within (round, bracket)

    # Seed numbers (1-8) within the conference. For Finals, both are 0.
    high_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    low_seed: Mapped[int] = mapped_column(Integer, nullable=False)

    high_seed_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    low_seed_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)

    high_seed_wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    low_seed_wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    winner_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id"), nullable=True
    )

    high_seed_team: Mapped["Team"] = relationship(foreign_keys=[high_seed_team_id])
    low_seed_team:  Mapped["Team"] = relationship(foreign_keys=[low_seed_team_id])
    winner_team:    Mapped["Team | None"] = relationship(foreign_keys=[winner_team_id])

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Series s{self.season} R{self.round} {self.bracket}#{self.slot_index} "
            f"({self.high_seed}) vs ({self.low_seed}) "
            f"{self.high_seed_wins}-{self.low_seed_wins}>"
        )

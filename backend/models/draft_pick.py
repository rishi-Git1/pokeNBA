"""DraftPick ORM model. Tradeable assets alongside player BST."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

if TYPE_CHECKING:
    from backend.models.team import Team


class DraftPick(Base):
    __tablename__ = "draft_picks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    round: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 or 2
    pick_number: Mapped[int] = mapped_column(Integer, nullable=True)  # set at lottery time

    # Who originally owned this pick (lottery odds tied to this team's record)
    original_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    # Who currently owns it (transfers when traded)
    owning_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)

    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    original_team: Mapped["Team"] = relationship(foreign_keys=[original_team_id])
    owning_team: Mapped["Team"] = relationship(
        back_populates="draft_picks",
        foreign_keys=[owning_team_id],
    )

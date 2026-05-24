"""Pydantic schemas for team payloads."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, computed_field

from backend.schemas.player import PlayerSummary


class TeamSummary(BaseModel):
    """Lightweight team blob used in standings/lists."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    abbreviation: str
    city: str
    conference: str
    division: str
    wins: int
    losses: int


class TeamOut(TeamSummary):
    """Full team detail with roster and cap info."""
    bst_cap: int
    bst_used: int
    roster: list[PlayerSummary]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cap_room(self) -> int:
        return self.bst_cap - self.bst_used


class StandingsRow(TeamSummary):
    """Standings row with derived win-percentage."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def games_played(self) -> int:
        return self.wins + self.losses

    @computed_field  # type: ignore[prop-decorator]
    @property
    def win_pct(self) -> float:
        gp = self.wins + self.losses
        return round(self.wins / gp, 3) if gp else 0.0

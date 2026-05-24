"""Pydantic schemas for games & box scores."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class GameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    season: int
    game_date: date
    home_team_id: int
    away_team_id: int
    home_score: int
    away_score: int
    overtime_periods: int
    is_completed: bool


class BoxScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    player_id: int
    team_id: int
    season: int
    is_starter: bool
    minutes: float
    points: int
    rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    fouls: int
    fg_made: int
    fg_attempted: int
    three_made: int
    three_attempted: int
    ft_made: int
    ft_attempted: int
    plus_minus: int
    usage_rate: float


class DayResultOut(BaseModel):
    sim_date: date
    season: int
    games_played: int
    box_scores_written: int
    games: list[GameOut]

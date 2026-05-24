"""Pure-Python sim-time data structures, decoupled from SQLAlchemy.

A ``PlayerInGame`` is built once at game start from an ORM ``Player``, lives in
memory through all 4 quarters, and is serialized back to a ``BoxScore`` row at
flush time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.models.player import Player, Position


@dataclass(slots=True)
class PlayerInGame:
    """One player's live state inside a single game."""

    # Identity
    player_id: int
    team_id: int
    name: str
    position: Position
    badge: str

    # Snapshot ratings (taken at tip-off; aging happens between games)
    inside: int           # Attack          → finishing
    outside: int          # Sp. Attack      → shooting
    interior_d: int       # Defense         → rebounding/blocks
    perimeter_d: int      # Sp. Defense     → steals/contests
    speed: int
    max_stamina: int      # = HP

    # Live state
    on_court: bool = False
    is_starter: bool = False
    current_stamina: float = 0.0
    fouls: int = 0
    fouled_out: bool = False
    minutes: float = 0.0

    # Box-score accumulators
    points: int = 0
    rebounds: int = 0
    assists: int = 0
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    fg_made: int = 0
    fg_attempted: int = 0
    three_made: int = 0
    three_attempted: int = 0
    ft_made: int = 0
    ft_attempted: int = 0
    plus_minus: int = 0
    possessions_used: int = 0  # for usage% calc

    # ------------------------------------------------------------------
    @classmethod
    def from_orm(cls, p: Player) -> "PlayerInGame":
        return cls(
            player_id=p.id,
            team_id=p.team_id or 0,
            name=p.name,
            position=p.position,
            badge=p.badge,
            inside=p.cur_attack,
            outside=p.cur_sp_attack,
            interior_d=p.cur_defense,
            perimeter_d=p.cur_sp_defense,
            speed=p.cur_speed,
            max_stamina=p.cur_hp,
            current_stamina=float(p.cur_hp),
        )

    # Convenience -------------------------------------------------------
    @property
    def stamina_pct(self) -> float:
        if self.max_stamina <= 0:
            return 0.0
        return self.current_stamina / self.max_stamina

    @property
    def is_fatigued(self) -> bool:
        from backend.sim.tuning import STAMINA_FATIGUE_THRESHOLD
        return self.stamina_pct < STAMINA_FATIGUE_THRESHOLD


@dataclass(slots=True)
class TeamInGame:
    """A team's live state inside a single game."""

    team_id: int
    abbreviation: str
    on_court: list[PlayerInGame]                                      # always len 5
    bench: list[PlayerInGame]                                         # everyone else
    score: int = 0
    fouls_quarter: int = 0       # team fouls in current quarter (for bonus)
    timeouts_remaining: int = 7

    # Resolved on demand --------------------------------------------------
    @property
    def all_players(self) -> list[PlayerInGame]:
        return self.on_court + self.bench

    @property
    def avg_speed_on_court(self) -> float:
        return sum(p.speed for p in self.on_court) / max(1, len(self.on_court))


@dataclass(slots=True)
class GameState:
    """Game-wide live state shared by both engines."""

    home: TeamInGame
    away: TeamInGame
    quarter: int = 1
    clock_seconds: float = 720.0
    possession_team_id: int | None = None  # which team currently has the ball
    possessions_played: int = 0
    log: list[str] = field(default_factory=list)  # optional play-by-play

    # ------------------------------------------------------------------
    def offense(self) -> TeamInGame:
        if self.possession_team_id == self.home.team_id:
            return self.home
        return self.away

    def defense(self) -> TeamInGame:
        if self.possession_team_id == self.home.team_id:
            return self.away
        return self.home

    def flip_possession(self) -> None:
        if self.possession_team_id == self.home.team_id:
            self.possession_team_id = self.away.team_id
        else:
            self.possession_team_id = self.home.team_id

    def is_clutch(self) -> bool:
        """4th quarter and within 5 points triggers Clutch Performer badge."""
        return self.quarter >= 4 and abs(self.home.score - self.away.score) <= 5

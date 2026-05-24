"""Optional parallel game execution using ``ProcessPoolExecutor``.

Each worker runs one game start-to-finish on a serialized roster snapshot.
The main process keeps the SQLAlchemy session and only walks the worker
results to update Game/Team rows + bulk-insert box scores.

Notes for Windows users:
- ``spawn`` is the only start method on Windows; that means each worker
  re-imports our backend modules. ``@lru_cache`` makes badge JSON loading
  cheap so this isn't a bottleneck.
- Workers must receive *only* picklable objects. We send already-built
  ``PlayerInGame`` dataclasses (slotted, picklable) — never ORM Players.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from backend.sim.game import GameResult, _build_team_from_pigs
from backend.sim.state import PlayerInGame
from backend.sim.game import run_prepared_game


@dataclass(slots=True)
class GameJob:
    """Picklable description of a single game to be simulated in a worker."""
    game_id: int
    season: int
    home_id: int
    home_abbr: str
    home_pigs: list[PlayerInGame]
    away_id: int
    away_abbr: str
    away_pigs: list[PlayerInGame]
    seed: int


def _run_one(job: GameJob) -> GameResult:
    """Top-level worker entrypoint (must be picklable, hence module-level)."""
    home = _build_team_from_pigs(job.home_id, job.home_abbr, job.home_pigs)
    away = _build_team_from_pigs(job.away_id, job.away_abbr, job.away_pigs)
    return run_prepared_game(
        game_id=job.game_id,
        season=job.season,
        home=home,
        away=away,
        seed=job.seed,
    )


def run_jobs_in_parallel(jobs: list[GameJob], max_workers: int | None = None) -> list[GameResult]:
    """Run all jobs concurrently and return results in the same order."""
    if not jobs:
        return []
    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(_run_one, jobs))

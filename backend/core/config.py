"""Centralized configuration. Tweak gameplay knobs here, not deep in the engine."""
from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="POKENBA_", extra="ignore")

    # --- Database ---
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'pokenba.db'}"

    # --- League shape ---
    num_teams: int = 30
    roster_size: int = 15
    starters_per_team: int = 5
    fa_buffer: int = 60  # extra free agents when the dex is smaller than the league

    # --- Team GM mode (CPU roster churn) ---
    cpu_gm_move_chance: float = 0.05  # per AI team, per sim day

    # --- Salary cap ---
    # Average fully-evolved BST is ~500. With 15-man rosters, a realistic
    # league cap lands around 7,500. The original spec quoted 2,500 as
    # *illustrative* — bump or override via POKENBA_BST_CAP env var.
    bst_cap: int = 7500
    bst_min_floor: int = 6500  # discourage tanking the cap (must be spent)

    # --- Aging / regens ---
    rookie_min_age: int = 19
    rookie_max_age: int = 22
    career_length_min: int = 6
    career_length_max: int = 14
    regen_stat_variance: float = 0.10  # +/- 10%

    # --- Season ---
    season_games: int = 82
    quarter_length_seconds: int = 720  # 12-minute quarters
    quarters_per_game: int = 4

    # --- Files ---
    minidex_path: Path = DATA_DIR / "pokemon_minidex.json"
    abilities_path: Path = DATA_DIR / "abilities_db.json"


settings = Settings()

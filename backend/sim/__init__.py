"""Simulation engine.

Three nested layers:
- Micro  : ``possession.py`` — single 5v5 possession resolver (RNG + math).
- Mid    : ``rotation.py``   — substitution engine that runs on dead balls.
- Macro  : ``league_day.py`` — runs a day's slate, batch-flushes box scores.

The engine is intentionally **decoupled from SQLAlchemy**: ORM Player rows are
materialized into lightweight ``PlayerInGame`` dataclasses up front, the entire
game runs in pure Python memory, and results are flushed back via a single
``executemany`` per day.
"""

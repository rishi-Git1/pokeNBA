"""Loads ``data/abilities_db.json`` once at import time and exposes lookup helpers.

The contract is intentionally tiny: any string in / any string out. The
simulation engine reads ``BADGE_EFFECTS[badge]`` to apply flat modifiers to the
possession RNG math, and the seed script reads ``map_ability_to_badge(name)``
to assign a badge to each Pokémon.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from backend.core.config import settings

DEFAULT_BADGE = "Neutral"


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    with settings.abilities_path.open(encoding="utf-8") as f:
        return json.load(f)


def all_badges() -> dict[str, dict[str, Any]]:
    """All badge definitions keyed by badge name."""
    return _load()["badges"]


def ability_mapping() -> dict[str, str]:
    """Raw ability_name -> badge_name dict."""
    return _load()["ability_mapping"]


def map_ability_to_badge(ability_name: str) -> str:
    """Resolve a Pokémon ability to its basketball Badge.

    Falls back to ``DEFAULT_BADGE`` for anything not present in the mapping —
    this keeps the seed script bullet-proof if the minidex contains an
    obscure ability we haven't cataloged yet.
    """
    return ability_mapping().get(ability_name, DEFAULT_BADGE)


def badge_effects(badge: str) -> dict[str, float]:
    """Flat numeric modifiers attached to a badge (used by the sim engine)."""
    return all_badges().get(badge, {}).get("effects", {})


def badge_trigger(badge: str) -> str:
    """When the badge fires (e.g. ``always``, ``on_shot_inside``, ``4th_quarter``)."""
    return all_badges().get(badge, {}).get("trigger", "none")

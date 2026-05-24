"""PokeAPI sprite URL helpers.

We never call the live PokeAPI — sprite URLs follow a predictable pattern on
the project's GitHub raw CDN. Frontends load these directly; the backend only
constructs the URLs.

Example::

    front_default(6)        # → ".../sprites/pokemon/6.png"   (Charizard)
    official_artwork(6)     # → ".../other/official-artwork/6.png"
"""
from __future__ import annotations

_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon"


def front_default(pokedex_id: int) -> str:
    """Standard 96x96 front-facing pixel sprite."""
    return f"{_BASE}/{pokedex_id}.png"


def back_default(pokedex_id: int) -> str:
    """Standard 96x96 back-facing pixel sprite."""
    return f"{_BASE}/back/{pokedex_id}.png"


def official_artwork(pokedex_id: int) -> str:
    """High-resolution official artwork (~475x475)."""
    return f"{_BASE}/other/official-artwork/{pokedex_id}.png"


def home_artwork(pokedex_id: int) -> str:
    """Pokémon HOME 3D-render style sprite (~512x512 transparent)."""
    return f"{_BASE}/other/home/{pokedex_id}.png"

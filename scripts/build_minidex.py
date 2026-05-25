"""Build ``data/pokemon_minidex.json`` from PokeAPI.

Includes every fully-evolved Pokémon (evolution-chain leaf nodes) plus
single-stage species that never evolve further. Mid-evolutions and baby
Pokémon are excluded.

Usage::

    python scripts/build_minidex.py

Responses are cached under ``data/pokeapi_cache/`` so re-runs are fast.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "pokeapi_cache"
OUTPUT = ROOT / "data" / "pokemon_minidex.json"
BASE = "https://pokeapi.co/api/v2"

# Be polite to the public API; cache makes re-runs cheap.
REQUEST_DELAY = 0.05
MAX_RETRIES = 4


def _cache_path(url: str) -> Path:
    rel = url.removeprefix(BASE + "/")
    safe = re.sub(r"[^\w.-]", "_", rel)
    return CACHE_DIR / f"{safe}.json"


def _fetch(url: str) -> dict:
    cache_path = _cache_path(url)
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(REQUEST_DELAY)
            req = urllib.request.Request(url, headers={"User-Agent": "pokeNBA-minidex-builder/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data), encoding="utf-8")
            return data
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt + 1 < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(f"Failed to fetch {url}")


def _paginate(resource: str) -> list[dict]:
    url = f"{BASE}/{resource}?limit=2000"
    items: list[dict] = []
    while url:
        page = _fetch(url)
        items.extend(page["results"])
        url = page.get("next")
    return items


def _terminal_species(chain_node: dict, out: set[str]) -> None:
    evolves = chain_node.get("evolves_to") or []
    if not evolves:
        out.add(chain_node["species"]["name"])
        return
    for child in evolves:
        _terminal_species(child, out)


def _english_name(species: dict) -> str:
    for entry in species.get("names", []):
        if entry["language"]["name"] == "en":
            return entry["name"]
    return species["name"].replace("-", " ").title()


def _format_ability(raw: str) -> str:
    # Match existing minidex style: "Sand Rush", "Soul-Heart"
    parts = [p.capitalize() for p in raw.split("-")]
    return "-".join(parts) if raw.count("-") else " ".join(parts)


def _national_dex_id(species: dict) -> int:
    for entry in species.get("pokedex_numbers", []):
        if entry["pokedex"]["name"] == "national":
            return entry["entry_number"]
    return species["id"]


def _primary_ability(pokemon: dict) -> str:
    abilities = sorted(
        (a for a in pokemon.get("abilities", []) if not a.get("is_hidden")),
        key=lambda a: a.get("slot", 99),
    )
    if not abilities:
        hidden = sorted(pokemon.get("abilities", []), key=lambda a: a.get("slot", 99))
        if not hidden:
            return "Neutral"
        return _format_ability(hidden[0]["ability"]["name"])
    return _format_ability(abilities[0]["ability"]["name"])


def _stats(pokemon: dict) -> dict[str, int]:
    by_name = {s["stat"]["name"]: s["base_stat"] for s in pokemon["stats"]}
    return {
        "hp": by_name["hp"],
        "attack": by_name["attack"],
        "defense": by_name["defense"],
        "sp_attack": by_name["special-attack"],
        "sp_defense": by_name["special-defense"],
        "speed": by_name["speed"],
    }


def _default_pokemon_url(species: dict) -> str:
    for variety in species.get("varieties", []):
        if variety.get("is_default"):
            return variety["pokemon"]["url"]
    return species["varieties"][0]["pokemon"]["url"]


def _is_excluded_species(name: str, species: dict) -> bool:
    """Skip non-standard forms we don't want in the league pool."""
    if species.get("is_baby"):
        return True
    # Mega / Gmax / totem / cap forms are not separate evolution-chain leaves,
    # but filter obvious cosmetic duplicates when they appear as species.
    lowered = name.lower()
    if re.search(r"-mega|-gmax|-totem|-cap|-starter|-cosplay|-original|-dusk|-midnight|-dawn|-ultra|-rapid-strike|-single-strike", lowered):
        return True
    return False


def build() -> list[dict]:
    print("Fetching evolution chains…")
    chains = _paginate("evolution-chain")

    terminal: set[str] = set()
    for i, chain_ref in enumerate(chains, 1):
        chain = _fetch(chain_ref["url"])
        _terminal_species(chain["chain"], terminal)
        if i % 100 == 0:
            print(f"  parsed {i}/{len(chains)} chains ({len(terminal)} terminal species)")

    print(f"Found {len(terminal)} terminal species")

    entries: list[dict] = []
    skipped = 0
    for i, name in enumerate(sorted(terminal), 1):
        species = _fetch(f"{BASE}/pokemon-species/{name}")
        if _is_excluded_species(name, species):
            skipped += 1
            continue

        pokemon = _fetch(_default_pokemon_url(species))
        entry = {
            "id": _national_dex_id(species),
            "name": _english_name(species),
            "stats": _stats(pokemon),
            "primary_ability": _primary_ability(pokemon),
        }
        entries.append(entry)
        if i % 50 == 0:
            print(f"  built {i}/{len(terminal)} entries")

    # Stable ordering by national dex id (ties broken by name).
    entries.sort(key=lambda e: (e["id"], e["name"]))

    # Last-resort dedupe if two species share a national dex slot (shouldn't happen).
    seen_ids: set[int] = set()
    deduped: list[dict] = []
    for entry in entries:
        if entry["id"] in seen_ids:
            skipped += 1
            continue
        seen_ids.add(entry["id"])
        deduped.append(entry)

    print(f"Wrote {len(deduped)} Pokémon ({skipped} skipped)")
    return deduped


def main() -> None:
    entries = build()
    payload = {
        "_meta": {
            "description": "Fully-evolved and single-stage Pokémon for pokeNBA league seeding.",
            "source": "Generated from PokeAPI evolution chains via scripts/build_minidex.py",
            "stats_order": ["hp", "attack", "defense", "sp_attack", "sp_defense", "speed"],
            "count": len(entries),
        },
        "pokemon": entries,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {OUTPUT} ({len(entries)} species)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

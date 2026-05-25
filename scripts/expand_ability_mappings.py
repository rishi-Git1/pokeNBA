"""Expand ability→badge mappings and normalize minidex ability names."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ABILITIES_PATH = ROOT / "data" / "abilities_db.json"
MINIDEX_PATH = ROOT / "data" / "pokemon_minidex.json"

_SMALL_WORDS = {"as", "of", "the", "and"}

# Canonical ability name fixes after title-casing PokeAPI slugs.
ALIASES = {
    "Dragons Maw": "Dragon's Maw",
    "Good As Gold": "Good as Gold",
    "Soul Heart": "Soul-Heart",
}

# New mappings for abilities appearing in the full dex.
NEW_MAPPINGS: dict[str, str] = {
    "Aftermath": "Pickpocket",
    "Air Lock": "Lockdown Defender",
    "Anger Shell": "Heat Check",
    "Anticipation": "Floor General",
    "Bad Dreams": "Pickpocket",
    "Battle Armor": "Lockdown Defender",
    "Beads of Ruin": "Glass Cannon",
    "Berserk": "Heat Check",
    "Big Pecks": "Lockdown Defender",
    "Bulletproof": "Lockdown Defender",
    "Cheek Pouch": "Iron Man",
    "Comatose": "Iron Man",
    "Commander": "Floor General",
    "Contrary": "Volume Scorer",
    "Corrosion": "Pickpocket",
    "Cotton Down": "Pickpocket",
    "Cud Chew": "Iron Man",
    "Cursed Body": "Pickpocket",
    "Cute Charm": "Pickpocket",
    "Dancer": "Floor General",
    "Dark Aura": "Floor General",
    "Dazzling": "Lockdown Defender",
    "Disguise": "Iron Man",
    "Dragon's Maw": "Slasher",
    "Drizzle": "Floor General",
    "Drought": "Fast Break Threat",
    "Dry Skin": "Iron Man",
    "Early Bird": "Iron Man",
    "Earth Eater": "Post Anchor",
    "Effect Spore": "Pickpocket",
    "Electric Surge": "Fast Break Threat",
    "Electromorphosis": "Heat Check",
    "Emergency Exit": "Fast Break Threat",
    "Fairy Aura": "Floor General",
    "Flame Body": "Pickpocket",
    "Flower Gift": "Floor General",
    "Flower Veil": "Floor General",
    "Forecast": "Neutral",
    "Forewarn": "Floor General",
    "Full Metal Body": "Lockdown Defender",
    "Fur Coat": "Lockdown Defender",
    "Gluttony": "Neutral",
    "Gooey": "Pickpocket",
    "Grassy Surge": "Fast Break Threat",
    "Gulp Missile": "Sniper",
    "Hadron Engine": "Heat Check",
    "Healer": "Iron Man",
    "Hospitality": "Floor General",
    "Hunger Switch": "Neutral",
    "Hydration": "Iron Man",
    "Hyper Cutter": "Lockdown Defender",
    "Ice Body": "Iron Man",
    "Ice Face": "Iron Man",
    "Illusion": "Neutral",
    "Immunity": "Lockdown Defender",
    "Innards Out": "Glass Cannon",
    "Inner Focus": "Iron Man",
    "Insomnia": "Iron Man",
    "Intrepid Sword": "Volume Scorer",
    "Iron Barbs": "Pickpocket",
    "Justified": "Volume Scorer",
    "Leaf Guard": "Iron Man",
    "Lightning Rod": "Post Anchor",
    "Limber": "Iron Man",
    "Lingering Aroma": "Pickpocket",
    "Liquid Ooze": "Pickpocket",
    "Magma Armor": "Iron Man",
    "Magnet Pull": "Pickpocket",
    "Marvel Scale": "Post Anchor",
    "Merciless": "Heat Check",
    "Misty Surge": "Fast Break Threat",
    "Mold Breaker": "Volume Scorer",
    "Motor Drive": "Fast Break Threat",
    "Multitype": "Neutral",
    "Mummy": "Pickpocket",
    "Mycelium Might": "Floor General",
    "Oblivious": "Lockdown Defender",
    "Opportunist": "Heat Check",
    "Orichalcum Pulse": "Heat Check",
    "Overcoat": "Iron Man",
    "Own Tempo": "Iron Man",
    "Poison Point": "Pickpocket",
    "Poison Puppeteer": "Pickpocket",
    "Power Spot": "Floor General",
    "Pressure": "Lockdown Defender",
    "Prism Armor": "Lockdown Defender",
    "Protosynthesis": "Heat Check",
    "Psychic Surge": "Fast Break Threat",
    "Purifying Salt": "Post Anchor",
    "Quark Drive": "Heat Check",
    "Receiver": "Neutral",
    "Refrigerate": "Slasher",
    "Ripen": "Neutral",
    "Rivalry": "Volume Scorer",
    "Rks System": "Neutral",
    "Rough Skin": "Pickpocket",
    "Sand Force": "Slasher",
    "Sand Spit": "Post Anchor",
    "Sand Stream": "Fast Break Threat",
    "Sand Veil": "Fast Break Threat",
    "Schooling": "Neutral",
    "Scrappy": "Volume Scorer",
    "Seed Sower": "Post Anchor",
    "Serene Grace": "Sniper",
    "Shadow Shield": "Lockdown Defender",
    "Shed Skin": "Iron Man",
    "Shell Armor": "Lockdown Defender",
    "Shield Dust": "Lockdown Defender",
    "Shields Down": "Iron Man",
    "Simple": "Volume Scorer",
    "Slow Start": "Neutral",
    "Snow Cloak": "Fast Break Threat",
    "Snow Warning": "Fast Break Threat",
    "Soundproof": "Lockdown Defender",
    "Stakeout": "Pickpocket",
    "Stance Change": "Neutral",
    "Static": "Pickpocket",
    "Steadfast": "Fast Break Threat",
    "Steam Engine": "Fast Break Threat",
    "Steelworker": "Slasher",
    "Sticky Hold": "Iron Man",
    "Suction Cups": "Lockdown Defender",
    "Supersweet Syrup": "Pickpocket",
    "Sweet Veil": "Floor General",
    "Tablets of Ruin": "Glass Cannon",
    "Tangled Feet": "Lockdown Defender",
    "Tera Shift": "Neutral",
    "Teravolt": "Volume Scorer",
    "Thermal Exchange": "Heat Check",
    "Toxic Chain": "Pickpocket",
    "Toxic Debris": "Pickpocket",
    "Transistor": "Slasher",
    "Truant": "Neutral",
    "Turboblaze": "Volume Scorer",
    "Unnerve": "Lockdown Defender",
    "Unseen Fist": "Slasher",
    "Vessel of Ruin": "Glass Cannon",
    "Victory Star": "Clutch Performer",
    "Vital Spirit": "Iron Man",
    "Wandering Spirit": "Pickpocket",
    "Water Bubble": "Post Anchor",
    "Water Compaction": "Post Anchor",
    "Water Veil": "Iron Man",
    "Weak Armor": "Glass Cannon",
    "Well Baked Body": "Post Anchor",
    "Wind Power": "Fast Break Threat",
    "Wind Rider": "Fast Break Threat",
    "Wonder Guard": "Lockdown Defender",
    "Wonder Skin": "Lockdown Defender",
    "Zero To Hero": "Heat Check",
}


def normalize_ability_name(raw: str) -> str:
    cleaned = " ".join(raw.replace("-", " ").split())
    words = cleaned.split()
    parts: list[str] = []
    for i, word in enumerate(words):
        lower = word.lower()
        if i > 0 and lower in _SMALL_WORDS:
            parts.append(lower)
        else:
            parts.append(lower.capitalize())
    name = " ".join(parts)
    return ALIASES.get(name, name)


def main() -> None:
    data = json.loads(ABILITIES_PATH.read_text(encoding="utf-8"))
    mapping: dict[str, str] = dict(data["ability_mapping"])
    mapping.update(NEW_MAPPINGS)

    valid_badges = set(data["badges"])
    for ability, badge in list(mapping.items()):
        if badge not in valid_badges:
            raise ValueError(f"Unknown badge {badge!r} for ability {ability!r}")

    data["ability_mapping"] = dict(sorted(mapping.items(), key=lambda kv: kv[0].lower()))
    ABILITIES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"ability_mapping: {len(data['ability_mapping'])} entries")

    minidex = json.loads(MINIDEX_PATH.read_text(encoding="utf-8"))
    unmapped = 0
    for entry in minidex["pokemon"]:
        entry["primary_ability"] = normalize_ability_name(entry["primary_ability"])
        if entry["primary_ability"] not in data["ability_mapping"]:
            unmapped += 1

    MINIDEX_PATH.write_text(json.dumps(minidex, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"minidex normalized; unmapped abilities remaining: {unmapped}")


if __name__ == "__main__":
    main()

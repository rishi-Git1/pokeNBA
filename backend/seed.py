"""Database seed script.

Run with::

    python -m backend.seed

Pipeline:
1. Drop and recreate every table.
2. Insert 30 NBA-style franchises (Pokémon-themed mascots).
3. Load ``data/pokemon_minidex.json``; for each species, build one or more
   Player rows (cloning with ±10% variance to inflate the pool to a full
   league + free-agent reserve).
4. Snake-draft players (sorted by BST descending) into the 30 rosters so that
   talent is spread evenly. Leftovers become free agents.
5. Generate two rounds of draft picks for the upcoming season per team.
6. Print a summary table (BST used per team, free-agent count, badge spread).

The script is **idempotent** — re-running it nukes the DB and rebuilds.
"""
from __future__ import annotations

import json
import random
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.player_factory import StatBlock, build_player, roman
from backend.database import SessionLocal, create_all, drop_all
from backend.league.state import reset_state
from backend.models import DraftPick, Player, Team
from backend.sim.schedule import generate_schedule


SEED = 1995  # deterministic league for reproducible scaffolding


# ----------------------------------------------------------------------------
# Franchise definitions (city, mascot, abbreviation, conference, division)
# ----------------------------------------------------------------------------
FRANCHISES: list[tuple[str, str, str, str, str]] = [
    # Eastern Conference - Atlantic
    ("Boston",        "Beedrills",   "BOS", "East", "Atlantic"),
    ("Brooklyn",      "Bisharps",    "BKN", "East", "Atlantic"),
    ("New York",      "Nidokings",   "NYK", "East", "Atlantic"),
    ("Philadelphia",  "Pidgeots",    "PHI", "East", "Atlantic"),
    ("Toronto",       "Tyranitars",  "TOR", "East", "Atlantic"),
    # Eastern Conference - Central
    ("Chicago",       "Charizards",  "CHI", "East", "Central"),
    ("Cleveland",     "Cloysters",   "CLE", "East", "Central"),
    ("Detroit",       "Donphans",    "DET", "East", "Central"),
    ("Indiana",       "Infernapes",  "IND", "East", "Central"),
    ("Milwaukee",     "Magmars",     "MIL", "East", "Central"),
    # Eastern Conference - Southeast
    ("Atlanta",       "Aerodactyls", "ATL", "East", "Southeast"),
    ("Charlotte",     "Cinderaces",  "CHA", "East", "Southeast"),
    ("Miami",         "Milotics",    "MIA", "East", "Southeast"),
    ("Orlando",       "Onixes",      "ORL", "East", "Southeast"),
    ("Washington",    "Whimsicotts", "WAS", "East", "Southeast"),
    # Western Conference - Northwest
    ("Denver",        "Dragonites",  "DEN", "West", "Northwest"),
    ("Minnesota",     "Metagrosses", "MIN", "West", "Northwest"),
    ("Oklahoma City", "Octillerys",  "OKC", "West", "Northwest"),
    ("Portland",      "Pinsirs",     "POR", "West", "Northwest"),
    ("Utah",          "Umbreons",    "UTA", "West", "Northwest"),
    # Western Conference - Pacific
    ("Golden State",  "Greninjas",   "GSW", "West", "Pacific"),
    ("Los Angeles",   "Laprases",    "LAL", "West", "Pacific"),
    ("LA",            "Lucarios",    "LAC", "West", "Pacific"),
    ("Phoenix",       "Pyroars",     "PHX", "West", "Pacific"),
    ("Sacramento",    "Snorlaxes",   "SAC", "West", "Pacific"),
    # Western Conference - Southwest
    ("Dallas",        "Dragapults",  "DAL", "West", "Southwest"),
    ("Houston",       "Houndooms",   "HOU", "West", "Southwest"),
    ("Memphis",       "Machamps",    "MEM", "West", "Southwest"),
    ("New Orleans",   "Ninetales",   "NOP", "West", "Southwest"),
    ("San Antonio",   "Sceptiles",   "SAS", "West", "Southwest"),
]


# ----------------------------------------------------------------------------
# Stage 1: Teams
# ----------------------------------------------------------------------------
def seed_teams(db: Session) -> list[Team]:
    teams = [
        Team(
            name=mascot,
            abbreviation=abbrev,
            city=city,
            conference=conf,
            division=div,
        )
        for city, mascot, abbrev, conf, div in FRANCHISES
    ]
    db.add_all(teams)
    db.flush()  # populate IDs
    return teams


# ----------------------------------------------------------------------------
# Stage 2: Player pool
# ----------------------------------------------------------------------------
def build_player_pool(rng: random.Random) -> list[Player]:
    """Read minidex and build the league player pool.

    One canonical copy of every species in the dex is always created. If the
    dex is smaller than ``num_teams * roster_size + fa_buffer``, additional
    clones with ±variance are generated until the target pool size is met.
    """
    with settings.minidex_path.open(encoding="utf-8") as f:
        data = json.load(f)

    species_entries = data["pokemon"]
    target_pool_size = settings.num_teams * settings.roster_size + settings.fa_buffer

    pool: list[Player] = []
    generation_counter: Counter[str] = Counter()

    # Round 1 — one of each species, exactly as printed in the minidex.
    for entry in species_entries:
        species = entry["name"]
        generation_counter[species] += 1
        gen = generation_counter[species]
        stats = StatBlock(**entry["stats"])
        pool.append(
            build_player(
                pokedex_id=entry["id"],
                species=species,
                name=species,
                stats=stats,
                primary_ability=entry["primary_ability"],
                generation=gen,
                rng=rng,
            )
        )

    # Subsequent rounds — clone each species with ±variance until we hit target.
    if len(species_entries) < target_pool_size:
        while len(pool) < target_pool_size:
            for entry in species_entries:
                if len(pool) >= target_pool_size:
                    break
                species = entry["name"]
                generation_counter[species] += 1
                gen = generation_counter[species]
                base_stats = StatBlock(**entry["stats"])
                varied = base_stats.varied(settings.regen_stat_variance, rng)
                pool.append(
                    build_player(
                        pokedex_id=entry["id"],
                        species=species,
                        name=f"{species} {roman(gen)}",
                        stats=varied,
                        primary_ability=entry["primary_ability"],
                        generation=gen,
                        rng=rng,
                    )
                )

    return pool


# ----------------------------------------------------------------------------
# Stage 3: Roster assignment (snake-draft on BST descending)
# ----------------------------------------------------------------------------
def assign_rosters(pool: list[Player], teams: list[Team]) -> None:
    """Snake-draft sort by BST so talent is balanced across teams."""
    pool.sort(key=lambda p: p.bst, reverse=True)

    target_per_team = settings.roster_size
    rounds = target_per_team
    cursor = 0

    for r in range(rounds):
        order = list(teams) if r % 2 == 0 else list(reversed(teams))
        for team in order:
            if cursor >= len(pool):
                return
            pool[cursor].team_id = team.id
            cursor += 1

    # Anything left in the pool stays a free agent (team_id is already None).


# ----------------------------------------------------------------------------
# Stage 4: Draft picks
# ----------------------------------------------------------------------------
def seed_draft_picks(db: Session, teams: list[Team], season: int = 1) -> None:
    picks = [
        DraftPick(
            season=season,
            round=rd,
            pick_number=None,  # set at lottery time
            original_team_id=team.id,
            owning_team_id=team.id,
            is_used=False,
        )
        for team in teams
        for rd in (1, 2)
    ]
    db.add_all(picks)


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------
def _print_summary(db: Session) -> None:
    teams = db.query(Team).order_by(Team.conference, Team.division, Team.name).all()
    print()
    print("=" * 86)
    print(f"{'Team':<28} {'Conf':<5} {'Div':<10} {'Players':>7} {'BST Used':>10} {'vs Cap':>8}")
    print("-" * 86)
    over_cap = 0
    for team in teams:
        roster = [p for p in team.players if not p.is_retired]
        bst_used = sum(p.bst for p in roster)
        delta = bst_used - settings.bst_cap
        if delta > 0:
            over_cap += 1
        flag = f"+{delta}" if delta > 0 else f"{delta}"
        label = f"{team.city} {team.name}"
        print(
            f"{label:<28} {team.conference:<5} {team.division:<10} "
            f"{len(roster):>7} {bst_used:>10} {flag:>8}"
        )
    print("=" * 86)

    free_agents = db.query(Player).filter(Player.team_id.is_(None)).count()
    badge_counts = Counter(p.badge for p in db.query(Player).all())
    pos_counts = Counter(p.position.value for p in db.query(Player).all())

    print(f"\nLeague summary")
    print(f"  Teams:        {len(teams)}")
    print(f"  Free agents:  {free_agents}")
    print(f"  Over cap:     {over_cap} (cap = {settings.bst_cap}; tweak in config)")
    print(f"  Position mix: {dict(pos_counts)}")
    print(f"  Badge mix:")
    for badge, count in badge_counts.most_common():
        print(f"    {badge:<22} {count}")


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
def reset_database(seed: int = SEED, *, verbose: bool = False) -> dict:
    """Drop every table, recreate the schema, and re-seed a fresh league.

    Reusable from both the CLI (``python -m backend.seed``) and the API
    (``POST /api/league/reset``). Returns a small summary dict of counts.
    """
    rng = random.Random(seed)
    if verbose:
        print(f"Seeding pokeNBA league (deterministic seed={seed})...")

    drop_all()
    create_all()

    with SessionLocal() as db:
        reset_state(db)
        teams = seed_teams(db)
        pool = build_player_pool(rng)
        assign_rosters(pool, teams)
        db.add_all(pool)
        seed_draft_picks(db, teams, season=1)
        db.commit()
        if verbose:
            _print_summary(db)

        n_games = generate_schedule(db, season=1, rng=random.Random(seed))
        if verbose:
            print(f"\nGenerated {n_games} games for season 1.")

        # Counts for the API response (cheap COUNT queries on tiny tables).
        team_count = db.scalar(select(func.count(Team.id))) or 0
        player_count = db.scalar(select(func.count(Player.id))) or 0
        fa_count = db.scalar(select(func.count(Player.id)).where(Player.team_id.is_(None))) or 0

    if verbose:
        print("\nDone. SQLite file:", settings.database_url)

    return {
        "teams": team_count,
        "players": player_count,
        "free_agents": fa_count,
        "games_generated": n_games,
        "season": 1,
        "seed": seed,
    }


def run() -> None:
    """CLI entry point — verbose run with summary printing."""
    reset_database(verbose=True)


if __name__ == "__main__":
    run()

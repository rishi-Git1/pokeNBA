"""Command-line entry point for the simulation engine.

Examples::

    python -m backend.sim.cli schedule              # generate schedule
    python -m backend.sim.cli day                   # sim next game day
    python -m backend.sim.cli days --count 7        # sim next 7 game days
    python -m backend.sim.cli season                # sim rest of season
    python -m backend.sim.cli game --id 5           # replay one game with PBP
"""
from __future__ import annotations

import argparse
import random
import sys

from sqlalchemy import select

from backend.database import SessionLocal, create_all
from backend.models import Game, Player, Team
from backend.sim.game import run_game
from backend.sim.league_day import sim_day, sim_until_done
from backend.sim.schedule import generate_schedule


def _print_day(result) -> None:
    print(f"\n=== {result.sim_date} (season {result.season}) -- {result.games_played} games ===")
    for g in result.results:
        winner = "HOME" if g.home_score > g.away_score else "AWAY"
        print(f"  Game {g.home_team_id:>2} {g.home_score:>3} - {g.away_score:<3} {g.away_team_id:<2}  ({winner})")


def cmd_schedule(args: argparse.Namespace) -> int:
    create_all()
    with SessionLocal() as db:
        n = generate_schedule(db, season=args.season)
    print(f"Generated {n} games for season {args.season}.")
    return 0


def cmd_day(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    with SessionLocal() as db:
        result = sim_day(
            db, season=args.season, rng=rng,
            parallel=args.parallel, max_workers=args.workers,
            capture_play_log=False,
        )
    if result is None:
        print("No games left to play this season.")
        return 1
    _print_day(result)
    return 0


def cmd_days(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    with SessionLocal() as db:
        days = sim_until_done(
            db, season=args.season, rng=rng, max_days=args.count,
            parallel=args.parallel, max_workers=args.workers,
        )
    if not days:
        print("No games to play.")
        return 1
    for d in days:
        _print_day(d)
    print(f"\nSimulated {len(days)} game days, {sum(d.games_played for d in days)} games total.")
    return 0


def cmd_season(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    with SessionLocal() as db:
        days = sim_until_done(
            db, season=args.season, rng=rng,
            parallel=args.parallel, max_workers=args.workers,
        )
        print(f"Season {args.season} complete: {len(days)} days, "
              f"{sum(d.games_played for d in days)} games.")
        # Print top-3 standings per conference.
        teams = list(db.scalars(select(Team).order_by(Team.wins.desc())))
        print("\n--- Top of the East ---")
        for t in [x for x in teams if x.conference == "East"][:5]:
            print(f"  {t.abbreviation:<4} {t.wins:>3}-{t.losses:<3}  {t.city} {t.name}")
        print("--- Top of the West ---")
        for t in [x for x in teams if x.conference == "West"][:5]:
            print(f"  {t.abbreviation:<4} {t.wins:>3}-{t.losses:<3}  {t.city} {t.name}")
    return 0


def cmd_game(args: argparse.Namespace) -> int:
    """Replay a single game with full play-by-play (does NOT persist)."""
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    with SessionLocal() as db:
        game = db.get(Game, args.id)
        if game is None:
            print(f"Game {args.id} not found.")
            return 1
        home = db.get(Team, game.home_team_id)
        away = db.get(Team, game.away_team_id)
        home_players = list(db.scalars(select(Player).where(Player.team_id == home.id, Player.is_retired.is_(False))))
        away_players = list(db.scalars(select(Player).where(Player.team_id == away.id, Player.is_retired.is_(False))))
        result = run_game(
            game_id=game.id,
            season=game.season,
            home_id=home.id,
            home_abbr=home.abbreviation,
            home_players=home_players,
            away_id=away.id,
            away_abbr=away.abbreviation,
            away_players=away_players,
            rng=rng,
            capture_play_log=True,
        )
    print(f"\n{home.abbreviation} {result.home_score} - {result.away_score} {away.abbreviation}\n")
    if args.pbp:
        for line in result.play_log:
            print(line)
    print(f"\n--- Top scorers ---")
    top = sorted(result.box_scores, key=lambda r: r["points"], reverse=True)[:5]
    for row in top:
        print(
            f"  pid={row['player_id']:<4} {row['points']:>3} pts  "
            f"{row['rebounds']:>2} reb  {row['assists']:>2} ast  "
            f"{row['fg_made']}/{row['fg_attempted']} FG ({row['three_made']}/{row['three_attempted']} 3PT)  "
            f"{row['minutes']:.1f} min"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="poke-nba-sim", description="pokeNBA simulation CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sched = sub.add_parser("schedule", help="Generate the season schedule")
    p_sched.add_argument("--season", type=int, default=1)
    p_sched.set_defaults(func=cmd_schedule)

    def _add_perf_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--parallel", action="store_true", help="Run games concurrently across CPU cores")
        sp.add_argument("--workers", type=int, default=None, help="Worker count (default: # CPU cores)")

    p_day = sub.add_parser("day", help="Sim the next unplayed game day")
    p_day.add_argument("--season", type=int, default=1)
    p_day.add_argument("--seed", type=int, default=None)
    _add_perf_flags(p_day)
    p_day.set_defaults(func=cmd_day)

    p_days = sub.add_parser("days", help="Sim the next N game days")
    p_days.add_argument("--count", type=int, default=7)
    p_days.add_argument("--season", type=int, default=1)
    p_days.add_argument("--seed", type=int, default=None)
    _add_perf_flags(p_days)
    p_days.set_defaults(func=cmd_days)

    p_season = sub.add_parser("season", help="Sim the rest of the current season")
    p_season.add_argument("--season", type=int, default=1)
    p_season.add_argument("--seed", type=int, default=None)
    _add_perf_flags(p_season)
    p_season.set_defaults(func=cmd_season)

    p_game = sub.add_parser("game", help="Replay a single game (does not persist)")
    p_game.add_argument("--id", type=int, required=True)
    p_game.add_argument("--seed", type=int, default=None)
    p_game.add_argument("--pbp", action="store_true", help="Print full play-by-play")
    p_game.set_defaults(func=cmd_game)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

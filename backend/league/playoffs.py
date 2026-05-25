"""Playoff bracket: seeding, per-game simulation, round simulation, advancement.

Bracket layout (NBA standard, no play-in):

```
East:                         West:
  (1) ──┐                       (1) ──┐
        ├── R2-A                      ├── R2-A
  (8) ──┘     ├── E.Conf F           (8) ──┘     ├── W.Conf F
              │       └─── Finals ──── Champion
  (4) ──┐     ├── R2-A                  ├── R2-A
        ├── R2-A                      (4) ──┐
  (5) ──┘                               (5) ──┘
  (3) ──┐     (and similar for 3v6, 2v7)
        ├── R2-B
  (6) ──┘     ├── E.Conf F
  (2) ──┐     │
        ├── R2-B
  (7) ──┘
```

Slot indexing inside a bracket (within a round):
- Round 1: 0=1v8, 1=4v5, 2=3v6, 3=2v7
- Round 2: 0=(R1#0 winner) vs (R1#1 winner), 1=(R1#2 winner) vs (R1#3 winner)
- Round 3 (Conf Finals): 0=(R2#0 winner) vs (R2#1 winner)
- Round 4 (Finals): 0=East vs West conference winners
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Game, Player, Series, Team
from backend.league.playoff_injuries import (
    advance_injury_clocks,
    merge_reports,
    prepare_team_roster,
)
from backend.sim.game import run_game
from backend.sim.league_day import _load_rosters

GAMES_TO_WIN_SERIES: int = 4  # best of 7


# ----------------------------------------------------------------------------
# Bracket seeding (called once when regular season ends)
# ----------------------------------------------------------------------------
def start_playoffs(db: Session, season: int) -> list[Series]:
    """Seed the 8 first-round series (4 East + 4 West) from the current standings."""
    east_seeds = _seed_conference(db, "East")
    west_seeds = _seed_conference(db, "West")

    # First-round matchup pattern: (1v8), (4v5), (3v6), (2v7)
    first_round_pairs = [(1, 8), (4, 5), (3, 6), (2, 7)]

    series_rows: list[Series] = []
    for slot, (high, low) in enumerate(first_round_pairs):
        for bracket, seeds in (("East", east_seeds), ("West", west_seeds)):
            high_team = seeds[high - 1]
            low_team = seeds[low - 1]
            series_rows.append(Series(
                season=season,
                round=1,
                bracket=bracket,
                slot_index=slot,
                high_seed=high,
                low_seed=low,
                high_seed_team_id=high_team.id,
                low_seed_team_id=low_team.id,
            ))

    db.add_all(series_rows)
    db.commit()
    return series_rows


def _seed_conference(db: Session, conference: str) -> list[Team]:
    """Return the top 8 teams in a conference, sorted by win pct desc, then by raw wins."""
    teams = list(db.scalars(
        select(Team).where(Team.conference == conference)
    ))
    teams.sort(
        key=lambda t: (-(t.wins / max(1, t.wins + t.losses)), -t.wins, t.losses, t.id)
    )
    return teams[:8]


# ----------------------------------------------------------------------------
# Per-game simulation
# ----------------------------------------------------------------------------
def _sim_one_series_game(db: Session, series: Series, *, rng: random.Random) -> dict:
    """Sim the next scheduled game in a single series."""
    game_number = series.high_seed_wins + series.low_seed_wins + 1
    home_team, away_team = _matchup_home_away(db, series, game_number)

    raw_rosters = _load_rosters(db, {home_team.id, away_team.id})
    home_available, home_report = prepare_team_roster(
        db, season=series.season, roster=raw_rosters[home_team.id], rng=rng,
    )
    away_available, away_report = prepare_team_roster(
        db, season=series.season, roster=raw_rosters[away_team.id], rng=rng,
    )
    injury_report = merge_reports(home_report, away_report)

    game = Game(
        season=series.season,
        game_date=_next_playoff_date(db, series.season),
        home_team_id=home_team.id,
        away_team_id=away_team.id,
        is_playoff=True,
        series_id=series.id,
        series_game_number=game_number,
    )
    db.add(game)
    db.flush()

    result = run_game(
        game_id=game.id,
        season=series.season,
        home_id=home_team.id,
        home_abbr=home_team.abbreviation,
        home_players=home_available,
        away_id=away_team.id,
        away_abbr=away_team.abbreviation,
        away_players=away_available,
        rng=rng,
    )

    game.home_score = result.home_score
    game.away_score = result.away_score
    game.overtime_periods = result.overtime_periods
    game.is_completed = True
    if result.box_scores:
        from sqlalchemy import insert
        from backend.models import BoxScore
        db.execute(insert(BoxScore), result.box_scores)

    home_won = result.home_score > result.away_score
    winner_id = home_team.id if home_won else away_team.id
    if winner_id == series.high_seed_team_id:
        series.high_seed_wins += 1
    else:
        series.low_seed_wins += 1

    series_finished_now = False
    if series.high_seed_wins >= GAMES_TO_WIN_SERIES:
        series.is_completed = True
        series.winner_team_id = series.high_seed_team_id
        series_finished_now = True
    elif series.low_seed_wins >= GAMES_TO_WIN_SERIES:
        series.is_completed = True
        series.winner_team_id = series.low_seed_team_id
        series_finished_now = True

    advance_injury_clocks(db, season=series.season, team_ids={home_team.id, away_team.id})
    db.commit()

    if series_finished_now:
        _maybe_advance_round(db, series.season, series.round)

    return _series_state(db, series, latest_game=game, injury_report=injury_report)


def sim_next_playoff_game(db: Session, *, rng: random.Random | None = None) -> dict:
    """Sim the next undecided game in the earliest-round active series."""
    rng = rng or random.Random()
    series = _next_active_series(db)
    if series is None:
        raise RuntimeError("No active playoff series.")
    return _sim_one_series_game(db, series, rng=rng)


def current_round_slate(db: Session, season: int) -> dict | None:
    """Next simultaneous game number for every still-active series in the current round."""
    incomplete = list(db.scalars(
        select(Series)
        .where(Series.season == season, Series.is_completed.is_(False))
        .order_by(Series.round, Series.slot_index, Series.id)
    ))
    if not incomplete:
        return None

    current_round = incomplete[0].round
    round_series = [s for s in incomplete if s.round == current_round]
    slate_game = min(s.high_seed_wins + s.low_seed_wins + 1 for s in round_series)
    ready = [s for s in round_series if s.high_seed_wins + s.low_seed_wins + 1 == slate_game]

    return {
        "round": current_round,
        "slate_game": slate_game,
        "series_count": len(ready),
        "series_ids": [s.id for s in ready],
    }


def sim_round_slate(db: Session, *, rng: random.Random | None = None) -> dict:
    """Sim the next game number across every active series in the current round.

    Example: round 1 starts at 0-0 for all eight matchups — one click sims
    Game 1 in each series (eight games), then the button becomes Sim Game 2.
    """
    rng = rng or random.Random()
    slate = current_round_slate(db, _playoff_season(db))
    if slate is None:
        raise RuntimeError("No active playoff series.")

    series_rows = [
        db.get(Series, sid) for sid in slate["series_ids"]
    ]
    series_rows = [s for s in series_rows if s is not None and not s.is_completed]
    if not series_rows:
        raise RuntimeError("No series ready for the current slate.")

    results: list[dict] = []
    all_new: list[dict] = []
    all_unavail: list[dict] = []
    for series in series_rows:
        if series.is_completed:
            continue
        next_num = series.high_seed_wins + series.low_seed_wins + 1
        if next_num != slate["slate_game"]:
            continue
        outcome = _sim_one_series_game(db, series, rng=rng)
        results.append(outcome)
        ir = outcome.get("injury_report")
        if ir:
            all_new.extend(ir.get("new_injuries", []))
            all_unavail.extend(ir.get("unavailable", []))

    return {
        "round": slate["round"],
        "slate_game": slate["slate_game"],
        "games_played": len(results),
        "results": results,
        "injury_report": {"new_injuries": all_new, "unavailable": all_unavail},
    }


def _playoff_season(db: Session) -> int:
    row = db.scalars(
        select(Series.season)
        .where(Series.is_completed.is_(False))
        .order_by(Series.season.desc())
        .limit(1)
    ).first()
    if row is not None:
        return row
    row = db.scalars(select(Series.season).order_by(Series.season.desc()).limit(1)).first()
    if row is None:
        from backend.league.state import get_state
        return get_state(db).current_season
    return row


def sim_next_playoff_round(db: Session, *, rng: random.Random | None = None) -> dict:
    """Keep simming games until every series in the current round resolves."""
    rng = rng or random.Random()
    games_played = 0
    last: dict | None = None
    injury_reports: list[dict] = []
    while True:
        series = _next_active_series(db)
        if series is None:
            break
        # Only stop when the current round is fully resolved.
        if last is not None and last.get("round") != series.round:
            break
        last = sim_next_playoff_game(db, rng=rng)
        games_played += 1
        if last.get("injury_report"):
            injury_reports.append(last["injury_report"])
    return {"games_played": games_played, "stopped_at": last, "injury_reports": injury_reports}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _next_active_series(db: Session) -> Series | None:
    """Earliest-round, lowest-slot incomplete series with both seats filled."""
    return db.scalars(
        select(Series)
        .where(Series.is_completed.is_(False))
        .order_by(Series.season, Series.round, Series.slot_index, Series.id)
        .limit(1)
    ).first()


def _matchup_home_away(db: Session, series: Series, game_number: int) -> tuple[Team, Team]:
    """Best-of-7 home pattern: high seed hosts games 1, 2, 5, 7."""
    high = db.get(Team, series.high_seed_team_id)
    low = db.get(Team, series.low_seed_team_id)
    high_hosts = game_number in (1, 2, 5, 7)
    return (high, low) if high_hosts else (low, high)


def _next_playoff_date(db: Session, season: int) -> date:
    """Pick a date one day past the latest game already in the DB for this season."""
    latest = db.scalar(
        select(Game.game_date)
        .where(Game.season == season)
        .order_by(Game.game_date.desc())
        .limit(1)
    )
    if latest is None:
        return date(2027, 4, 15)  # arbitrary playoff start
    return latest + timedelta(days=1)


def _maybe_advance_round(db: Session, season: int, round_number: int) -> None:
    """If every series in the just-finished round is complete, build the next round."""
    same_round = list(db.scalars(
        select(Series).where(Series.season == season, Series.round == round_number)
    ))
    if not all(s.is_completed for s in same_round):
        return  # round not done yet

    if round_number == 1:
        _build_round_2(db, season, same_round)
    elif round_number == 2:
        _build_conference_finals(db, season, same_round)
    elif round_number == 3:
        _build_finals(db, season, same_round)
    # Round 4 (Finals) — terminal; lifecycle.maybe_advance_phase will move to DRAFT.


def _build_round_2(db: Session, season: int, round_one: list[Series]) -> None:
    """For each conference, build 2 semifinal series from the 4 round-1 winners."""
    for bracket in ("East", "West"):
        sl0 = next(s for s in round_one if s.bracket == bracket and s.slot_index == 0)
        sl1 = next(s for s in round_one if s.bracket == bracket and s.slot_index == 1)
        sl2 = next(s for s in round_one if s.bracket == bracket and s.slot_index == 2)
        sl3 = next(s for s in round_one if s.bracket == bracket and s.slot_index == 3)

        for slot, (top, bot) in enumerate(((sl0, sl1), (sl2, sl3))):
            t_high, t_low = _seed_order(top, bot)
            db.add(Series(
                season=season, round=2, bracket=bracket, slot_index=slot,
                high_seed=_winning_seed(t_high),
                low_seed=_winning_seed(t_low),
                high_seed_team_id=t_high.winner_team_id,  # type: ignore[arg-type]
                low_seed_team_id=t_low.winner_team_id,    # type: ignore[arg-type]
            ))
    db.commit()


def _build_conference_finals(db: Session, season: int, round_two: list[Series]) -> None:
    for bracket in ("East", "West"):
        sl0 = next(s for s in round_two if s.bracket == bracket and s.slot_index == 0)
        sl1 = next(s for s in round_two if s.bracket == bracket and s.slot_index == 1)
        t_high, t_low = _seed_order(sl0, sl1)
        db.add(Series(
            season=season, round=3, bracket=bracket, slot_index=0,
            high_seed=_winning_seed(t_high), low_seed=_winning_seed(t_low),
            high_seed_team_id=t_high.winner_team_id,  # type: ignore[arg-type]
            low_seed_team_id=t_low.winner_team_id,    # type: ignore[arg-type]
        ))
    db.commit()


def _build_finals(db: Session, season: int, conf_finals: list[Series]) -> None:
    east = next(s for s in conf_finals if s.bracket == "East")
    west = next(s for s in conf_finals if s.bracket == "West")
    # Finals: home court goes to the better record; we approximate with seed.
    east_seed = _winning_seed(east)
    west_seed = _winning_seed(west)
    if east_seed <= west_seed:
        high_team_id, low_team_id, high_seed, low_seed = (
            east.winner_team_id, west.winner_team_id, east_seed, west_seed
        )
    else:
        high_team_id, low_team_id, high_seed, low_seed = (
            west.winner_team_id, east.winner_team_id, west_seed, east_seed
        )
    db.add(Series(
        season=season, round=4, bracket="Finals", slot_index=0,
        high_seed=high_seed, low_seed=low_seed,
        high_seed_team_id=high_team_id,  # type: ignore[arg-type]
        low_seed_team_id=low_team_id,    # type: ignore[arg-type]
    ))
    db.commit()


def _seed_order(a: Series, b: Series) -> tuple[Series, Series]:
    """Whichever series winner has the better seed (lower number) is the high seed."""
    a_seed = _winning_seed(a)
    b_seed = _winning_seed(b)
    return (a, b) if a_seed <= b_seed else (b, a)


def _winning_seed(series: Series) -> int:
    return series.high_seed if series.winner_team_id == series.high_seed_team_id else series.low_seed


def _series_state(
    db: Session,
    series: Series,
    *,
    latest_game: Game | None = None,
    injury_report=None,
) -> dict:
    out = {
        "series_id": series.id,
        "round": series.round,
        "bracket": series.bracket,
        "slot_index": series.slot_index,
        "high_seed": series.high_seed,
        "low_seed": series.low_seed,
        "high_seed_team_id": series.high_seed_team_id,
        "low_seed_team_id": series.low_seed_team_id,
        "high_seed_wins": series.high_seed_wins,
        "low_seed_wins": series.low_seed_wins,
        "is_completed": series.is_completed,
        "winner_team_id": series.winner_team_id,
        "latest_game_id": latest_game.id if latest_game is not None else None,
        "latest_score": (
            f"{latest_game.away_score}-{latest_game.home_score}"
            if latest_game is not None else None
        ),
    }
    if injury_report is not None:
        out["injury_report"] = injury_report.to_dict()
    return out


def get_bracket(db: Session, season: int) -> dict:
    """Full bracket dump for the frontend: all series across all rounds."""
    rows = list(db.scalars(
        select(Series).where(Series.season == season).order_by(Series.round, Series.bracket, Series.slot_index)
    ))
    slate = current_round_slate(db, season)
    return {
        "season": season,
        "slate": slate,
        "series": [
            {
                "id": s.id,
                "round": s.round,
                "bracket": s.bracket,
                "slot_index": s.slot_index,
                "high_seed": s.high_seed,
                "low_seed": s.low_seed,
                "high_seed_team_id": s.high_seed_team_id,
                "low_seed_team_id": s.low_seed_team_id,
                "high_seed_wins": s.high_seed_wins,
                "low_seed_wins": s.low_seed_wins,
                "is_completed": s.is_completed,
                "winner_team_id": s.winner_team_id,
            }
            for s in rows
        ],
    }

"""Projected win totals for what-if roster moves.

The model is intentionally simple: a closed-form rating that weighs starters
heavily over deep bench, normalized against the league average, then mapped
linearly to season wins. It's accurate enough for "should I cut this guy?"
prompts without paying for a full Monte Carlo sim.

If you want better fidelity later, swap ``project_wins`` for a function that
spawns N games via ``backend.sim.game.run_game`` against a synthetic average
opponent — the rest of the API stays the same.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.models import Player, Team

# Rating weights: 5 starters get heavy weight, deep bench gets a sliver.
# Sum (~11.85) is intentional: we normalize against league mean before
# converting to wins, so absolute scale doesn't matter.
_STARTER_WEIGHTS: list[float] = [
    2.0, 1.8, 1.6, 1.4, 1.2,   # starters (1–5)
    0.8, 0.7, 0.6, 0.5, 0.4,   # rotation bench (6–10)
    0.3, 0.2, 0.15, 0.1, 0.05, # deep bench (11–15)
]
_WIN_SLOPE: float = 200.0  # wins per 100% rating delta vs league average
_PACE_BLEND_MAX: float = 0.7  # cap pace's contribution at 70% even late-season


def team_rating(roster: list[Player]) -> float:
    """Effective team strength. Sorts by BST, applies starter weights.

    Note: rating uses *raw* BST, not effective BST — a rookie on a discount
    deal is still as good as their stats say. The cap math is what cares
    about the discount, not the projection.
    """
    if not roster:
        return 0.0
    sorted_players = sorted(roster, key=lambda p: -p.bst)
    return sum(
        w * p.bst
        for w, p in zip(_STARTER_WEIGHTS, sorted_players)
    )


def project_wins(
    rating: float,
    league_avg: float,
    *,
    season_games: int | None = None,
    current_wins: int = 0,
    current_losses: int = 0,
) -> int:
    """Map (rating - league_avg) and optional season pace → projected wins.

    Pure-rating projection (the only kind available before opening night) is a
    linear function of relative rating. Once games are played, we blend in the
    team's current pace, weighted by season progress (capped at 70%) so a hot
    or cold start still moves the number even after months of games.

    Result is clamped to ``[5, season_games - 5]``.
    """
    games = season_games or settings.season_games

    # Rating-based component — the only thing that responds to roster moves.
    if league_avg <= 0:
        rating_wins = games / 2.0
    else:
        relative = (rating - league_avg) / league_avg
        rating_wins = (games / 2.0) + relative * _WIN_SLOPE

    # Optional pace blend — extrapolate the current record.
    games_played = max(0, current_wins + current_losses)
    if games_played > 0:
        win_pct = current_wins / games_played
        pace_wins = win_pct * games
        progress = min(_PACE_BLEND_MAX, games_played / games)
        proj = progress * pace_wins + (1.0 - progress) * rating_wins
    else:
        proj = rating_wins

    return max(5, min(games - 5, round(proj)))


def league_average_rating(db: Session) -> float:
    """Mean rating across all 30 teams (excludes retired players)."""
    teams = list(db.scalars(select(Team)))
    if not teams:
        return 0.0
    ratings = [
        team_rating([p for p in t.players if not p.is_retired])
        for t in teams
    ]
    return sum(ratings) / len(ratings)


def project_team(db: Session, team: Team) -> dict:
    """Build a projection blob for the team's *current* roster."""
    roster = [p for p in team.players if not p.is_retired]
    rating = team_rating(roster)
    league_avg = league_average_rating(db)
    return {
        "team_id": team.id,
        "rating": round(rating, 1),
        "league_avg_rating": round(league_avg, 1),
        "projected_wins": project_wins(
            rating, league_avg,
            current_wins=team.wins, current_losses=team.losses,
        ),
        "season_games": settings.season_games,
    }


def project_after_release(db: Session, *, team_id: int, player_id: int) -> dict:
    """Compute current vs after-release projection for a confirm dialog."""
    team = db.get(Team, team_id)
    if team is None:
        raise ValueError("Team not found")
    player = db.get(Player, player_id)
    if player is None or player.team_id != team_id:
        raise ValueError("Player is not on that team")

    current_roster = [p for p in team.players if not p.is_retired]
    after_roster = [p for p in current_roster if p.id != player_id]

    league_avg = league_average_rating(db)
    current_rating = team_rating(current_roster)
    after_rating = team_rating(after_roster)

    bst_used = sum(p.effective_bst for p in current_roster)
    bst_after = sum(p.effective_bst for p in after_roster)

    proj_kwargs = dict(current_wins=team.wins, current_losses=team.losses)

    return {
        "team_id": team_id,
        "player_id": player_id,
        "player_name": player.name,
        "current": {
            "projected_wins": project_wins(current_rating, league_avg, **proj_kwargs),
            "bst_used": bst_used,
            "roster_size": len(current_roster),
        },
        "after": {
            "projected_wins": project_wins(after_rating, league_avg, **proj_kwargs),
            "bst_used": bst_after,
            "roster_size": len(after_roster),
        },
    }


def project_after_sign(db: Session, *, team_id: int, player_id: int) -> dict:
    """Mirror of ``project_after_release`` for free-agent signings."""
    team = db.get(Team, team_id)
    if team is None:
        raise ValueError("Team not found")
    player = db.get(Player, player_id)
    if player is None:
        raise ValueError("Player not found")
    if player.team_id is not None:
        raise ValueError("Player already on a team")

    current_roster = [p for p in team.players if not p.is_retired]
    after_roster = current_roster + [player]

    league_avg = league_average_rating(db)
    current_rating = team_rating(current_roster)
    after_rating = team_rating(after_roster)

    proj_kwargs = dict(current_wins=team.wins, current_losses=team.losses)

    return {
        "team_id": team_id,
        "player_id": player_id,
        "player_name": player.name,
        "current": {
            "projected_wins": project_wins(current_rating, league_avg, **proj_kwargs),
            "bst_used": sum(p.effective_bst for p in current_roster),
            "roster_size": len(current_roster),
        },
        "after": {
            "projected_wins": project_wins(after_rating, league_avg, **proj_kwargs),
            "bst_used": sum(p.effective_bst for p in after_roster),
            "roster_size": len(after_roster),
        },
    }

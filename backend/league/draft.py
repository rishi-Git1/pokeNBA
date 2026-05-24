"""Annual rookie draft.

After playoffs end, the lifecycle module runs aging+regens, inflates the
cap, and then calls :func:`initialize_draft_order` to set the pick order
(worst record → best record, ties decided by coin flip). Each pick assigns
one free-agent player to a team **on a 3-season rookie deal** (counts as
half BST against the cap during those years).

Only the **first round** is drafted (30 picks). The R2 picks already minted
by ``end_of_season`` stay around as trade assets but aren't auto-used here.
"""
from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.league.state import get_state
from backend.models import DraftPick, Player, Team

ROOKIE_DEAL_SEASONS: int = 3


# ----------------------------------------------------------------------------
# Initialization
# ----------------------------------------------------------------------------
def initialize_draft_order(db: Session, *, season: int, rng: random.Random | None = None) -> None:
    """Set ``pick_number`` on every R1 pick for ``season + 1`` and reset progress."""
    rng = rng or random.Random()

    # We assign rookies to picks owned by ``original_team_id`` ordering. But the
    # owning_team_id is what counts (picks may have been traded). For draft
    # ORDER, use the ORIGINAL team's record. The picking team is the OWNING
    # team. This matches real-world reverse-order rules.
    next_season = season + 1
    picks: list[DraftPick] = list(db.scalars(
        select(DraftPick)
        .where(DraftPick.season == next_season, DraftPick.round == 1, DraftPick.is_used.is_(False))
    ))
    if not picks:
        # Defensive: if end_of_season hasn't run yet, mint them now.
        teams = list(db.scalars(select(Team).order_by(Team.id)))
        picks = [
            DraftPick(season=next_season, round=1, original_team_id=t.id, owning_team_id=t.id, is_used=False)
            for t in teams
        ]
        db.add_all(picks)
        db.commit()

    teams_by_id = {t.id: t for t in db.scalars(select(Team))}

    # Sort by ORIGINAL team's record: ascending wins, descending losses, then
    # a deterministic coin-flip-ish tiebreaker (rng.random()).
    def sort_key(pick: DraftPick) -> tuple[int, int, float]:
        t = teams_by_id[pick.original_team_id]
        # Lower wins first; same wins -> more losses first; ties -> rng.
        return (t.wins, -t.losses, rng.random())

    picks.sort(key=sort_key)
    for i, pick in enumerate(picks, start=1):
        pick.pick_number = i

    state = get_state(db)
    state.draft_current_pick = 0
    state.draft_total_picks = len(picks)
    db.commit()


# ----------------------------------------------------------------------------
# State view
# ----------------------------------------------------------------------------
def get_draft_state(db: Session) -> dict:
    """Snapshot of the draft for the frontend draft room."""
    state = get_state(db)
    season = state.current_season + 1  # picks were minted for "next season"

    picks: list[DraftPick] = list(db.scalars(
        select(DraftPick)
        .where(DraftPick.season == season, DraftPick.round == 1)
        .order_by(DraftPick.pick_number)
    ))

    on_clock = next((pk for pk in picks if not pk.is_used), None)
    teams_by_id = {t.id: t for t in db.scalars(select(Team))}

    available = list(db.scalars(
        select(Player)
        .where(Player.team_id.is_(None), Player.is_retired.is_(False))
        .order_by(Player.bst.desc())
    ))

    pick_log = []
    for pk in picks:
        owning = teams_by_id.get(pk.owning_team_id)
        original = teams_by_id.get(pk.original_team_id)
        drafted = None
        if pk.is_used:
            drafted = db.scalars(
                select(Player).where(
                    Player.drafted_season == season,
                    Player.drafted_pick_number == pk.pick_number,
                )
            ).first()
        pick_log.append({
            "pick_number": pk.pick_number,
            "owning_team_id": pk.owning_team_id,
            "owning_abbr": owning.abbreviation if owning else None,
            "original_team_id": pk.original_team_id,
            "original_abbr": original.abbreviation if original else None,
            "is_used": pk.is_used,
            "drafted_player_id": drafted.id if drafted else None,
            "drafted_player_name": drafted.name if drafted else None,
            "drafted_player_sprite": drafted.sprite_url if drafted else None,
            "drafted_player_position": drafted.position.value if drafted else None,
            "drafted_player_bst": drafted.bst if drafted else None,
        })

    return {
        "season": season,
        "current_pick": state.draft_current_pick,
        "total_picks": state.draft_total_picks,
        "is_complete": state.draft_total_picks > 0 and state.draft_current_pick >= state.draft_total_picks,
        "on_clock": _on_clock_blob(on_clock, teams_by_id) if on_clock is not None else None,
        "picks": pick_log,
        "available": [
            {
                "id": p.id,
                "name": p.name,
                "species": p.species,
                "pokedex_id": p.pokedex_id,
                "position": p.position.value,
                "bst": p.bst,
                "effective_bst": p.bst // 2,  # rookie-deal preview
                "badge": p.badge,
                "age": p.age,
                "is_regen": p.is_regen,
                "generation": p.generation,
                "sprite_url": p.sprite_url,
                "artwork_url": p.artwork_url,
            }
            for p in available
        ],
    }


def _on_clock_blob(pick: DraftPick, teams_by_id: dict[int, Team]) -> dict:
    owning = teams_by_id.get(pick.owning_team_id)
    original = teams_by_id.get(pick.original_team_id)
    return {
        "pick_number": pick.pick_number,
        "owning_team_id": pick.owning_team_id,
        "owning_team_abbr": owning.abbreviation if owning else None,
        "owning_team_name": f"{owning.city} {owning.name}" if owning else None,
        "via": (
            None
            if owning is original or owning is None or original is None
            else f"via {original.abbreviation}"
        ),
    }


# ----------------------------------------------------------------------------
# Picks
# ----------------------------------------------------------------------------
class DraftError(Exception):
    pass


def _get_current_pick(db: Session) -> DraftPick:
    state = get_state(db)
    season = state.current_season + 1
    pick = db.scalars(
        select(DraftPick)
        .where(DraftPick.season == season, DraftPick.round == 1, DraftPick.is_used.is_(False))
        .order_by(DraftPick.pick_number)
        .limit(1)
    ).first()
    if pick is None:
        raise DraftError("Draft is already complete.")
    return pick


def make_pick(db: Session, *, player_id: int) -> dict:
    """Manual pick by the team currently on the clock."""
    pick = _get_current_pick(db)
    player = db.get(Player, player_id)
    if player is None:
        raise DraftError(f"Player {player_id} not found.")
    if player.is_retired:
        raise DraftError("Cannot draft a retired player.")
    if player.team_id is not None:
        raise DraftError("Player is not a free agent.")

    return _execute_pick(db, pick, player)


def auto_pick(db: Session) -> dict:
    """Best available BST goes to the team on the clock."""
    pick = _get_current_pick(db)
    state = get_state(db)
    season = state.current_season + 1

    # Greedy heuristic: highest raw BST among unsigned players.
    player = db.scalars(
        select(Player)
        .where(Player.team_id.is_(None), Player.is_retired.is_(False))
        .order_by(Player.bst.desc())
        .limit(1)
    ).first()
    if player is None:
        raise DraftError("No free agents left to draft.")
    return _execute_pick(db, pick, player)


def sim_rest_of_draft(db: Session) -> dict:
    """Auto-pick every remaining selection in one shot."""
    picks_made = 0
    while True:
        try:
            auto_pick(db)
            picks_made += 1
        except DraftError:
            break
    state = get_state(db)
    return {
        "picks_made": picks_made,
        "current_pick": state.draft_current_pick,
        "total_picks": state.draft_total_picks,
        "is_complete": state.draft_current_pick >= state.draft_total_picks,
    }


def _execute_pick(db: Session, pick: DraftPick, player: Player) -> dict:
    """Stamp the rookie deal and bump draft progress. Idempotent up to the pick."""
    player.team_id = pick.owning_team_id
    player.on_rookie_deal = True
    player.rookie_seasons_remaining = ROOKIE_DEAL_SEASONS
    player.drafted_pick_number = pick.pick_number
    player.drafted_season = pick.season

    pick.is_used = True

    state = get_state(db)
    state.draft_current_pick += 1
    db.commit()

    return {
        "pick_number": pick.pick_number,
        "team_id": pick.owning_team_id,
        "player": {
            "id": player.id,
            "name": player.name,
            "position": player.position.value,
            "bst": player.bst,
            "effective_bst": player.effective_bst,
            "sprite_url": player.sprite_url,
        },
        "current_pick": state.draft_current_pick,
        "total_picks": state.draft_total_picks,
        "is_complete": state.draft_current_pick >= state.draft_total_picks,
    }

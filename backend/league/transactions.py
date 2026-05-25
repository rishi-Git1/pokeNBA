"""Trade execution + free-agent signings/releases.

Pure transactional logic, separated from the FastAPI router so the same code
can be invoked from the CLI, batch scripts, or future AI-driven CPU GMs.

Cap rule (default): a transaction may not push a team's roster BST above
``settings.bst_cap + TRADE_CAP_LEEWAY``. Tweak the leeway in ``settings`` if
you want a hard cap; right now we accept a small overshoot so the trade phase
isn't impossible from the seed state.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.league.state import get_state
from backend.league.injuries import apply_waiver_wire_penalty, handle_player_release
from backend.models import DraftPick, Player, Team


# How much a trade may push a team over the cap. The seed already starts every
# team a few hundred BST over, so this leeway prevents lockup on day one.
TRADE_CAP_LEEWAY: int = 1500
ROSTER_MAX_AFTER_TRADE: int = 17  # allow temporary 2-slot bloat for trade processing
ROSTER_MIN_AFTER_TRADE: int = 8


class TransactionError(Exception):
    """Raised when a trade or signing violates league rules."""


@dataclass(slots=True)
class TradeProposal:
    team_a_id: int
    team_b_id: int
    team_a_player_ids: list[int]
    team_b_player_ids: list[int]
    team_a_pick_ids: list[int] = None  # type: ignore[assignment]
    team_b_pick_ids: list[int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.team_a_pick_ids = self.team_a_pick_ids or []
        self.team_b_pick_ids = self.team_b_pick_ids or []


@dataclass(slots=True)
class TradeReport:
    team_a_id: int
    team_b_id: int
    team_a_bst_before: int
    team_a_bst_after: int
    team_b_bst_before: int
    team_b_bst_after: int
    players_moved: int
    picks_moved: int


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _team_roster(db: Session, team_id: int) -> list[Player]:
    return list(
        db.scalars(
            select(Player).where(
                Player.team_id == team_id,
                Player.is_retired.is_(False),
            )
        )
    )


def _bst_total(roster: list[Player]) -> int:
    """Effective BST — rookies count for half during their first 3 seasons."""
    return sum(p.effective_bst for p in roster)


def _check_cap(db: Session, team_label: str, new_total: int) -> None:
    state = get_state(db)
    cap = state.bst_cap + TRADE_CAP_LEEWAY
    if new_total > cap:
        raise TransactionError(
            f"Transaction would put {team_label} at {new_total} BST (cap {state.bst_cap}, "
            f"max with leeway {cap})."
        )


def _check_roster_bounds(team_label: str, new_size: int) -> None:
    if new_size > ROSTER_MAX_AFTER_TRADE:
        raise TransactionError(f"{team_label} would exceed roster max ({new_size} > {ROSTER_MAX_AFTER_TRADE}).")
    if new_size < ROSTER_MIN_AFTER_TRADE:
        raise TransactionError(f"{team_label} would fall below roster min ({new_size} < {ROSTER_MIN_AFTER_TRADE}).")


# ----------------------------------------------------------------------------
# Public ops
# ----------------------------------------------------------------------------
def execute_trade(db: Session, proposal: TradeProposal) -> TradeReport:
    """Atomically swap players + picks between two teams."""
    if proposal.team_a_id == proposal.team_b_id:
        raise TransactionError("Cannot trade with yourself.")

    team_a = db.get(Team, proposal.team_a_id)
    team_b = db.get(Team, proposal.team_b_id)
    if team_a is None or team_b is None:
        raise TransactionError("One or both teams not found.")

    # Resolve and validate ownership.
    players_out_a = [db.get(Player, pid) for pid in proposal.team_a_player_ids]
    players_out_b = [db.get(Player, pid) for pid in proposal.team_b_player_ids]
    for p in players_out_a:
        if p is None or p.team_id != team_a.id or p.is_retired:
            raise TransactionError(f"Player {p.id if p else '?'} not on team A or is retired.")
    for p in players_out_b:
        if p is None or p.team_id != team_b.id or p.is_retired:
            raise TransactionError(f"Player {p.id if p else '?'} not on team B or is retired.")

    picks_out_a = [db.get(DraftPick, pid) for pid in proposal.team_a_pick_ids]
    picks_out_b = [db.get(DraftPick, pid) for pid in proposal.team_b_pick_ids]
    for pk in picks_out_a:
        if pk is None or pk.owning_team_id != team_a.id or pk.is_used:
            raise TransactionError(f"Pick {pk.id if pk else '?'} not owned by team A.")
    for pk in picks_out_b:
        if pk is None or pk.owning_team_id != team_b.id or pk.is_used:
            raise TransactionError(f"Pick {pk.id if pk else '?'} not owned by team B.")

    # Compute hypothetical post-trade rosters.
    a_roster = _team_roster(db, team_a.id)
    b_roster = _team_roster(db, team_b.id)
    a_bst_before = _bst_total(a_roster)
    b_bst_before = _bst_total(b_roster)

    a_after = [p for p in a_roster if p not in players_out_a] + players_out_b  # type: ignore[operator]
    b_after = [p for p in b_roster if p not in players_out_b] + players_out_a  # type: ignore[operator]

    a_bst_after = _bst_total(a_after)
    b_bst_after = _bst_total(b_after)

    _check_cap(db, team_a.name, a_bst_after)
    _check_cap(db, team_b.name, b_bst_after)
    _check_roster_bounds(team_a.name, len(a_after))
    _check_roster_bounds(team_b.name, len(b_after))

    # Apply.
    for p in players_out_a:
        p.team_id = team_b.id  # type: ignore[union-attr]
    for p in players_out_b:
        p.team_id = team_a.id  # type: ignore[union-attr]
    for pk in picks_out_a:
        pk.owning_team_id = team_b.id  # type: ignore[union-attr]
    for pk in picks_out_b:
        pk.owning_team_id = team_a.id  # type: ignore[union-attr]

    db.commit()

    return TradeReport(
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        team_a_bst_before=a_bst_before,
        team_a_bst_after=a_bst_after,
        team_b_bst_before=b_bst_before,
        team_b_bst_after=b_bst_after,
        players_moved=len(players_out_a) + len(players_out_b),
        picks_moved=len(picks_out_a) + len(picks_out_b),
    )


def sign_free_agent(db: Session, *, team_id: int, player_id: int) -> Player:
    """Sign a free agent. Errors if the player isn't actually free or violates cap."""
    team = db.get(Team, team_id)
    player = db.get(Player, player_id)
    if team is None:
        raise TransactionError("Team not found.")
    if player is None:
        raise TransactionError("Player not found.")
    if player.is_retired:
        raise TransactionError("Cannot sign a retired player.")
    if player.team_id is not None:
        raise TransactionError("Player is already on a team.")

    if player.injury_penalty_pending:
        apply_waiver_wire_penalty(player)
        player.injury_penalty_pending = False

    roster = _team_roster(db, team.id)
    new_total = _bst_total(roster) + player.effective_bst
    _check_cap(db, team.name, new_total)
    _check_roster_bounds(team.name, len(roster) + 1)

    player.team_id = team.id
    db.commit()
    return player


def release_player(db: Session, *, team_id: int, player_id: int) -> Player:
    """Cut a player to free agency."""
    player = db.get(Player, player_id)
    if player is None:
        raise TransactionError("Player not found.")
    if player.team_id != team_id:
        raise TransactionError("Player is not on that team.")
    roster = _team_roster(db, team_id)
    _check_roster_bounds("releasing team", len(roster) - 1)

    season = get_state(db).current_season
    if handle_player_release(db, player=player, season=season):
        player.injury_penalty_pending = True

    player.team_id = None
    db.commit()
    return player

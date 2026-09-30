"""Request lifecycle domain logic: state machine, audit trail, episode assignment.

All rules are enforced here (server-side):
- Only whitelisted transitions, by the roles that own each step.
- `delivered` requires COUNT(assignments) >= episodes_requested.
- Only `good`/`usable` episodes may be assigned; an episode can belong to at
  most one request at any time (DB unique constraint is the last line of defence).
"""
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Assignment, Episode, Request, RequestStatusHistory, User
from app.models.episode import EpisodeQuality
from app.models.request import RequestStatus
from app.models.user import UserRole

# from_status -> set of allowed to_status values
TRANSITIONS: dict[RequestStatus, set[RequestStatus]] = {
    RequestStatus.SUBMITTED: {RequestStatus.IN_PROGRESS},
    RequestStatus.IN_PROGRESS: {RequestStatus.DELIVERED},
    RequestStatus.DELIVERED: {RequestStatus.ACCEPTED, RequestStatus.REJECTED},
    RequestStatus.ACCEPTED: set(),  # terminal
    RequestStatus.REJECTED: {RequestStatus.IN_PROGRESS},  # rework
}

# Which roles may perform each transition (owner client handles review steps).
TRANSITION_ROLES: dict[RequestStatus, set[UserRole]] = {
    RequestStatus.IN_PROGRESS: {UserRole.OPERATOR, UserRole.ADMIN},
    RequestStatus.DELIVERED: {UserRole.OPERATOR, UserRole.ADMIN},
    RequestStatus.ACCEPTED: {UserRole.CLIENT},
    RequestStatus.REJECTED: {UserRole.CLIENT},
}

ASSIGNABLE_QUALITIES = (EpisodeQuality.GOOD, EpisodeQuality.USABLE)


class DomainError(HTTPException):
    """A business-rule violation surfaced as a clean 4xx response."""

    def __init__(self, code: str, detail: str, status_code: int = status.HTTP_409_CONFLICT):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_transition(request: Request, to_status: RequestStatus, actor: User) -> None:
    """Raise DomainError unless `actor` may move `request` to `to_status` now."""
    allowed = TRANSITIONS.get(request.status, set())
    if to_status not in allowed:
        raise DomainError(
            "INVALID_TRANSITION",
            f"Cannot move request from {request.status.value!r} to {to_status.value!r}",
        )

    roles = TRANSITION_ROLES[to_status]
    if actor.role not in roles:
        raise DomainError(
            "FORBIDDEN_TRANSITION",
            f"Role {actor.role.value!r} cannot perform transition to {to_status.value!r}",
        )

    # A client may only act on their own request.
    if actor.role == UserRole.CLIENT and request.client_id != actor.id:
        raise DomainError("NOT_OWNER", "Clients can only act on their own requests", 403)

    # Preconditions.
    if to_status == RequestStatus.DELIVERED:
        if len(request.assignments) < request.episodes_requested:
            raise DomainError(
                "INSUFFICIENT_EPISODES",
                f"Request has {len(request.assignments)} assigned episode(s), "
                f"needs {request.episodes_requested} before delivery",
            )


def apply_transition(
    db: Session, request: Request, to_status: RequestStatus, actor: User
) -> Request:
    """Validate then persist a transition with its audit-trail entry."""
    validate_transition(request, to_status, actor)
    from_status = request.status
    request.status = to_status
    request.updated_at = _utcnow()
    db.add(
        RequestStatusHistory(
            request_id=request.id,
            from_status=from_status.value,
            to_status=to_status.value,
            changed_by_user_id=actor.id,
            changed_at=_utcnow(),
        )
    )
    db.commit()
    db.refresh(request)
    return request


def assign_episode(db: Session, request: Request, episode: Episode, actor: User) -> Assignment:
    """Assign one episode to a request under the domain rules."""
    if request.status not in (RequestStatus.SUBMITTED, RequestStatus.IN_PROGRESS,
                              RequestStatus.REJECTED):
        raise DomainError(
            "NOT_ASSIGNABLE",
            f"Episodes can only be assigned while the request is submitted/in_progress/rejected, "
            f"not {request.status.value!r}",
        )
    if episode.quality not in ASSIGNABLE_QUALITIES:
        raise DomainError(
            "BAD_QUALITY",
            f"Episode {episode.episode_id} has quality {episode.quality.value!r}; "
            f"only 'good' or 'usable' episodes can be assigned",
        )
    # Episode already assigned to *another* request?
    existing = (
        db.query(Assignment)
        .filter(Assignment.episode_id == episode.id, Assignment.request_id != request.id)
        .first()
    )
    if existing:
        raise DomainError(
            "EPISODE_ALREADY_ASSIGNED",
            f"Episode {episode.episode_id} is already assigned to request #{existing.request_id}",
        )
    # Already assigned to this very request -> idempotent no-op is friendlier than an error.
    duplicate = (
        db.query(Assignment)
        .filter(Assignment.request_id == request.id, Assignment.episode_id == episode.id)
        .first()
    )
    if duplicate:
        return duplicate

    assignment = Assignment(
        request_id=request.id,
        episode_id=episode.id,
        assigned_by_user_id=actor.id,
        assigned_at=_utcnow(),
    )
    db.add(assignment)
    try:
        db.commit()
    except Exception:
        # The DB unique constraint is the authority in a race; translate it.
        db.rollback()
        raise DomainError(
            "EPISODE_ALREADY_ASSIGNED",
            f"Episode {episode.episode_id} was just assigned to another request",
        ) from None
    db.refresh(request)
    return assignment


def unassign_episode(db: Session, request: Request, episode_pk: int, actor: User) -> None:
    """Remove an assignment (operator rework while not yet delivered)."""
    if actor.role not in (UserRole.OPERATOR, UserRole.ADMIN):
        raise DomainError("FORBIDDEN", "Only operators can unassign episodes", 403)
    if request.status not in (RequestStatus.SUBMITTED, RequestStatus.IN_PROGRESS,
                              RequestStatus.REJECTED):
        raise DomainError("NOT_ASSIGNABLE", "Cannot modify assignments after delivery")
    deleted = (
        db.query(Assignment)
        .filter(Assignment.request_id == request.id, Assignment.episode_id == episode_pk)
        .delete()
    )
    if not deleted:
        raise DomainError("ASSIGNMENT_NOT_FOUND", "That episode is not assigned to this request", 404)
    db.commit()


def create_request(db: Session, client: User, data) -> Request:
    request = Request(
        client_id=client.id,
        task_name=data.task_name.strip().lower(),
        episodes_requested=data.episodes_requested,
        deadline=data.deadline,
        notes=data.notes,
        status=RequestStatus.SUBMITTED,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    db.add(
        RequestStatusHistory(
            request_id=request.id,
            from_status=None,
            to_status=RequestStatus.SUBMITTED.value,
            changed_by_user_id=client.id,
            changed_at=_utcnow(),
        )
    )
    db.commit()
    return request

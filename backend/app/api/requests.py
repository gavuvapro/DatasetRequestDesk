"""Dataset request endpoints: creation, listing, transitions, assignments, history."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import CurrentUser, get_current_user
from app.database import get_db
from app.models import Assignment, Episode, Request, User
from app.models.request import RequestStatus
from app.models.user import UserRole
from app.schemas.request import (
    AssignEpisodeRequest,
    HistoryOut,
    RequestCreate,
    RequestOut,
    TransitionRequest,
)
from app.services import request_service
from app.services.request_service import DomainError

router = APIRouter(prefix="/api/requests", tags=["requests"])


def _to_out(db: Session, request: Request) -> RequestOut:
    client = request.client
    return RequestOut(
        id=request.id,
        client_id=request.client_id,
        client_name=client.name if client else None,
        task_name=request.task_name,
        episodes_requested=request.episodes_requested,
        deadline=request.deadline,
        notes=request.notes,
        status=request.status,
        created_at=request.created_at,
        updated_at=request.updated_at,
        assigned_count=len(request.assignments),
    )


def _get_visible_request(db: Session, request_id: int, user: User) -> Request:
    request = (
        db.query(Request)
        .options(joinedload(Request.client))
        .filter(Request.id == request_id)
        .first()
    )
    if not request:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Request not found")
    if user.role == UserRole.CLIENT and request.client_id != user.id:
        # 404 (not 403) so clients cannot even probe other clients' request ids.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Request not found")
    return request


@router.post("", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    body: RequestCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser,
):
    """Clients (and admins acting for a client) create dataset requests."""
    if current_user.role not in (UserRole.CLIENT, UserRole.ADMIN):
        raise DomainError("FORBIDDEN", "Only clients can create requests", status.HTTP_403_FORBIDDEN)
    return _to_out(db, request_service.create_request(db, current_user, body))


@router.get("", response_model=list[RequestOut])
def list_requests(
    status_filter: RequestStatus | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: CurrentUser,
):
    """Clients see only their own requests; operators/admins see all."""
    query = db.query(Request).options(joinedload(Request.client))
    if current_user.role == UserRole.CLIENT:
        query = query.filter(Request.client_id == current_user.id)
    if status_filter:
        query = query.filter(Request.status == status_filter)
    return [_to_out(db, r) for r in query.order_by(Request.created_at.desc()).all()]


@router.get("/{request_id}", response_model=RequestOut)
def get_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser,
):
    request = _get_visible_request(db, request_id, current_user)
    return _to_out(db, request)


@router.get("/{request_id}/history", response_model=list[HistoryOut])
def get_history(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser,
):
    request = _get_visible_request(db, request_id, current_user)
    return list(request.status_history)


@router.get("/{request_id}/assignments")
def get_assignments(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser,
):
    """List episodes assigned to a request (visible to owner client + operators)."""
    request = _get_visible_request(db, request_id, current_user)
    return [
        {
            "id": a.id,
            "episode_pk": a.episode_id,
            "episode_id": a.episode.episode_id,
            "robot_id": a.episode.robot_id,
            "task_name": a.episode.task_name,
            "quality": a.episode.quality.value,
            "duration_seconds": a.episode.duration_seconds,
            "assigned_by_user_id": a.assigned_by_user_id,
            "assigned_at": a.assigned_at,
        }
        for a in request.assignments
    ]


@router.post("/{request_id}/transition", response_model=RequestOut)
def transition_request(
    request_id: int,
    body: TransitionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser,
):
    """Move a request through its state machine.

    Operators: submitted->in_progress->delivered, rejected->in_progress.
    Owner client: delivered->accepted / delivered->rejected.
    """
    request = _get_visible_request(db, request_id, current_user)
    try:
        updated = request_service.apply_transition(db, request, body.to_status, current_user)
    except DomainError as exc:
        raise exc
    return _to_out(db, updated)


@router.post("/{request_id}/assign", response_model=list[dict])
def assign_episode(
    request_id: int,
    body: AssignEpisodeRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser,
):
    """Assign one episode to a request (operator/admin only)."""
    if current_user.role not in (UserRole.OPERATOR, UserRole.ADMIN):
        raise DomainError("FORBIDDEN", "Only operators can assign episodes", status.HTTP_403_FORBIDDEN)
    request = _get_visible_request(db, request_id, current_user)
    episode = db.get(Episode, body.episode_id)
    if not episode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Episode not found")
    try:
        request_service.assign_episode(db, request, episode, current_user)
    except DomainError as exc:
        raise exc
    return [
        {
            "id": a.id,
            "episode_id": a.episode.episode_id,
            "quality": a.episode.quality.value,
        }
        for a in db.query(Assignment)
        .filter(Assignment.request_id == request.id)
        .options(joinedload(Assignment.episode))
        .all()
    ]


@router.delete("/{request_id}/assign/{episode_pk}", status_code=status.HTTP_204_NO_CONTENT)
def unassign_episode(
    request_id: int,
    episode_pk: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser,
):
    """Remove an assignment (operator rework before delivery)."""
    if current_user.role not in (UserRole.OPERATOR, UserRole.ADMIN):
        raise DomainError("FORBIDDEN", "Only operators can unassign episodes", status.HTTP_403_FORBIDDEN)
    request = _get_visible_request(db, request_id, current_user)
    request_service.unassign_episode(db, request, episode_pk, current_user)

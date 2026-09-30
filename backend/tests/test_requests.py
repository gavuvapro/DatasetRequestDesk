"""Request lifecycle tests: transitions, assignment rules, audit trail."""
import pytest

from app.models.assignment import Assignment
from app.services.request_service import DomainError, apply_transition, assign_episode

from tests.conftest import make_episode, make_request


def test_valid_happy_path(db, client_a, operator):
    req = make_request(db, client_a, count=2)
    apply_transition(db, req, "in_progress", operator)
    ep1 = make_episode(db, "EP-A1")
    ep2 = make_episode(db, "EP-A2", quality="usable")
    assign_episode(db, req, ep1, operator)
    assign_episode(db, req, ep2, operator)
    apply_transition(db, req, "delivered", operator)
    apply_transition(db, req, "accepted", client_a)
    assert req.status.value == "accepted"
    assert len(req.status_history) == 4  # submitted, in_progress, delivered, accepted


def test_invalid_transition_submitted_to_delivered(db, client_a, operator):
    req = make_request(db, client_a)
    with pytest.raises(DomainError):
        apply_transition(db, req, "delivered", operator)


def test_accepted_is_terminal(db, client_a, operator):
    req = make_request(db, client_a, status="accepted")
    with pytest.raises(DomainError):
        apply_transition(db, req, "in_progress", operator)


def test_delivered_requires_enough_assignments(db, client_a, operator):
    req = make_request(db, client_a, count=2)
    apply_transition(db, req, "in_progress", operator)
    assign_episode(db, req, make_episode(db, "EP-B1"), operator)
    with pytest.raises(DomainError) as exc:
        apply_transition(db, req, "delivered", operator)
    assert "needs 2" in exc.value.detail


def test_client_cannot_start_progress(db, client_a):
    req = make_request(db, client_a)
    with pytest.raises(DomainError):
        apply_transition(db, req, "in_progress", client_a)


def test_operator_cannot_accept(db, client_a, operator):
    req = make_request(db, client_a, status="delivered")
    with pytest.raises(DomainError):
        apply_transition(db, req, "accepted", operator)


def test_client_cannot_accept_other_clients_request(db, client_a, client_b):
    req = make_request(db, client_a, status="delivered")
    with pytest.raises(DomainError):
        apply_transition(db, req, "accepted", client_b)


def test_rejection_and_rework_cycle(db, client_a, operator):
    req = make_request(db, client_a, count=1)
    apply_transition(db, req, "in_progress", operator)
    assign_episode(db, req, make_episode(db, "EP-C1"), operator)
    apply_transition(db, req, "delivered", operator)
    apply_transition(db, req, "rejected", client_a)
    apply_transition(db, req, "in_progress", operator)  # rework
    assert req.status.value == "in_progress"
    # After rework the episode is still assigned; unassign then re-deliver flow works.
    apply_transition(db, req, "delivered", operator)
    assert req.status.value == "delivered"


def test_bad_quality_episode_cannot_be_assigned(db, client_a, operator):
    req = make_request(db, client_a)
    ep = make_episode(db, "EP-D1", quality="bad")
    with pytest.raises(DomainError) as exc:
        assign_episode(db, req, ep, operator)
    assert "good" in exc.value.detail


def test_episode_cannot_be_assigned_to_two_requests(db, client_a, client_b, operator):
    req1 = make_request(db, client_a)
    req2 = make_request(db, client_b)
    ep = make_episode(db, "EP-E1")
    assign_episode(db, req1, ep, operator)
    with pytest.raises(DomainError) as exc:
        assign_episode(db, req2, ep, operator)
    assert "already assigned" in exc.value.detail


def test_double_assignment_unique_constraint_at_db_level(db, client_a, operator):
    """The unique constraint must hold even if service checks are bypassed."""
    from sqlalchemy.exc import IntegrityError

    req = make_request(db, client_a)
    ep = make_episode(db, "EP-F1")
    db.add(
        Assignment(
            request_id=req.id,
            episode_id=ep.id,
            assigned_by_user_id=operator.id,
        )
    )
    db.commit()
    db.add(
        Assignment(
            request_id=req.id,
            episode_id=ep.id,
            assigned_by_user_id=operator.id,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_reassign_same_episode_is_idempotent(db, client_a, operator):
    req = make_request(db, client_a)
    ep = make_episode(db, "EP-G1")
    a1 = assign_episode(db, req, ep, operator)
    a2 = assign_episode(db, req, ep, operator)
    assert a1.id == a2.id


def test_unassign_episode(db, client_a, operator):
    req = make_request(db, client_a)
    ep = make_episode(db, "EP-H1")
    assign_episode(db, req, ep, operator)
    from app.services.request_service import unassign_episode

    unassign_episode(db, req, ep.id, operator)
    assert db.query(Assignment).filter(Assignment.request_id == req.id).count() == 0


def test_history_records_actor_and_timestamps(db, client_a, operator):
    req = make_request(db, client_a)
    apply_transition(db, req, "in_progress", operator)
    entry = req.status_history[-1]
    assert entry.from_status == "submitted"
    assert entry.to_status == "in_progress"
    assert entry.changed_by_user_id == operator.id
    assert entry.changed_at is not None

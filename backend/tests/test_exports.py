"""Export job (stretch item) tests: idempotent creation, retries, RBAC."""
from unittest.mock import patch

import pytest

from app.models import ExportJob, ExportStatus
from app.services import export_worker
from app.services.export_worker import ensure_job, process_pending_jobs
from app.services.request_service import assign_episode

from tests.conftest import login_headers, make_episode, make_request


def test_job_created_on_assignment(db, client_a, operator):
    req = make_request(db, client_a)
    ep = make_episode(db, "EP-X1")
    assignment = assign_episode(db, req, ep, operator)
    jobs = db.query(ExportJob).filter(ExportJob.assignment_id == assignment.id).all()
    assert len(jobs) == 1
    assert jobs[0].status == ExportStatus.QUEUED


def test_job_creation_is_idempotent(db, client_a, operator):
    req = make_request(db, client_a)
    ep = make_episode(db, "EP-X2")
    assignment = assign_episode(db, req, ep, operator)
    first = db.query(ExportJob).filter(ExportJob.assignment_id == assignment.id).one()
    again = ensure_job(db, assignment)
    assert again.id == first.id
    count = db.query(ExportJob).filter(ExportJob.assignment_id == assignment.id).count()
    assert count == 1


def test_processing_succeeds_and_marks_done(db, client_a, operator):
    req = make_request(db, client_a)
    ep = make_episode(db, "EP-X3")
    assignment = assign_episode(db, req, ep, operator)

    with patch.object(export_worker.random, "uniform", return_value=0.1), \
         patch.object(export_worker.random, "random", return_value=0.99):  # never fails
        process_pending_jobs(once=True)

    job = db.query(ExportJob).filter(ExportJob.assignment_id == assignment.id).one()
    assert job.status == ExportStatus.DONE
    assert job.attempts == 1
    assert job.finished_at is not None


def _job_for(db, assignment_id):
    """Re-read a job with fresh state (worker sessions update it externally).

    The commit ends this session's read transaction so the next SELECT sees
    the worker's latest commit rather than a stale SQLite snapshot.
    """
    db.commit()
    db.expire_all()
    return db.query(ExportJob).filter(ExportJob.assignment_id == assignment_id).one()


def test_failure_is_retried(db, client_a, operator):
    req = make_request(db, client_a)
    ep = make_episode(db, "EP-X4")
    assignment = assign_episode(db, req, ep, operator)

    # Fail twice, then succeed.
    with patch.object(export_worker.random, "uniform", return_value=0.1), \
         patch.object(export_worker.random, "random", return_value=0.0):
        process_pending_jobs(once=True)
        job = _job_for(db, assignment.id)
        assert job.status == ExportStatus.FAILED
        assert job.attempts == 1

        process_pending_jobs(once=True)
        job = _job_for(db, assignment.id)
        assert job.status == ExportStatus.FAILED
        assert job.attempts == 2

    with patch.object(export_worker.random, "uniform", return_value=0.1), \
         patch.object(export_worker.random, "random", return_value=0.99):
        process_pending_jobs(once=True)

    job = _job_for(db, assignment.id)
    assert job.status == ExportStatus.DONE
    assert job.attempts == 3


def test_retries_are_capped(db, client_a, operator):
    req = make_request(db, client_a)
    ep = make_episode(db, "EP-X5")
    assignment = assign_episode(db, req, ep, operator)

    with patch.object(export_worker.random, "uniform", return_value=0.1), \
         patch.object(export_worker.random, "random", return_value=0.0):  # always fails
        for _ in range(5):
            process_pending_jobs(once=True)

    job = _job_for(db, assignment.id)
    assert job.status == ExportStatus.FAILED
    assert job.attempts == job.max_attempts


def _mk_other_client(db):
    from tests.conftest import make_user

    return make_user(db, "tmp-exp@example.com", "client")


def test_retry_endpoint_requeues_failed_job(client, db, client_a, operator, client_a_headers=None):
    other = _mk_other_client(db)
    req = make_request(db, other)
    ep = make_episode(db, "EP-X6")
    assign_episode(db, req, ep, operator)

    with patch.object(export_worker.random, "uniform", return_value=0.1), \
         patch.object(export_worker.random, "random", return_value=0.0):
        process_pending_jobs(once=True)
    job = db.query(ExportJob).filter(ExportJob.episode_id == ep.id).one()
    assert job.status == ExportStatus.FAILED

    ops_headers = login_headers(client, operator.email)
    res = client.post(f"/api/requests/{req.id}/assign/{ep.id}/retry-export", headers=ops_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "queued"
    assert res.json()["attempts"] == 0


def test_retry_endpoint_rejects_done_job(client, db, client_a, operator):
    req = make_request(db, client_a)
    ep = make_episode(db, "EP-X7")
    assign_episode(db, req, ep, operator)

    with patch.object(export_worker.random, "uniform", return_value=0.1), \
         patch.object(export_worker.random, "random", return_value=0.99):
        process_pending_jobs(once=True)

    ops_headers = login_headers(client, operator.email)
    res = client.post(f"/api/requests/{req.id}/assign/{ep.id}/retry-export", headers=ops_headers)
    assert res.status_code == 409


def test_client_cannot_retry_export(client, db, client_a, operator):
    req = make_request(db, client_a)
    ep = make_episode(db, "EP-X8")
    assign_episode(db, req, ep, operator)

    client_headers = login_headers(client, client_a.email)
    res = client.post(
        f"/api/requests/{req.id}/assign/{ep.id}/retry-export", headers=client_headers
    )
    assert res.status_code == 403


def test_assignments_api_includes_export_status(client, db, client_a, operator):
    req = make_request(db, client_a)
    ep = make_episode(db, "EP-X9")
    assign_episode(db, req, ep, operator)

    with patch.object(export_worker.random, "uniform", return_value=0.1), \
         patch.object(export_worker.random, "random", return_value=0.99):
        process_pending_jobs(once=True)

    ops_headers = login_headers(client, operator.email)
    res = client.get(f"/api/requests/{req.id}/assignments", headers=ops_headers)
    assert res.status_code == 200
    row = res.json()[0]
    assert row["export"]["status"] == "done"
    assert row["export"]["attempts"] == 1


def test_unassign_removes_export_job(db, client_a, operator):
    from app.services.request_service import unassign_episode

    req = make_request(db, client_a)
    ep = make_episode(db, "EP-X10")
    assign_episode(db, req, ep, operator)
    assert db.query(ExportJob).count() == 1

    unassign_episode(db, req, ep.id, operator)
    assert db.query(ExportJob).count() == 0


def test_worker_disabled_in_tests(client):
    """The sleeping background thread must never run under pytest."""
    from app.config import get_settings

    assert get_settings().export_worker_enabled is False

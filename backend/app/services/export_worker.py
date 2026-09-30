"""Background export worker (stretch item).

Simulates an export pipeline: each assignment gets exactly one job (UNIQUE
constraint = idempotency anchor). The worker claims QUEUED/FAILED jobs that
haven't exhausted retries, "works" them for 2-5s, and fails ~20% of the time.
Failures stay retryable: FAILED jobs with attempts left are re-claimed.

Safety properties:
- Idempotent creation: `ensure_job` is only ever called with a fresh
  Assignment; the UNIQUE(assignment_id) constraint backstops any race.
- Atomic claiming: each job row is claimed via UPDATE ... WHERE status IN
  (queued, failed) - two workers can never grab the same job.
- Crash safety: if the process dies mid-run, the job stays `running` with a
  stale updated_at and is reclaimed after a timeout (crash recovery).
"""
import logging
import random
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ExportJob, ExportStatus

logger = logging.getLogger("app.export_worker")

CLAIM_TIMEOUT_SECONDS = 60  # a `running` job older than this is considered dead
FAILURE_PROBABILITY = 0.2
WORK_MIN_SECONDS = 2
WORK_MAX_SECONDS = 5


def ensure_job(db: Session, assignment) -> ExportJob:
    """Idempotently create the export job for a fresh assignment.

    Called from the assignment flow where we hold a fresh, unique assignment,
    so INSERT normally succeeds; the UNIQUE constraint backstops any race.
    """
    job = ExportJob(
        assignment_id=assignment.id,
        episode_id=assignment.episode_id,
        request_id=assignment.request_id,
        status=ExportStatus.QUEUED,
        attempts=0,
    )
    db.add(job)
    try:
        db.commit()
    except Exception:
        db.rollback()
        existing = (
            db.query(ExportJob).filter(ExportJob.assignment_id == assignment.id).first()
        )
        if existing:
            return existing
        raise
    db.refresh(job)
    return job


def remove_job(db: Session, request_id: int, episode_pk: int) -> int:
    """Delete the export job for a (request, episode) pair being unassigned."""
    deleted = (
        db.query(ExportJob)
        .filter(ExportJob.request_id == request_id, ExportJob.episode_id == episode_pk)
        .delete()
    )
    db.commit()
    return deleted


def _claim_job(db: Session) -> ExportJob | None:
    """Atomically claim one runnable job, or return None.

    Claimable:
    - QUEUED: always (fresh work or an operator re-queue).
    - FAILED: immediate retry while attempts remain (a real deployment would
      add exponential backoff via a `next_attempt_at` column).
    - RUNNING: only if stale (crash recovery - the worker died mid-job).
    """
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(seconds=CLAIM_TIMEOUT_SECONDS)
    claimable = or_(
        and_(ExportJob.status == ExportStatus.QUEUED),
        and_(
            ExportJob.status == ExportStatus.FAILED,
            ExportJob.attempts < ExportJob.max_attempts,
        ),
        and_(
            ExportJob.status == ExportStatus.RUNNING,
            ExportJob.updated_at < stale_cutoff,
        ),
    )
    job = (
        db.execute(
            select(ExportJob)
            .where(claimable)
            .order_by(ExportJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .first()
    )
    if job is None:
        return None
    job.status = ExportStatus.RUNNING
    job.attempts += 1
    job.updated_at = now
    db.commit()
    return job


def _do_export(job: ExportJob) -> None:
    """Simulate the export work: 2-5s, 20% failure. Returns normally on success."""
    time.sleep(random.uniform(WORK_MIN_SECONDS, WORK_MAX_SECONDS))
    if random.random() < FAILURE_PROBABILITY:
        raise RuntimeError("simulated export failure (20% rollout)")


def process_pending_jobs(once: bool = False) -> int:
    """Claim and run jobs until the queue is empty (or once, for tests)."""
    from app.database import get_session_factory

    processed = 0
    while True:
        factory: sessionmaker = get_session_factory()
        db = factory()
        try:
            job = _claim_job(db)
            if job is None:
                return processed
            job_id = job.id
        finally:
            db.close()

        # Heavy/slow work happens on its own session, like a real worker.
        db = factory()
        try:
            job = db.get(ExportJob, job_id)
            try:
                _do_export(job)
                job.status = ExportStatus.DONE
                job.last_error = None
            except Exception as exc:  # noqa: BLE001 - simulated failure
                job.status = ExportStatus.FAILED
                job.last_error = str(exc)[:500]
            job.updated_at = datetime.now(timezone.utc)
            if job.status == ExportStatus.DONE:
                job.finished_at = job.updated_at
            db.commit()
            processed += 1
            logger.info(
                "export job finished",
                extra={"extra_fields": {
                    "event": "export_job",
                    "job_id": job_id,
                    "status": job.status.value,
                    "attempts": job.attempts,
                }},
            )
        finally:
            db.close()
        if once:
            return processed


def start_worker_thread(poll_interval: float = 2.0) -> threading.Thread:
    """Start the daemon polling loop (used by FastAPI startup)."""

    def _loop() -> None:
        while True:
            try:
                processed = process_pending_jobs()
                if processed == 0:
                    time.sleep(poll_interval)
            except Exception:  # noqa: BLE001 - a worker must never die
                logger.exception("export worker loop error")
                time.sleep(poll_interval)

    thread = threading.Thread(target=_loop, name="export-worker", daemon=True)
    thread.start()
    return thread

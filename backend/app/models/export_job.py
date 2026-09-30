"""ExportJob: simulated background export of an assigned episode.

Stretch item: on assignment, each episode goes through a simulated export job
(sleep 2-5s, fails randomly 20% of the time). One job per assignment - the
UNIQUE constraint on assignment_id is the idempotency anchor, so creating a job
twice for the same assignment can never duplicate work.
"""
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.user import utcnow


class ExportStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ExportJob(Base):
    __tablename__ = "export_jobs"
    __table_args__ = (
        UniqueConstraint("assignment_id", name="uq_export_jobs_assignment_id"),
        Index("ix_export_jobs_status", "status"),
        Index("ix_export_jobs_request", "request_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id"), nullable=False
    )
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), nullable=False)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), nullable=False)
    status: Mapped[ExportStatus] = mapped_column(
        Enum(
            ExportStatus,
            name="export_status",
            native_enum=False,
            length=10,
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ExportStatus.QUEUED,
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assignment: Mapped["Assignment"] = relationship(lazy="joined")  # noqa: F821
    episode: Mapped["Episode"] = relationship(lazy="joined")  # noqa: F821

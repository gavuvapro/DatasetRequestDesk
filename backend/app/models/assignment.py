"""Assignment model: an episode allocated to a dataset request.

The UNIQUE constraint on episode_id enforces "an episode is assigned to at most
one request at a time" at the database level, not just in application code.
"""
from datetime import datetime  # noqa: F401 - used in Mapped[] annotations

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.user import utcnow


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("episode_id", name="uq_assignments_episode_id"),
        Index("ix_assignments_request", "request_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), nullable=False)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), nullable=False)
    assigned_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    request: Mapped["Request"] = relationship(back_populates="assignments")  # noqa: F821
    episode: Mapped["Episode"] = relationship(lazy="joined")  # noqa: F821

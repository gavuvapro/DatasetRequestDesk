"""Dataset request lifecycle model and its audit trail."""
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.user import utcnow


class RequestStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    task_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    episodes_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RequestStatus] = mapped_column(
        Enum(
            RequestStatus,
            name="request_status",
            native_enum=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],  # store 'submitted', not 'SUBMITTED'
        ),
        default=RequestStatus.SUBMITTED,
        index=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    client: Mapped["User"] = relationship(lazy="joined")  # noqa: F821
    assignments: Mapped[list["Assignment"]] = relationship(  # noqa: F821
        back_populates="request", cascade="all, delete-orphan", lazy="selectin"
    )
    status_history: Mapped[list["RequestStatusHistory"]] = relationship(  # noqa: F821
        back_populates="request", cascade="all, delete-orphan",
        order_by="RequestStatusHistory.changed_at", lazy="selectin",
    )


class RequestStatusHistory(Base):
    __tablename__ = "request_status_history"
    __table_args__ = (Index("ix_history_request_changed", "request_id", "changed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    request: Mapped["Request"] = relationship(back_populates="status_history")  # noqa: F821

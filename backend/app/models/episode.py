"""Episode model: one recorded robot demonstration clip."""
import enum

from sqlalchemy import DateTime, Enum, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import utcnow


class EpisodeQuality(str, enum.Enum):
    GOOD = "good"
    USABLE = "usable"
    BAD = "bad"


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        # Composite index for analytics: per-day/per-robot/quality rollups at 5M-row scale.
        Index("ix_episodes_recorded_at_robot_quality", "recorded_at", "robot_id", "quality"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    robot_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    task_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    operator_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quality: Mapped[EpisodeQuality] = mapped_column(
        Enum(EpisodeQuality, name="episode_quality", native_enum=False, length=10),
        index=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

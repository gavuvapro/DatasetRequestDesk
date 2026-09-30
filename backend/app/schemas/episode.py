"""Pydantic schemas for episodes and CSV import."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.episode import EpisodeQuality


class EpisodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    episode_id: str
    robot_id: str
    task_name: str
    recorded_at: datetime
    duration_seconds: int
    operator_name: str
    quality: EpisodeQuality


class EpisodePage(BaseModel):
    items: list[EpisodeOut]
    total: int
    limit: int
    offset: int


class ImportReport(BaseModel):
    """Detailed result of a CSV import run."""

    imported: int
    skipped: int
    errors: list[str] = Field(default_factory=list)

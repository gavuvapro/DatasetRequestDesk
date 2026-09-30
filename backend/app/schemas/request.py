"""Pydantic schemas for dataset requests, transitions, and assignments."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.request import RequestStatus


class RequestCreate(BaseModel):
    task_name: str = Field(min_length=1, max_length=255)
    episodes_requested: int = Field(ge=1, le=100_000)
    deadline: datetime
    notes: str | None = Field(None, max_length=5_000)


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    client_name: str | None = None
    task_name: str
    episodes_requested: int
    deadline: datetime
    notes: str | None
    status: RequestStatus
    created_at: datetime
    updated_at: datetime
    assigned_count: int = 0


class TransitionRequest(BaseModel):
    to_status: RequestStatus


class AssignEpisodeRequest(BaseModel):
    episode_id: int = Field(description="Numeric primary key from GET /api/episodes")


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_status: str | None
    to_status: str
    changed_by_user_id: int
    changed_at: datetime

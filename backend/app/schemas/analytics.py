"""Analytics response schemas."""
from pydantic import BaseModel


class EpisodesPerDayRobot(BaseModel):
    day: str
    robot_id: str
    episodes: int


class RequestsByStatus(BaseModel):
    status: str
    count: int


class MedianFulfilment(BaseModel):
    median_hours_submitted_to_delivered: float | None
    sample_size: int


class TopTask(BaseModel):
    task_name: str
    good_episodes: int


class AnalyticsResponse(BaseModel):
    range_days: int
    episodes_per_day_robot: list[EpisodesPerDayRobot]
    requests_by_status: list[RequestsByStatus]
    median_fulfilment: MedianFulfilment
    top_tasks: list[TopTask]
    engine: str  # "postgres" or "sqlite" (tests/local)

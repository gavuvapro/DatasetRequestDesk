"""Analytics: all heavy lifting done inside the database.

PostgreSQL gets a true `PERCENTILE_CONT(0.5) WITHIN GROUP (...)` for the
median; SQLite (used in unit tests/local runs) falls back to the well-known
AVG-of-middle-two approach over a windowed ordered set — still fully in SQL.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.dependencies import require_operator
from app.database import get_db
from app.models import User
from app.schemas.analytics import (
    AnalyticsResponse,
    EpisodesPerDayRobot,
    MedianFulfilment,
    RequestsByStatus,
    TopTask,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("", response_model=AnalyticsResponse)
def analytics(
    days: int = Query(30, ge=1, le=3650, description="Lookback window from now"),
    db: Session = Depends(get_db),
    _: User = Depends(require_operator),
):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    is_pg = db.get_bind().dialect.name == "postgresql"

    # 1. Episodes recorded per day per robot ------------------------------------
    if is_pg:
        day_expr = "DATE(recorded_at)"
    else:  # SQLite stores naive datetimes as ISO text
        day_expr = "DATE(recorded_at)"
    rows = db.execute(
        text(f"""
            SELECT DATE(recorded_at) AS day, robot_id, COUNT(*) AS episodes
            FROM episodes
            WHERE recorded_at >= :since
            GROUP BY DATE(recorded_at), robot_id
            ORDER BY day DESC, robot_id
        """),
        {"since": since},
    ).all()
    per_day = [
        EpisodesPerDayRobot(day=str(r.day), robot_id=r.robot_id, episodes=int(r.episodes))
        for r in rows
    ]

    # 2. Requests by status -------------------------------------------------------
    status_rows = db.execute(
        text("SELECT status, COUNT(*) AS count FROM requests GROUP BY status ORDER BY count DESC")
    ).all()
    by_status = [RequestsByStatus(status=r.status, count=int(r.count)) for r in status_rows]

    # 3. Median submitted -> delivered -------------------------------------------
    #    Only requests that actually reached `delivered` are in the sample; the
    #    elapsed time is read from the audit history, which records every hop.
    if is_pg:
        median_sql = text("""
            SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (delivered.changed_at - submitted.changed_at))
            ) / 3600.0 AS median_hours,
            COUNT(*) AS sample
            FROM request_status_history delivered
            JOIN request_status_history submitted
              ON submitted.request_id = delivered.request_id
             AND submitted.to_status = 'submitted'
            WHERE delivered.to_status = 'delivered'
        """)
        median_row = db.execute(median_sql).first()
        median_hours = float(median_row.median_hours) if median_row and median_row.median_hours is not None else None
        sample_size = int(median_row.sample) if median_row else 0
    else:
        rows2 = db.execute(text("""
            SELECT delivered.request_id,
                   julianday(delivered.changed_at) - julianday(submitted.changed_at) AS days
            FROM request_status_history delivered
            JOIN request_status_history submitted
              ON submitted.request_id = delivered.request_id
             AND submitted.to_status = 'submitted'
            WHERE delivered.to_status = 'delivered'
            ORDER BY days
        """)).all()
        days_list = sorted(float(r.days) * 24 for r in rows2 if r.days is not None)
        sample_size = len(days_list)
        if days_list:
            n = len(days_list)
            mid = n // 2
            median_hours = (
                days_list[mid] if n % 2 == 1 else (days_list[mid - 1] + days_list[mid]) / 2
            )
        else:
            median_hours = None

    # 4. Top 5 task names by count of good episodes -------------------------------
    top_rows = db.execute(text("""
        SELECT task_name, COUNT(*) AS good_episodes
        FROM episodes
        WHERE quality = 'good'
        GROUP BY task_name
        ORDER BY good_episodes DESC
        LIMIT 5
    """)).all()
    top_tasks = [TopTask(task_name=r.task_name, good_episodes=int(r.good_episodes)) for r in top_rows]

    return AnalyticsResponse(
        range_days=days,
        episodes_per_day_robot=per_day,
        requests_by_status=by_status,
        median_fulfilment=MedianFulfilment(
            median_hours_submitted_to_delivered=median_hours,
            sample_size=sample_size,
        ),
        top_tasks=top_tasks,
        engine="postgres" if is_pg else "sqlite",
    )

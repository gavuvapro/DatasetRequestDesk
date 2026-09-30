"""Episode browsing and CSV import endpoints."""
import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.dependencies import require_operator
from app.database import get_db
from app.models import Episode, User
from app.models.episode import EpisodeQuality
from app.schemas.episode import EpisodePage, ImportReport
from app.services.import_service import import_csv

router = APIRouter(prefix="/api/episodes", tags=["episodes"])

MAX_UPLOAD_BYTES = 512 * 1024 * 1024  # 512 MB


@router.get("", response_model=EpisodePage)
def list_episodes(
    task_name: str | None = Query(None, description="Case-insensitive substring match"),
    quality: EpisodeQuality | None = None,
    robot_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_operator),
):
    """Operator/admin only: paginated episode list with filters."""
    query = db.query(Episode)
    if task_name:
        query = query.filter(Episode.task_name.ilike(f"%{task_name.strip().lower()}%"))
    if quality:
        query = query.filter(Episode.quality == quality)
    if robot_id:
        query = query.filter(Episode.robot_id == robot_id.strip().lower())
    total = query.count()
    items = query.order_by(Episode.recorded_at.desc()).offset(offset).limit(limit).all()
    return EpisodePage(items=items, total=total, limit=limit, offset=offset)


@router.post("/import", response_model=ImportReport)
async def import_episodes_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_operator),
):
    """Import a messy episodes CSV. Idempotent: re-running reports only skips."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Upload a .csv file")

    size = 0
    tmp_path = ""
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
        tmp_path = tmp.name
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                os.unlink(tmp_path)
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")
            tmp.write(chunk)

    try:
        report = import_csv(db, tmp_path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return ImportReport(**report)

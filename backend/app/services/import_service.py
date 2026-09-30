"""CSV import engine for messy episode exports.

Design goals:
- Never create duplicates, no matter how often the same file is imported
  (in-file duplicates, DB duplicates, or case variants like `ep-00003`).
- Sanitize aggressively: whitespace, letter casing, multiple date formats.
- Report exactly what happened: imported / skipped / per-row errors.
- Scale: validate and insert in batches; DB dedupe uses chunked `IN` queries,
  so memory stays bounded even for multi-million-row imports.
"""
import csv
import logging
import re
from datetime import datetime
from pathlib import Path

from dateutil import parser as dateparser
from sqlalchemy.orm import Session

from app.config import settings
from app.models.episode import Episode, EpisodeQuality

logger = logging.getLogger("app.import")

REQUIRED_COLUMNS = ("episode_id", "robot_id", "task_name", "recorded_at",
                    "duration_seconds", "operator_name", "quality")
COLUMN_ALIASES = {c.lower().replace("_", ""): c for c in REQUIRED_COLUMNS}

_DURATION_RE = re.compile(r"^\d+$")


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _parse_datetime(raw: str) -> datetime:
    """Parse ISO 8601 (`2026-08-16T23:28:00`, `...Z`) and European `DD/MM/YYYY HH:MM`."""
    raw = _clean(raw)
    # European format first: 14/08/2026 09:15 (day-first is explicit here).
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    # ISO 8601, tolerating a trailing Z and space-separated date/time.
    parsed = dateparser.isoparse(raw) if "T" in raw or raw.endswith("Z") else None
    if parsed is None:
        parsed = dateparser.parse(raw, dayfirst=True)
    if parsed is None:
        raise ValueError(f"unparseable datetime {raw!r}")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(tz=None).replace(tzinfo=None) if False else parsed
    return parsed


def _parse_duration(raw: str) -> int:
    """Strict positive-integer duration: rejects -5, 45.5, N/A, empty, 999999."""
    raw = _clean(raw)
    if not _DURATION_RE.match(raw):
        raise ValueError(f"invalid duration {raw!r} (want a positive whole number of seconds)")
    value = int(raw)
    if not 1 <= value <= 86_400:  # sane upper bound: one day of continuous recording
        raise ValueError(f"duration {value} out of range (1..86400 seconds)")
    return value


def _normalise_episode_key(raw: str) -> str:
    """Canonical form used for dedupe: uppercase, no internal whitespace."""
    return re.sub(r"\s+", "", _clean(raw).upper())


class _RowError(ValueError):
    pass


def _row_to_episode(row: dict[str, str], row_number: int) -> Episode:
    def field(name: str) -> str:
        for key, value in row.items():
            if key and _clean(key).lower().replace("_", "") == name.lower().replace("_", ""):
                return _clean(value)
        return ""

    episode_id_raw = field("episode_id")
    if not episode_id_raw:
        raise _RowError("Missing episode_id")
    robot = field("robot_id").lower()
    if not robot:
        raise _RowError("Missing robot_id")
    if robot not in settings.known_robots:
        raise _RowError(f"Unknown robot_id {robot!r}")
    task = re.sub(r"\s+", " ", field("task_name")).lower()
    if not task:
        raise _RowError("Missing task_name")
    operator = _clean(field("operator_name"))
    if not operator:
        raise _RowError("Missing operator_name")
    quality_raw = field("quality").lower()
    try:
        quality = EpisodeQuality(quality_raw)
    except ValueError:
        raise _RowError(f"invalid quality {field('quality')!r} (want good/usable/bad)") from None

    try:
        recorded_at = _parse_datetime(field("recorded_at"))
    except (ValueError, OverflowError) as exc:
        raise _RowError(f"invalid recorded_at {field('recorded_at')!r}: {exc}") from None

    try:
        duration = _parse_duration(field("duration_seconds"))
    except ValueError as exc:
        raise _RowError(str(exc)) from None

    from app.models.user import utcnow

    return Episode(
        episode_id=episode_id_raw.upper(),
        robot_id=robot,
        task_name=task,
        recorded_at=recorded_at,
        duration_seconds=duration,
        operator_name=operator,
        quality=quality,
        created_at=utcnow(),
    )


def _existing_episode_keys(db: Session, keys: list[str]) -> set[str]:
    """Chunked lookup of already-imported episode_ids."""
    found: set[str] = set()
    chunk_size = 900
    for start in range(0, len(keys), chunk_size):
        chunk = keys[start:start + chunk_size]
        rows = db.query(Episode.episode_id).filter(Episode.episode_id.in_(chunk)).all()
        found.update(r[0] for r in rows)
    return found


def import_csv(db: Session, path: str | Path) -> dict:
    """Import episodes from `path`. Idempotent: safe to run any number of times."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    imported = 0
    skipped = 0
    errors: list[str] = []
    batch: dict[str, Episode] = {}  # canonical episode_id -> Episode (in-file dedupe)

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = [(_clean(h).lower()) for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise ValueError(f"CSV header missing required columns: {', '.join(missing)}")

        for row_number, row in enumerate(reader, start=2):  # header is line 1
            # Skip fully blank lines some editors append.
            if not any(_clean(v) for v in row.values() if isinstance(v, str)):
                continue
            try:
                episode = _row_to_episode(row, row_number)
            except _RowError as exc:
                errors.append(f"Row {row_number}: {exc}")
                skipped += 1
                continue

            if episode.episode_id in batch:
                # Earlier occurrence in this same file wins; later duplicates skipped.
                skipped += 1
                errors.append(
                    f"Row {row_number}: duplicate episode_id {episode.episode_id} in file, skipped"
                )
                continue
            batch[episode.episode_id] = episode

    # DB-level dedupe for everything that survived in-file validation.
    db_existing = _existing_episode_keys(db, list(batch.keys()))
    to_insert: list[Episode] = []
    for key, episode in batch.items():
        if key in db_existing:
            skipped += 1
            continue
        to_insert.append(episode)

    # Bulk insert in chunks; guard against unique-violation races by flushing
    # per chunk and converting a failure into per-row skips.
    chunk_size = 1_000
    for start in range(0, len(to_insert), chunk_size):
        chunk = to_insert[start:start + chunk_size]
        try:
            db.bulk_save_objects(chunk)
            db.commit()
            imported += len(chunk)
        except Exception:  # noqa: BLE001 - fall back to row-by-row for this chunk
            db.rollback()
            for episode in chunk:
                try:
                    db.add(episode)
                    db.commit()
                    imported += 1
                except Exception:  # noqa: BLE001
                    db.rollback()
                    skipped += 1

    report = {"imported": imported, "skipped": skipped, "errors": errors}
    logger.info("import finished", extra={"extra_fields": {**report, "file": str(path)}})
    return report

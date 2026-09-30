"""Shared fixtures: isolated SQLite DB, seeded users, authenticated API clients."""
import os
import tempfile
from pathlib import Path

# Configure the app BEFORE it is imported anywhere: an isolated SQLite file per
# test session. (Analytics uses the SQLite fallback path; the Postgres branch is
# exercised in Docker - see docs/TESTING_GUIDE.md.)
_TEST_DB = os.path.join(tempfile.gettempdir(), "drd_test_session.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, get_engine  # noqa: E402
from app.models import (  # noqa: E402
    Assignment,
    Episode,
    Request,
    RequestStatusHistory,
    User,
)
from app.models.episode import EpisodeQuality  # noqa: E402
from app.models.request import RequestStatus  # noqa: E402
from app.models.user import UserRole  # noqa: E402
from app.core.security import hash_password  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
SEED_CSV = BACKEND_DIR.parent / "seed" / "episodes.csv"
# Import runs relative to the backend/ directory.
SEED_CSV_REL = "../seed/episodes.csv"


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Fresh schema for the whole session; drop everything afterwards."""
    if os.path.exists(_TEST_DB):
        os.unlink(_TEST_DB)
    Base.metadata.create_all(get_engine())
    yield
    get_engine().dispose()
    if os.path.exists(_TEST_DB):
        os.unlink(_TEST_DB)


@pytest.fixture()
def db():
    """A session that wipes all tables after each test for isolation."""
    from app.database import get_session_factory

    session = get_session_factory()()
    yield session
    session.close()
    session.rollback()
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()


@pytest.fixture()
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def make_user(db, email, role, password="pw123456", name=None):
    user = User(
        email=email,
        password_hash=hash_password(password),
        role=UserRole(role),
        name=name or email.split("@")[0],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login_headers(client_api, email, password="pw123456"):
    """Return Bearer headers for `email` by logging in through the API."""
    res = client_api.post("/api/auth/login", data={"username": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture()
def operator(db):
    return make_user(db, "op@example.com", "operator", name="Op One")


@pytest.fixture()
def admin(db):
    return make_user(db, "adm@example.com", "admin", name="Admin")


@pytest.fixture()
def client_a(db):
    return make_user(db, "client-a@example.com", "client", name="Client A")


@pytest.fixture()
def client_b(db):
    return make_user(db, "client-b@example.com", "client", name="Client B")


def make_episode(db, episode_id, quality="good", task="pick cup", robot="arm-01",
                 recorded="2026-08-16T10:00:00", duration=60, operator="Aline"):
    from datetime import datetime

    recorded_dt = recorded if isinstance(recorded, datetime) else datetime.fromisoformat(recorded)
    ep = Episode(
        episode_id=episode_id,
        robot_id=robot,
        task_name=task,
        recorded_at=recorded_dt,
        duration_seconds=duration,
        operator_name=operator,
        quality=EpisodeQuality(quality),
    )
    db.add(ep)
    db.commit()
    db.refresh(ep)
    return ep


def make_request(db, client, task="pick cup", count=2, status=RequestStatus.SUBMITTED):
    from datetime import datetime, timezone

    status_value = status if isinstance(status, RequestStatus) else RequestStatus(status)
    req = Request(
        client_id=client.id,
        task_name=task,
        episodes_requested=count,
        deadline=datetime(2026, 12, 31, 0, 0, 0),
        status=status_value,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    # Mirror production: creation writes the initial audit entry.
    db.add(
        RequestStatusHistory(
            request_id=req.id,
            from_status=None,
            to_status=status_value.value,
            changed_by_user_id=client.id,
            changed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    return req

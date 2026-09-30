"""Analytics endpoint tests: response formatting and correct aggregation."""
from app.services.import_service import import_csv

from tests.conftest import login_headers, make_episode, make_request


def _mk(db):
    """A throwaway client used to vary request ownership."""
    from tests.conftest import make_user

    return make_user(db, "tmp-c@example.com", "client")


def _seed_two_requests(db, client_a, client_b):
    make_request(db, client_a, task="pick cup", status="submitted")
    make_request(db, client_b, task="open drawer", status="delivered")
    make_request(db, client_a, task="fold towel", status="accepted")


def test_analytics_requires_operator_role(client, db, client_a, operator):
    _seed_two_requests(db, client_a, _mk(db))
    headers = login_headers(client, operator.email)
    res = client.get("/api/analytics", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == {
        "range_days", "episodes_per_day_robot", "requests_by_status",
        "median_fulfilment", "top_tasks", "engine",
    }
    assert body["engine"] in ("postgres", "sqlite")


def test_analytics_counts_requests_by_status(client, db, client_a, operator):
    _seed_two_requests(db, client_a, _mk(db))
    headers = login_headers(client, operator.email)
    body = client.get("/api/analytics", headers=headers).json()
    by_status = {r["status"]: r["count"] for r in body["requests_by_status"]}
    assert by_status.get("submitted") == 1
    assert by_status.get("delivered") == 1
    assert by_status.get("accepted") == 1


def test_analytics_top_tasks_order_by_good_episodes(client, db, operator, client_a):
    make_episode(db, "EP-T1", quality="good", task="alpha")
    make_episode(db, "EP-T2", quality="good", task="alpha")
    make_episode(db, "EP-T3", quality="good", task="beta")
    make_episode(db, "EP-T4", quality="bad", task="alpha")  # bad must not count
    make_episode(db, "EP-T5", quality="usable", task="beta")  # usable must not count
    headers = login_headers(client, operator.email)
    body = client.get("/api/analytics", headers=headers).json()
    tasks = {t["task_name"]: t["good_episodes"] for t in body["top_tasks"]}
    assert tasks["alpha"] == 2
    assert tasks["beta"] == 1


def test_analytics_per_day_per_robot(client, db, operator):
    make_episode(db, "EP-D1", robot="arm-01", recorded="2026-05-01T08:00:00")
    make_episode(db, "EP-D2", robot="arm-01", recorded="2026-05-01T09:00:00")
    make_episode(db, "EP-D3", robot="arm-02", recorded="2026-05-01T10:00:00")
    make_episode(db, "EP-D4", robot="arm-01", recorded="2026-05-02T08:00:00")
    headers = login_headers(client, operator.email)
    body = client.get("/api/analytics?days=365", headers=headers).json()
    rows = {(r["day"], r["robot_id"]): r["episodes"] for r in body["episodes_per_day_robot"]}
    assert rows[("2026-05-01", "arm-01")] == 2
    assert rows[("2026-05-01", "arm-02")] == 1
    assert rows[("2026-05-02", "arm-01")] == 1


def test_analytics_median_fulfilled_requests_only(client, db, operator, client_a):
    """Median is computed over requests that reached `delivered` only."""
    from datetime import datetime, timedelta, timezone

    from app.models import RequestStatusHistory

    base = datetime.now(timezone.utc)

    # Request 1: submitted -> in_progress (never delivered) -> excluded.
    req1 = make_request(db, client_a)  # history: None -> submitted at ~now
    db.add(RequestStatusHistory(request_id=req1.id, from_status="submitted",
                                to_status="in_progress", changed_by_user_id=operator.id,
                                changed_at=base + timedelta(hours=10)))
    db.commit()

    # Request 2: submitted -> delivered 4 hours later -> the only sample.
    req2 = make_request(db, client_a)
    db.add(RequestStatusHistory(request_id=req2.id, from_status="in_progress",
                                to_status="delivered", changed_by_user_id=operator.id,
                                changed_at=base + timedelta(hours=4)))
    db.commit()

    headers = login_headers(client, operator.email)
    body = client.get("/api/analytics", headers=headers).json()
    med = body["median_fulfilment"]
    assert med["sample_size"] == 1
    assert 3.9 < med["median_hours_submitted_to_delivered"] < 4.1


def test_client_cannot_access_analytics(client, db, client_a, operator):
    headers = login_headers(client, client_a.email)
    assert client.get("/api/analytics", headers=headers).status_code == 403


def test_analytics_range_validation(client, operator):
    headers = login_headers(client, operator.email)
    assert client.get("/api/analytics?days=0", headers=headers).status_code == 422
    assert client.get("/api/analytics?days=5000", headers=headers).status_code == 422

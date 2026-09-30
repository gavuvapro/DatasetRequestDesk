"""RBAC and authentication tests: server-side role enforcement."""
import pytest

from tests.conftest import login_headers, make_request


@pytest.fixture()
def ops_headers(client, operator):
    return login_headers(client, operator.email)


@pytest.fixture()
def admin_headers(client, admin):
    return login_headers(client, admin.email)


@pytest.fixture()
def a_headers(client, client_a):
    return login_headers(client, client_a.email)


@pytest.fixture()
def b_headers(client, client_b):
    return login_headers(client, client_b.email)


def test_login_rejects_bad_password(client, client_a):
    res = client.post("/api/auth/login", data={"username": client_a.email, "password": "wrong"})
    assert res.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_profile(client, a_headers, client_a):
    res = client.get("/api/auth/me", headers=a_headers)
    assert res.status_code == 200
    assert res.json()["email"] == client_a.email
    assert res.json()["role"] == "client"


def test_anonymous_cannot_create_request(client):
    res = client.post(
        "/api/requests",
        json={"task_name": "x", "episodes_requested": 1, "deadline": "2026-12-01T00:00:00"},
    )
    assert res.status_code == 401


def test_client_cannot_list_episodes(client, a_headers):
    assert client.get("/api/episodes", headers=a_headers).status_code == 403


def test_anonymous_cannot_import_csv(client):
    res = client.post("/api/episodes/import", files={"file": ("x.csv", b"a,b\n1,2", "text/csv")})
    assert res.status_code == 401


def test_client_cannot_import_csv(client, a_headers):
    res = client.post(
        "/api/episodes/import",
        headers=a_headers,
        files={"file": ("x.csv", b"a,b\n1,2", "text/csv")},
    )
    assert res.status_code == 403


def test_client_cannot_see_analytics(client, a_headers):
    assert client.get("/api/analytics", headers=a_headers).status_code == 403


def test_operator_cannot_create_user(client, ops_headers):
    res = client.post(
        "/api/users",
        headers=ops_headers,
        json={"email": "x@x.example.com", "password": "secret123", "role": "operator", "name": "X"},
    )
    assert res.status_code == 403


def test_admin_can_create_user(client, admin_headers):
    res = client.post(
        "/api/users",
        headers=admin_headers,
        json={"email": "new@example.com", "password": "secret123", "role": "operator", "name": "New"},
    )
    assert res.status_code == 201
    assert res.json()["role"] == "operator"


def test_client_sees_only_own_requests(client, db, a_headers, b_headers, client_a, client_b):
    mine = make_request(db, client_a)
    theirs = make_request(db, client_b)

    listed = client.get("/api/requests", headers=a_headers).json()
    assert [r["id"] for r in listed] == [mine.id]

    assert client.get(f"/api/requests/{theirs.id}", headers=a_headers).status_code == 404
    assert client.get(f"/api/requests/{theirs.id}", headers=b_headers).status_code == 200


def test_client_cannot_transition_other_clients_request(client, db, b_headers, client_a):
    req = make_request(db, client_a, status="delivered")
    res = client.post(
        f"/api/requests/{req.id}/transition", headers=b_headers, json={"to_status": "accepted"}
    )
    assert res.status_code == 404  # hidden, not just forbidden


def test_operator_cannot_accept_delivery(client, db, ops_headers, client_a):
    req = make_request(db, client_a, status="delivered")
    res = client.post(
        f"/api/requests/{req.id}/transition", headers=ops_headers, json={"to_status": "accepted"}
    )
    assert res.status_code == 409


def test_client_cannot_start_progress(client, db, a_headers, client_a):
    req = make_request(db, client_a)
    res = client.post(
        f"/api/requests/{req.id}/transition", headers=a_headers, json={"to_status": "in_progress"}
    )
    assert res.status_code == 409


def test_client_cannot_assign_episodes(client, db, a_headers, client_a, operator):
    from tests.conftest import make_episode

    req = make_request(db, client_a)
    ep = make_episode(db, "EP-T01")
    res = client.post(
        f"/api/requests/{req.id}/assign", headers=a_headers, json={"episode_id": ep.id}
    )
    assert res.status_code == 403


def test_deactivated_user_cannot_login(client, db, admin_headers):
    res = client.post(
        "/api/users",
        headers=admin_headers,
        json={"email": "ghost@example.com", "password": "secret123", "role": "client", "name": "G"},
    )
    uid = res.json()["id"]
    client.patch(f"/api/users/{uid}", headers=admin_headers, json={"is_active": False})
    res = client.post("/api/auth/login", data={"username": "ghost@example.com", "password": "secret123"})
    assert res.status_code == 403

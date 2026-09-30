# Dataset Request Desk — Testing Guide

## One command test run (from a clean clone)

```bash
# Everything: database, migrations, seed users, API, frontend
docker compose up --build
```

The backend container runs `alembic upgrade head`, seeds the five demo users,
and starts the API. The frontend is on http://localhost:3000, the API on
http://localhost:8000 (docs at http://localhost:8000/docs).

## Running the automated test suite

### Locally (fast, uses SQLite — no database service needed)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt                      # on Windows without a C compiler:
                                                     #   pip install fastapi uvicorn ... (all but psycopg2-binary)
pytest
```

Expected: **46 passed**. The suite covers exactly the areas the brief cares about:

| File | What it locks down |
|---|---|
| `tests/test_auth.py` | bad passwords, anonymous access, RBAC (client vs operator vs admin), clients seeing only their own requests (404, not 403), cross-client transitions blocked, deactivated users rejected |
| `tests/test_import.py` | messy-row rejection (bad quality, bad durations, unknown robots, unparseable dates), in-file duplicates, case-variant dedupe, ISO + European dates, idempotent re-import (172 imported then 0), header validation |
| `tests/test_requests.py` | every legal/illegal transition, delivery precondition (`>= episodes_requested`), bad-quality rejection, one-episode-one-request (API rule **and** DB unique constraint), rework cycle, audit-trail contents |
| `tests/test_analytics.py` | response shape, per-day/per-robot aggregation, top-5 good tasks, median over delivered-only requests with controlled timestamps, range validation |

### Inside Docker (PostgreSQL, exercises the `PERCENTILE_CONT` branch)

```bash
docker compose exec backend sh -c "cd /srv && pytest"
```

If you point `DATABASE_URL` at a disposable database, the suite runs against
PostgreSQL and the analytics median query uses the real
`PERCENTILE_CONT(0.5) WITHIN GROUP` path (on SQLite it uses the documented
fallback). Tests create their own schema and clean up after themselves.

## Manual verification checklist

### 1. CSV import idempotency (the money test)

```bash
docker compose exec backend python -m app.cli import-csv /seed/episodes.csv
# {"imported": 172, "skipped": 17, "errors": ["Row 59: Missing episode_id", ...]}
docker compose exec backend python -m app.cli import-csv /seed/episodes.csv
# {"imported": 0,   "skipped": 189, ...}   <- identical DB state, no duplicates
```

(The 17 errors are the intentionally messy rows in the seed file: missing IDs,
`excellent` quality, `-5`/`45.5`/`N/A`/`999999` durations, `not a date`,
unknown robot `arm-99`, and duplicate `EP-00074`/`EP-00030`/`EP-00011`.)

### 2. RBAC through the API

```bash
# client token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -d 'username=client-a@example.com&password=client123' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:8000/api/episodes -H "Authorization: Bearer $TOKEN"        # 403
curl -s http://localhost:8000/api/analytics -H "Authorization: Bearer $TOKEN"       # 403
curl -s http://localhost:8000/api/requests -H "Authorization: Bearer $TOKEN"        # only client-a's rows
```

### 3. State machine guard rails

- Deliver a request with fewer episodes assigned than requested → `409`.
- Operator attempts `delivered -> accepted` → `409` (clients only).
- Client B attempts to accept client A's delivery → `404` (invisible).
- Assign the same episode to a second request → `409`, even if two operators race
  (the `assignments.episode_id` UNIQUE constraint is the backstop).

### 4. Structured logs

```bash
docker compose logs backend | grep http_request | tail -3
# one JSON line per request: method, path, status, duration_ms, user_id
```

## Frontend smoke test

1. Open http://localhost:3000.
2. Log in as `client-a@example.com / client123` → create a request, watch it appear as `submitted`.
3. Log out, log in as `ops1@example.com / ops123` → find the request, assign
   episodes from the library (filter by task `pick cup`, quality `good`), then
   `Start`, `Deliver` once enough episodes are assigned.
4. Log back in as the client → `Accept` or `Reject` the delivered request.
5. As the operator, open `/api/analytics` (or `GET /api/analytics`) to see the aggregates.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `psycopg2-binary` fails to build on Windows/Python 3.13+ | Install everything else; tests run on SQLite. Inside Docker (Python 3.12) the wheel installs normally. |
| Backend unhealthy, `can't connect to db` | `docker compose logs db`; make sure port 5432 is free or override `POSTGRES_PORT`. |
| Using Neon | Set `DATABASE_URL` in `.env` to the Neon string (`?sslmode=require`); the `db` container stays idle. |
| Port conflicts | Override `BACKEND_PORT` / `FRONTEND_PORT` / `POSTGRES_PORT` in `.env`. |

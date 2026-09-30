# Dataset Request Desk

Internal web platform for a robotics data-collection company: clients submit
dataset requests, operators import episode metadata from messy CSV exports and
fulfil requests by assigning episodes, and every workflow step is audited.

**Stack** — FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL (Neon-compatible) ·
HTML5/Tailwind/vanilla-JS frontend behind nginx · Docker Compose · pytest.

## Quickstart

```bash
cp .env.example .env        # optional: defaults work out of the box
docker compose up --build
```

This starts PostgreSQL, runs migrations, seeds users, and launches:

- **Frontend:** http://localhost:3000
- **API:** http://localhost:8000 (interactive docs at `/docs`)
- **Health:** http://localhost:8000/health

### Import the seed data (operators can also upload via the UI)

```bash
docker compose exec backend python -m app.cli import-csv /seed/episodes.csv
```

Re-running the command is safe — the import is idempotent and reports exactly
what was imported, skipped, and why.

## Seed credentials

| Email | Password | Role |
|---|---|---|
| `admin@example.com` | `admin123` | admin |
| `ops1@example.com` | `ops123` | operator |
| `ops2@example.com` | `ops123` | operator |
| `client-a@example.com` | `client123` | client |
| `client-b@example.com` | `client123` | client |

## Run the tests

```bash
cd backend
pip install -r requirements.txt
pytest          # 46 passed (SQLite; see docs/TESTING_GUIDE.md for Postgres runs)
```

## Using Neon PostgreSQL

Set `DATABASE_URL` in `.env` to your Neon connection string — the app
normalises `postgresql://` to `postgresql+psycopg2://` automatically:

```
DATABASE_URL=postgresql+psycopg2://<user>:<password>@<host>/<db>?sslmode=require
```

With a remote `DATABASE_URL`, the bundled `db` container simply stays unused.
Run migrations against it with:

```bash
cd backend && DATABASE_URL="<neon url>" alembic upgrade head
```

## Project layout

```
backend/    FastAPI app (api/ services/ models/ schemas/ core/), Alembic, tests
frontend/   nginx + static SPA (login, client dashboard, operator dashboard)
docs/       ARCHITECTURE.md · API_SPEC.md · TESTING_GUIDE.md
seed/       episodes.csv (messy), users.json, generate_episodes.py (large-file load test)
```

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system diagram, ERD, scale notes (5M rows)
- [`docs/API_SPEC.md`](docs/API_SPEC.md) — full endpoint reference
- [`docs/TESTING_GUIDE.md`](docs/TESTING_GUIDE.md) — tests, Docker commands, manual checklist
- [`NOTES.md`](NOTES.md) — design decisions, security, trade-offs

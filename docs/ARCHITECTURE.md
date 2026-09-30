# Dataset Request Desk — Architecture

## System overview

```
┌────────────────────────────────────────────────────────────────────┐
│                          docker compose                            │
│                                                                    │
│  ┌──────────────┐   /api/* proxy   ┌────────────────────────────┐  │
│  │  frontend    │ ───────────────► │  backend (FastAPI, :8000)  │  │
│  │  nginx :3000 │                  │  uvicorn                   │  │
│  │  static SPA  │                  │  JWT auth · RBAC · logging │  │
│  └──────────────┘                  └──────────┬─────────────────┘  │
│                                               │ SQLAlchemy 2.0     │
│                                    ┌──────────▼──────────┐         │
│                                    │  PostgreSQL 16 :5432│         │
│                                    │  (or Neon over TLS) │         │
│                                    └─────────────────────┘         │
└────────────────────────────────────────────────────────────────────┘
```

- **frontend** — nginx serves the static HTML/JS SPA and reverse-proxies `/api/*`
  to the backend, so the browser sees a same-origin API (no CORS in production path).
- **backend** — FastAPI (sync endpoints on a threadpool), SQLAlchemy 2.0 ORM,
  Pydantic v2 schemas, Alembic migrations. On startup the container runs
  `alembic upgrade head`, seeds users if absent, then starts uvicorn.
- **db** — PostgreSQL 16. A `DATABASE_URL` pointing at Neon works unchanged
  (`postgresql+psycopg2://...?sslmode=require`); the `db` service is then simply unused.

## Data model (ERD)

```
users 1 ──── n requests 1 ──── n assignments n ──── 1 episodes
  │                │                                    ▲
  │                │ 1                    unique(episode_id)
  │                └── n request_status_history        │
  └── n assignments.assigned_by_user_id               │
                     request_status_history.changed_by_user_id ──┘ (users)
```

| Table | Key columns | Constraints & indexes |
|---|---|---|
| `users` | `id`, `email`, `password_hash`, `role` | `email UNIQUE`, indexed; role in `admin/operator/client` |
| `episodes` | `id`, `episode_id`, `robot_id`, `task_name`, `recorded_at`, `duration_seconds`, `operator_name`, `quality` | `episode_id UNIQUE` (idempotent import anchor); single indexes on `robot_id`, `task_name`, `recorded_at`, `quality`; **composite index `(recorded_at, robot_id, quality)`** |
| `requests` | `id`, `client_id FK`, `task_name`, `episodes_requested`, `deadline`, `notes`, `status` | indexes on `client_id`, `status`, `task_name`; `created_at`/`updated_at` |
| `assignments` | `id`, `request_id FK`, `episode_id FK`, `assigned_by_user_id FK`, `assigned_at` | **`UNIQUE(episode_id)`** — an episode can belong to at most one request, enforced by the DB, not just the API |
| `request_status_history` | `id`, `request_id FK`, `from_status`, `to_status`, `changed_by_user_id FK`, `changed_at` | composite index `(request_id, changed_at)`; append-only audit trail |
| `export_jobs` | `id`, `assignment_id FK`, `episode_id FK`, `request_id FK`, `status`, `attempts`, `max_attempts`, `last_error` | **`UNIQUE(assignment_id)`** — exactly one job per assignment (idempotency anchor); indexes on `status`, `request_id` |

State is deliberately centralised: `requests.status` is the single source of
truth for workflow position; `request_status_history` is append-only evidence.
Nothing else stores status.

## Request lifecycle

```
                 assign episodes (operator)
submitted ──────────────► in_progress ──────────────► delivered ────► accepted
                             ▲      (needs >= requested)   │
                             │                             ▼
                             └──────── rejected ◄──────── (client)
                                      (rework)                  terminal
```

Every arrow is validated twice: once in `request_service.TRANSITIONS` (who may
move what where) and once by role checks (`TRANSITION_ROLES`). Each applied
transition writes one audit row with actor and timestamp.

## Layered backend

```
app/
├── api/          HTTP surface: routers, request/response validation (thin)
├── services/     Domain logic: import engine, state machine, assignment rules
├── models/       SQLAlchemy ORM: tables, constraints, enums
├── schemas/      Pydantic v2: API contracts
├── core/         security (bcrypt + JWT), dependencies (get_current_user, RoleChecker)
├── database.py   lazy engine/session factory
├── config.py     pydantic-settings, DATABASE_URL normalisation for Neon
├── logger.py     JSON-lines formatter
└── main.py       app assembly, StructuredLoggingMiddleware
```

Business rules live in `services/`, never in routers, so the same rules are
exercised by API tests and would be reusable by a CLI or worker.

## Background export pipeline (stretch item)

```
assign_episode() ──► export_jobs (queued)                            1 job : 1 assignment
                          ▲                                             UNIQUE(assignment_id)
                          │ retry (reset attempts)                       = idempotency anchor
 POST /assign/{ep}/retry-export

export-worker thread (daemon, poll 2s):
    claim oldest QUEUED (or FAILED w/ attempts left, or stale RUNNING)
      → status=running, attempts+=1        [atomic UPDATE, FOR UPDATE SKIP LOCKED]
    simulate: sleep 2–5s, 20% failure
    → done | failed(last_error)            [own session, like a real worker]
```

Safety properties: idempotent creation (UNIQUE constraint backstops races),
atomic claiming (two workers can never run one job), and crash recovery (a
`running` job older than 60s is reclaimed). The worker runs in its own sessions
and would extract cleanly to a separate process + real task queue later.

## Structured logging

`StructuredLoggingMiddleware` emits one JSON line per request on stdout:

```json
{"timestamp":"2026-09-30T20:41:57.669742+00:00","level":"INFO","logger":"app.request",
 "message":"POST /api/requests","event":"http_request","method":"POST","path":"/api/requests",
 "status":201,"duration_ms":252.48,"user_id":"4"}
```

`user_id` comes from decoding the Bearer token in the middleware (never throws).
`/health` is excluded to keep the firehose clean. `LOG_FORMAT=text` switches to
human-readable output for local debugging.

## Scale notes (5M episodes)

The brief asks: what happens at 5M episodes?

- **Import** — the engine never materialises the file: rows stream through
  validation, dedupe against the DB happens in chunked `IN` queries (900 keys per
  chunk, memory-bounded), and insertion is batched `bulk_save_objects` with a
  per-row fallback. At 5M rows the current per-chunk `INSERT ... VALUES` would
  become the bottleneck; the next step is PostgreSQL `COPY FROM STDIN` into a
  staging table + `INSERT ... ON CONFLICT (episode_id) DO NOTHING`, which makes
  the whole import one set-based, idempotent statement.
- **Analytics** — all four queries aggregate in SQL. The per-day/per-robot query
  uses the composite index `(recorded_at, robot_id, quality)`; with 5M rows over
  a year the windowed scan touches only the requested range. Top-tasks scans
  `quality = 'good'`; at 5M rows I would add a partial index on
  `(task_name) WHERE quality = 'good'` or maintain a daily rollup table
  (`episode_daily_stats`) refreshed by a scheduled job.
- **Median fulfilment** — `PERCENTILE_CONT` over `request_status_history` only;
  this table grows with requests (hundreds/thousands), not episodes, so it is
  unaffected by episode volume.
- **Listing** — `/api/episodes` is paginated and index-backed; keyset
  pagination (`WHERE (recorded_at, id) < (:last, :last_id)`) would replace
  `OFFSET` before 10M rows.
- **Connection pressure** — uvicorn workers × threadpool share the engine pool;
  at 10× users I would run several replicas behind nginx and cap the pool
  (`pool_size=10, max_overflow=20`), with PgBouncer in transaction mode in front
  of PostgreSQL.

## Security posture

- Passwords: bcrypt via passlib; never logged, never returned.
- Tokens: short-lived JWTs (HS256, configurable TTL), resolved to a DB user on
  every request — deactivating a user revokes access immediately.
- Authorization: `RoleChecker` dependency + per-route checks + row-level
  filtering (`client_id = current_user.id`) — all server-side; other clients'
  requests return `404` so IDs cannot even be probed.
- Uploads: streamed to a temp file with a 512 MB cap; CSV parsing is
  stdlib-only (no formula/injection surface); all output rendered through an
  HTML-escaping helper in the frontend.
- CORS is open because nginx same-origin proxies in Docker; for a split-domain
  deployment, set the explicit frontend origin.

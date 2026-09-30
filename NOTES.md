# Notes

## 1. Design

**Data model.** Five tables: `users`, `episodes`, `requests`, `assignments`,
`request_status_history` (ERD in `docs/ARCHITECTURE.md`). State lives in exactly
two places: `requests.status` is the authoritative workflow position, and
`request_status_history` is an append-only audit trail (who moved what, when).
Assignments are rows, not arrays, so counting assigned episodes for the delivery
precondition is a cheap indexed query, and the `UNIQUE(episode_id)` constraint
makes "one episode, one request" a database guarantee rather than a hope.

**Hardest decisions:**

1. *Where the state machine lives.* I first sketched transitions as enum checks
   scattered through routers, but the role/owner rules and the delivery
   precondition made that untestable. Everything moved into
   `request_service.TRANSITIONS` / `TRANSITION_ROLES` + `apply_transition()`.
   Routers now only translate HTTP; the domain rules are unit-testable without
   HTTP at all, which is exactly how `tests/test_requests.py` works.
2. *Idempotent import against a messy file.* Deduplicating "in the file", "in the
   DB", and "case variant of both" simultaneously is easy to get subtly wrong
   (first-wins vs last-wins). I canonicalise `episode_id` to uppercase, dedupe
   in-file first (first occurrence wins), then chunk-query the DB for existing
   keys and skip those. Insertion is batched with a per-row fallback so a rare
   race degrades to "skipped" instead of failing the import.
3. *Analytics in SQL vs Python.* The brief demands database-side aggregation,
   which forced me to write the median twice: `PERCENTILE_CONT` for PostgreSQL
   and a small ordered-set fallback for SQLite so the test suite runs without a
   database service. Both branches are covered by the same endpoint contract.

## 2. What I deliberately left out (and what I'd do next)

- ~~No stretch item implemented~~ → **Stretch item implemented: background
  work.** Every assignment enqueues a simulated export job (`export_jobs` table,
  one per assignment via a UNIQUE constraint, so creation is idempotent). A
  daemon worker thread claims jobs atomically (`FOR UPDATE SKIP LOCKED`),
  simulates 2–5s of work, and fails ~20% of the time; failures retry up to 3
  times, and stale `running` rows are reclaimed after 60s (crash recovery).
  Operators see live per-episode export status in the assignment panel (2s poll)
  and can re-queue a failed export via `POST .../retry-export`. The worker uses
  its own sessions per job and would move to a separate process + real queue
  (or Postgres `SKIP LOCKED` queue) without touching the domain model. With two
  more days I'd add exponential backoff (`next_attempt_at`), a WebSocket/SSE
  push instead of polling, and extract the worker to its own container.
- **No pagination on request lists** (fine at this scale), no alembic autogenerate
  parity tests, no CI config (documented as nice-to-have in the brief).
- **Admin UI is API-only.** User management (`POST/PATCH /api/users`) exists and
  is tested, but the frontend only ships client + operator dashboards.
- **No refresh tokens / logout revocation list.** JWTs are short-lived-ish
  (configurable) and deactivation is enforced at every request, which covers the
  main operational risk.

## 3. What went wrong (and how I diagnosed it)

Three bugs worth admitting:

- **Enum values stored as names.** After the first end-to-end smoke test the
  analytics `top_tasks` came back empty. SQLAlchemy's `Enum` type persists
  member *names* (`GOOD`) by default while my raw SQL filtered `quality = 'good'`.
  Diagnosed by `SELECT DISTINCT quality FROM episodes` — the mismatch was
  immediate. Fix: `values_callable=lambda e: [m.value for m in e]` on all three
  enum columns.
- **Test emails rejected as invalid.** `email-validator` refuses `.test` and
  other special-use TLDs, so fixtures like `a@drd.test` blew up inside Pydantic
  with a confusing "value is not a valid email address" error. Diagnosed by
  reading the pydantic validation error verbatim; switched fixtures to
  `example.com` subdomains.
- **Export retries never ran.** The first claim filter folded the crash-recovery
  staleness check into *all* retries, so a freshly-failed job (updated_at = now)
  was invisible to the worker. Debugged with a scripted two-run scenario against
  a scratch SQLite DB; fixed by splitting the claim predicate into three
  explicit branches (QUEUED always, FAILED with attempts left, RUNNING if stale)
  and covering each with a test (`test_failure_is_retried`,
  `test_retries_are_capped`).

## 4. Security

- **Passwords:** bcrypt (passlib), never logged or returned; seeded users get
  hashed passwords via the same code path as the API.
- **Tokens:** JWT (HS256) carrying only `sub` and `role`; every request re-loads
  the user from the DB, so `is_active=False` takes effect instantly; `401` on
  missing/invalid, `403` on role mismatch.
- **Input validation:** Pydantic v2 on every body; CSV cells sanitised
  (trim/case-fold) and validated against whitelists (robots, quality enum,
  strict duration range) before touching the ORM; uploads streamed to disk with
  a hard size cap.
- **Row-level authorization:** clients can only ever see their own requests —
  enforced in the query (`WHERE client_id = ?`) *and* at single-resource fetch,
  returning `404` (not 403) so IDs can't be probed.
- **Top two vulnerabilities I'd worry about in this kind of system:**
  1. *IDOR / broken object-level authorization* — the classic internal-tool
     failure. Mitigated as above; in a review I'd add a regression test per
     endpoint asserting cross-tenant access yields 404.
  2. *CSV/SSRF-style injection into the export path* — once episodes flow out to
     clients as CSV/spreadsheets, formula injection (`=cmd|...`) becomes real.
     Not exposed here yet; when it is, cells starting with `=+-@` must be
     prefixed/escaped.

## 5. Scale

- **10× users:** uvicorn sync endpoints scale horizontally behind nginx; the
  first wall is the DB connection pool — add PgBouncer (transaction mode) and
  replicas for read-heavy endpoints (analytics, episode listing).
- **100× episodes (≈5M rows):** detailed in `docs/ARCHITECTURE.md`. First to
  break: unbatched imports and `OFFSET` pagination. Plan: `COPY`-based import
  into a staging table with `ON CONFLICT DO NOTHING`, keyset pagination, a
  partial index on `(task_name) WHERE quality = 'good'`, and a daily rollup
  table for the per-day analytics. The median query is unaffected — history
  grows with requests, not episodes.

## 6. AI tooling

This codebase was written with an AI coding assistant (Codebuff) driving
scaffolding, boilerplate, and test iteration under my direction. Design
decisions, domain rules, debugging (the enum-names issue above), and the final
review were done interactively — every line was executed against real runs of
the importer, the API smoke test, and the pytest suite before committing.
The interview live-coding session should be treated as the source of truth for
what I can defend.

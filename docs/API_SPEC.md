# Dataset Request Desk — API Specification

Base URL: `http://localhost:8000` (backend) or `http://localhost:3000/api` (via nginx proxy).

All endpoints except `/health` and `POST /api/auth/*` require the header:

```
Authorization: Bearer <access_token>
```

Errors use `{"detail": "..."}`. Domain rule violations return `409 Conflict`
(or `403` for permission issues, `404` when a resource must stay invisible).
Validation errors return `422` with FastAPI's standard body.

---

## Auth

### `POST /api/auth/login`
OAuth2 password flow (form-encoded). Used by the frontend.

| Field | Type | Notes |
|---|---|---|
| `username` | string | the user's email |
| `password` | string | |

**200** →
```json
{ "access_token": "eyJ...", "token_type": "bearer",
  "user": { "id": 1, "email": "admin@example.com", "role": "admin", "name": "Ada Admin",
            "organisation": null, "is_active": true, "created_at": "..." } }
```
`401` bad credentials · `403` deactivated account.

### `POST /api/auth/login-json`
Identical, but takes JSON: `{"email": "...", "password": "..."}`.

### `GET /api/auth/me`
Returns the authenticated user's profile (`UserOut`).

---

## Users (admin only)

| Endpoint | Description |
|---|---|
| `GET /api/users` | List all users. |
| `POST /api/users` | Create a user. Body: `{email, password (min 8), role: admin\|operator\|client, name, organisation?}`. `201`. |
| `PATCH /api/users/{id}` | Update `role`, `is_active`, `name`, `organisation`. Admin cannot deactivate themselves. |

---

## Episodes (operator/admin)

### `GET /api/episodes`
Paginated episode browser.

| Query param | Type | Description |
|---|---|---|
| `task_name` | string | case-insensitive substring match |
| `quality` | `good` \| `usable` \| `bad` | exact match |
| `robot_id` | string | exact match |
| `limit` | int (1–500, default 50) | |
| `offset` | int ≥ 0 | |

**200** → `{ "items": [EpisodeOut...], "total": 172, "limit": 50, "offset": 0 }`

`EpisodeOut`: `{id, episode_id, robot_id, task_name, recorded_at, duration_seconds, operator_name, quality}`

### `POST /api/episodes/import`
Multipart upload of a messy CSV (`file` field). Idempotent — re-running the same
file reports skips, never duplicates.

**200** →
```json
{ "imported": 172, "skipped": 17,
  "errors": ["Row 59: Missing episode_id", "Row 66: invalid duration '45.5' ..."] }
```
`400` invalid CSV header · `413` file larger than 512 MB.

---

## Requests

### `POST /api/requests` (client, admin)
```json
{ "task_name": "pick cup", "episodes_requested": 200,
  "deadline": "2026-12-01T00:00:00Z", "notes": "optional" }
```
**201** → `RequestOut`. New requests start `submitted`; the initial audit entry is written.

### `GET /api/requests?status=`
Clients receive **only their own** requests; operators/admins receive all.
Optional `status` filter (`submitted|in_progress|delivered|accepted|rejected`).

### `GET /api/requests/{id}`
Single request. A client requesting another client's request gets `404`.

`RequestOut`:
```json
{ "id": 1, "client_id": 4, "client_name": "Acme Robotics", "task_name": "pick cup",
  "episodes_requested": 2, "deadline": "...", "notes": null, "status": "submitted",
  "created_at": "...", "updated_at": "...", "assigned_count": 0 }
```

### `GET /api/requests/{id}/history`
Audit trail, oldest first:
```json
[{ "id": 3, "from_status": "submitted", "to_status": "in_progress",
   "changed_by_user_id": 2, "changed_at": "..." }]
```

### `GET /api/requests/{id}/assignments`
Episodes assigned to the request:
```json
[{ "id": 9, "episode_pk": 12, "episode_id": "EP-00138", "robot_id": "arm-02",
   "task_name": "pick cup", "quality": "good", "duration_seconds": 83,
   "assigned_by_user_id": 2, "assigned_at": "..." }]
```

### `POST /api/requests/{id}/transition`
Body: `{"to_status": "..."}`.

Allowed transitions and who may perform them:

| From | To | Who | Precondition |
|---|---|---|---|
| `submitted` | `in_progress` | operator/admin | — |
| `in_progress` | `delivered` | operator/admin | `assigned_count >= episodes_requested` |
| `delivered` | `accepted` | **owner client** | — |
| `delivered` | `rejected` | **owner client** | — |
| `rejected` | `in_progress` | operator/admin | rework |

`409` on invalid transition, missing precondition, or wrong role. Every success
writes a `request_status_history` row.

### `POST /api/requests/{id}/assign` (operator/admin)
Body: `{"episode_id": <numeric pk>}` — assign **one** episode.

Rules enforced (409 on violation):
- request must be `submitted`, `in_progress`, or `rejected`;
- episode quality must be `good` or `usable`;
- episode must not already belong to another request;
- assigning the same episode twice to the same request is an idempotent no-op.

**200** → the request's full assignment list.

### `DELETE /api/requests/{id}/assign/{episode_pk}` (operator/admin)
Remove an assignment (only before delivery). `204`.

---

## Analytics (operator/admin)

### `GET /api/analytics?days=30`
All aggregation runs inside the database.

```json
{
  "range_days": 30,
  "episodes_per_day_robot": [ { "day": "2026-09-14", "robot_id": "arm-01", "episodes": 5 } ],
  "requests_by_status": [ { "status": "delivered", "count": 3 } ],
  "median_fulfilment": { "median_hours_submitted_to_delivered": 36.2, "sample_size": 4 },
  "top_tasks": [ { "task_name": "pick cup", "good_episodes": 19 } ],
  "engine": "postgres"
}
```

- `episodes_per_day_robot`: `GROUP BY DATE(recorded_at), robot_id` within the window.
- `median_fulfilment`: median hours from the `submitted` history row to the
  `delivered` history row. PostgreSQL uses `PERCENTILE_CONT(0.5) WITHIN GROUP (...)`;
  SQLite (tests/local) uses an ordered-set fallback computed in SQL.
- `top_tasks`: top 5 task names by count of `good` episodes (all time).

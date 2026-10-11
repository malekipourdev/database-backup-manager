# Data Model: Admin Authentication and Database Instance Management

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-10-11

All tables live in the panel's internal database (SQLite by default). Types are expressed in
portable SQLAlchemy terms; no dialect-specific types are used (Principle V). All timestamps are
stored as timezone-aware UTC. Every table is created by an Alembic migration.

## admin_accounts

The single admin of the MVP (spec: Admin Account).

| Field | Type | Rules |
|-------|------|-------|
| id | Integer PK | |
| username | String(64) | Required, unique, stored lower-cased, 1–64 chars |
| password_hash | String(255) | Argon2id hash; never exposed |
| last_login_at | DateTime(tz) | Nullable |
| created_at / updated_at | DateTime(tz) | Set automatically |

Created at startup from `MBP_ADMIN_USERNAME` / `MBP_ADMIN_PASSWORD` only when the table is empty
(FR-007).

## sessions

Spec: Session.

| Field | Type | Rules |
|-------|------|-------|
| id | Integer PK | |
| token_hash | String(64) | SHA-256 hex of the cookie token; unique, indexed |
| admin_id | FK → admin_accounts.id | ON DELETE CASCADE |
| created_at | DateTime(tz) | |
| last_activity_at | DateTime(tz) | Updated on authenticated requests (≤ once/minute) |

**Lifecycle**: created on successful login → valid while `now - last_activity_at < 30 min` →
deleted on logout. Expired rows are rejected on lookup and purged opportunistically on login.

## login_attempts

Throttling state for FR-006; exists for any attempted username, known or not.

| Field | Type | Rules |
|-------|------|-------|
| username | String(64) PK | Lower-cased attempted username |
| failure_count | Integer | ≥ 0 |
| window_started_at | DateTime(tz) | Start of current 15-min window |
| locked_until | DateTime(tz) | Nullable |

**Transitions**: failure → if window expired, reset to count 1 / new window, else count+1; when
count reaches 5 → `locked_until = now + 15 min`. While `now < locked_until` all attempts fail
without checking the password. Success (when not locked) → row deleted.

## db_instances

Spec: Database Instance.

| Field | Type | Rules |
|-------|------|-------|
| id | Integer PK | |
| name | String(100) | Required, trimmed, unique (case-insensitive via `name_normalized`) |
| name_normalized | String(100) | Lower-cased name; unique index |
| host | String(255) | Required; hostname, IPv4 or IPv6 literal; no scheme, no spaces |
| port | Integer | Required, 1–65535, default 3306 |
| username | String(255) | Required, 1–255 chars, any characters |
| password_encrypted | Text | Fernet token; required; never returned or logged |
| notes | Text | Optional, ≤ 2,000 characters |
| server_type | String(16) | Nullable; `mysql` \| `mariadb` |
| server_version | String(64) | Nullable, e.g. `8.4.3`, `11.8.2` |
| last_test_at | DateTime(tz) | Nullable |
| last_test_ok | Boolean | Nullable |
| last_test_error_code | String(32) | Nullable; one of the error codes in research §7 |
| created_at / updated_at | DateTime(tz) | |

**Rules**:
- On update, an empty/absent password keeps `password_encrypted` unchanged (FR-010).
- If `host`, `port`, `username` or password change, `server_type`, `server_version` and the
  `last_test_*` fields are cleared (old results no longer describe the new target).
- Delete cascades to `db_selections` (FR-011).

## db_selections

Spec: Database Selection.

| Field | Type | Rules |
|-------|------|-------|
| id | Integer PK | |
| instance_id | FK → db_instances.id | ON DELETE CASCADE |
| database_name | String(64) | Required; unique together with `instance_id` |
| created_at | DateTime(tz) | |

**Rules**:
- Saving a selection replaces the instance's full set atomically (PUT semantics).
- `information_schema`, `performance_schema`, `sys` are rejected (FR-020); `mysql` is allowed.
- Names not currently present on the server are accepted only if already in the stored set
  (keeps "missing on server" entries, FR-022); new unknown names are rejected.

## Derived (not stored): database listing entry

Returned when listing an instance's databases; merges live server data with selections.

| Field | Meaning |
|-------|---------|
| name | Database name |
| is_system | Name is one of the four system schemas |
| selectable | `false` for `information_schema`, `performance_schema`, `sys` |
| selected | Present in `db_selections` |
| missing | Selected but not returned by the server |

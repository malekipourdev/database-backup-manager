# Research: Admin Authentication and Database Instance Management

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-10-11

The stack is largely fixed by the constitution (React SPA, FastAPI, SQLAlchemy + Alembic, SQLite
default, pytest, ruff, ESLint + Prettier). This document records the remaining decisions.

## 1. Backend runtime and data access style

- **Decision**: Python 3.12, FastAPI, SQLAlchemy 2.0 in **synchronous** mode (FastAPI runs sync
  route handlers in its thread pool). Dependencies managed with `uv`.
- **Rationale**: Sync SQLAlchemy works identically with SQLite, PostgreSQL and MySQL drivers
  (Principle V) without async driver variants. Load is a single admin; thread-pool concurrency is
  more than sufficient. The target-DB client (PyMySQL) is also synchronous.
- **Alternatives considered**: Async SQLAlchemy (`aiosqlite`/`asyncpg`/`aiomysql`) — more
  drivers to keep aligned, no benefit at this scale.

## 2. Admin password hashing

- **Decision**: Argon2id via `argon2-cffi` with library default parameters; rehash on login when
  parameters change.
- **Rationale**: Current OWASP recommendation; satisfies FR-004.
- **Alternatives considered**: bcrypt (72-byte input limit), PBKDF2 (weaker against GPUs).

## 3. Session mechanism

- **Decision**: Server-side sessions. On login, generate a 256-bit random token, store only its
  SHA-256 hash in a `sessions` table, and send the token in a cookie `mbp_session` with
  `HttpOnly`, `SameSite=Strict`, `Secure` (configurable off for local HTTP), `Path=/`.
  Idle timeout 30 minutes (FR-005), sliding: `last_activity_at` updated on each authenticated
  request (throttled to once per minute to limit writes). Logout deletes the row.
- **CSRF**: `SameSite=Strict` plus a required `X-Requested-With: mbp` header on all
  state-changing requests (cross-site forms cannot set custom headers; CORS is not enabled).
- **Rationale**: Server-side sessions can be revoked instantly (sign-out, expiry) and leak no
  claims; cookie keeps the token out of JavaScript.
- **Alternatives considered**: JWT in localStorage (XSS-exposed, not revocable); JWT in cookie
  (revocation needs a denylist, i.e. server state anyway).

## 4. Login throttling (FR-006)

- **Decision**: Table `login_attempts` keyed by normalized (lower-cased) username, tracking
  `failure_count`, `window_started_at`, `locked_until`. Applies to unknown usernames too, so
  lockout does not reveal account existence. Successful login resets the row. While locked, the
  response is the same generic failure (HTTP 401, code `invalid_credentials`) to avoid an
  enumeration oracle; a constant-time dummy hash verify runs for unknown usernames.
- **Alternatives considered**: In-memory limiter (lost on restart, wrong with multiple workers);
  per-IP limiting (behind a reverse proxy all IPs may look identical).

## 5. Initial admin bootstrap (FR-007)

- **Decision**: On startup, if the `admin_accounts` table is empty, create the admin from
  `MBP_ADMIN_USERNAME` and `MBP_ADMIN_PASSWORD`. If empty and these are unset, startup fails with
  a clear message. Once an admin exists the variables are ignored (documented).
- **Alternatives considered**: First-run web setup page — exposes an unauthenticated
  account-creation window, conflicting with Principle I.

## 6. Encryption of instance passwords (FR-012)

- **Decision**: `cryptography` Fernet (AES-128-CBC + HMAC-SHA256) via `MultiFernet`, key from
  `MBP_ENCRYPTION_KEY` (one or more comma-separated Fernet keys; first encrypts, all decrypt — to
  allow future key rotation). App refuses to start if missing or invalid.
- **Rationale**: Authenticated encryption, well-reviewed, simple API.
- **Alternatives considered**: AES-GCM by hand (more room for nonce mistakes); DB-native
  encryption (not portable across SQLite/PostgreSQL/MySQL).
- **Secret hygiene**: Password fields use a `SecretStr` type in schemas; a logging filter
  redacts known secret fields; repository/ORM `__repr__` excludes the ciphertext; API response
  schemas have no password field at all (only `has_password: true`).

## 7. Target-server client, detection and error classification

- **Decision**: `PyMySQL` (pure Python; supports MySQL 8 `caching_sha2_password` with
  `cryptography`, and MariaDB). Connect with `connect_timeout=10`, `read_timeout=10`,
  `write_timeout=10`. The whole operation is additionally wrapped in a 10-second deadline
  (worker thread + wait) so slow DNS resolution cannot exceed the limit (FR-017, SC-004).
- **Detection** (FR-015): `SELECT VERSION(), @@version_comment`. If either contains `MariaDB`,
  type is `mariadb`, else `mysql`. Version parsed as the leading `X.Y.Z` (MariaDB's
  `5.5.5-` replication prefix stripped).
- **Error classification** (FR-016), returned as stable codes the UI translates:

  | Condition | Code |
  |-----------|------|
  | `socket.gaierror` / MySQL client error 2005 | `host_not_found` |
  | `ECONNREFUSED` / client error 2003 with refused errno | `connection_refused` |
  | socket timeout / deadline exceeded / 2003 with timeout | `timeout` |
  | server error 1045 (and 1044, 1698) | `auth_rejected` |
  | any other server/client error | `server_error` + sanitized server message |

  Sanitizing removes the password value if present and truncates to 500 chars.
- **Database listing** (FR-018): `SHOW DATABASES` (respects the user's privileges). System
  schemas are the fixed set `information_schema`, `performance_schema`, `mysql`, `sys`; the
  backend returns all with an `is_system` and `selectable` flag, the UI hides system ones by
  default (FR-019/020).
- **Alternatives considered**: `mysqlclient` (C build deps, bigger image); `mysql-connector`
  (heavier, MariaDB quirks).

## 8. Frontend stack

- **Decision**: React 18 + TypeScript + Vite; React Router; TanStack Query for server state;
  `react-i18next` with JSON resource files `fa.json`/`en.json`; Mantine v7 component library
  (native RTL support via `DirectionProvider`); form validation with Mantine form + zod.
  `<html lang dir>` set from the selected language; layout styles use CSS logical properties.
  Dates formatted with `Intl.DateTimeFormat` (`fa-IR` gives Persian calendar and digits, `en-US`
  Gregorian). Language choice remembered in `localStorage` (convenience only), default Persian.
- **Rationale**: Mantine handles RTL mirroring of components out of the box, which is the
  costliest part of Principle VIII.
- **Alternatives considered**: MUI (RTL needs emotion stylis plugin setup); Tailwind + headless
  (all RTL handling manual).
- **Error display**: API errors carry a `code`; the UI maps `errors.<code>` translation keys,
  so all messages are bilingual (FR-024). Server-provided detail (for `server_error`) is shown
  verbatim as supplementary text.

## 9. Testing approach

- **Decision**: Backend: pytest + FastAPI `TestClient` for API tests on SQLite;
  `testcontainers` (Python) for integration tests against `mysql:8.4` and `mariadb:11.8`
  (current LTS lines), parametrized so each connection/listing test runs on both (SC-007).
  A secret-leak test seeds a known password and asserts it never appears in any response body or
  captured log record (SC-003). An auth-coverage test iterates every registered route and asserts
  401 without a session, except the allow-list (SC-002).
  Frontend: Vitest + Testing Library for translation completeness (both locale files have the
  same key set) and key components.
- **Alternatives considered**: Docker-compose-managed test DBs (harder to run per test session).

## 10. Packaging

- **Decision**: `backend/Dockerfile` (multi-stage: `uv` builder → `python:3.12-slim` runtime,
  non-root user, runs `alembic upgrade head` then `uvicorn`). `frontend/Dockerfile` (multi-stage:
  `node:22-alpine` build → `nginxinc/nginx-unprivileged:alpine` serving the SPA and proxying
  `/api` to the backend). Root `docker-compose.yml` with one internal network; only the frontend
  port published; SQLite data on a named volume. No `docker.sock` (Principle VI).
- **Host-machine servers**: Documented via `extra_hosts: ["host.docker.internal:host-gateway"]`
  in compose so admins can enter `host.docker.internal` as host (edge case in spec).

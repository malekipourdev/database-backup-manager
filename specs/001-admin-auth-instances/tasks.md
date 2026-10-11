---

description: "Task list for Admin Authentication and Database Instance Management"
---

# Tasks: Admin Authentication and Database Instance Management

**Input**: Design documents from `/specs/001-admin-auth-instances/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/openapi.yaml](./contracts/openapi.yaml),
[quickstart.md](./quickstart.md)

**Tests**: Included. Constitution Principle IX requires pytest coverage of backend business
logic and every API endpoint, and integration tests against real MySQL and MariaDB containers.
Within each story, write the tests first and confirm they fail before implementing.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested
on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story the task belongs to (US1–US4 from spec.md)

## Path Conventions

Web app layout from plan.md: backend package in `backend/src/mbp/`, backend tests in
`backend/tests/`, frontend in `frontend/src/`, frontend tests in `frontend/tests/`.
All code comments in English (Principle X). All user-visible frontend text goes through
`frontend/src/i18n/locales/{fa,en}.json`; never hard-code UI strings (Principle VIII).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and tooling

- [X] T001 Create the directory skeleton from plan.md "Source Code": `backend/src/mbp/{security,models,repositories,services,api}/`, `backend/tests/{unit,api,integration}/`, `backend/migrations/versions/`, `frontend/src/{i18n/locales,api,components,pages}/`, `frontend/tests/`, each Python package with an empty `__init__.py`
- [X] T002 Initialize backend project in `backend/pyproject.toml` (uv, Python `>=3.12`, package `mbp` under `src/`) with dependencies fastapi, uvicorn[standard], pydantic>=2, pydantic-settings, sqlalchemy>=2.0, alembic, pymysql, cryptography, argon2-cffi; dev dependencies pytest, httpx, testcontainers[mysql], ruff; pytest config with `testpaths=["tests"]` and marker `integration: requires Docker (MySQL/MariaDB containers)`, default run excludes it via `addopts = "-m 'not integration'"`
- [X] T003 [P] Configure ruff in `backend/pyproject.toml` (`line-length = 100`, `target-version = "py312"`, lint rules `E,F,I,B,UP,S,SIM`, ignore `S101` in `tests/`) and format settings
- [X] T004 [P] Initialize frontend with Vite React + TypeScript in `frontend/package.json` and `frontend/tsconfig.json`; add dependencies react-router-dom, @tanstack/react-query, i18next, react-i18next, @mantine/core, @mantine/hooks, @mantine/form, @mantine/notifications, zod; dev dependencies vitest, @testing-library/react, @testing-library/user-event, jsdom, eslint, prettier; scripts `dev`, `build`, `lint`, `format:check`, `test`
- [X] T005 [P] Configure ESLint (typescript-eslint, react-hooks, plus a `no-restricted-syntax`/i18n rule warning on JSX string literals) in `frontend/eslint.config.js` and Prettier in `frontend/.prettierrc`
- [X] T006 [P] Configure Vite dev proxy `/api` → `http://localhost:8000` and Vitest (`environment: "jsdom"`, `include: ["tests/**/*.test.ts?(x)"]`) in `frontend/vite.config.ts`
- [X] T007 [P] Create `.env.example` at repository root documenting `MBP_ENCRYPTION_KEY` (comma-separated Fernet keys, first encrypts), `MBP_ADMIN_USERNAME`, `MBP_ADMIN_PASSWORD`, `MBP_DATABASE_URL` (default `sqlite:////data/mbp.db`), `MBP_COOKIE_SECURE` (default `true`), with a comment on generating a Fernet key; add `.gitignore` entries for `.env`, `backend/.venv`, `frontend/node_modules`, `frontend/dist`, `*.db`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Configuration, internal database, security primitives, session-auth dependency,
error format, and frontend shell that every story needs

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Backend foundation

- [X] T008 Implement settings in `backend/src/mbp/config.py` with pydantic-settings, env prefix `MBP_`: `encryption_key: SecretStr` (required), `admin_username: str | None`, `admin_password: SecretStr | None`, `database_url: str = "sqlite:////data/mbp.db"`, `cookie_secure: bool = True`, `session_idle_minutes: int = 30`, `connect_timeout_seconds: int = 10`; expose cached `get_settings()`
- [X] T009 Implement engine and session factory in `backend/src/mbp/db.py`: `create_engine(settings.database_url)`, enable `PRAGMA foreign_keys=ON` for SQLite connections via event listener, `SessionLocal`, FastAPI dependency `get_db()` yielding a session; declarative `Base` with a naming convention for constraints; a `UTCDateTime` TypeDecorator storing timezone-aware UTC datetimes portably
- [X] T010 [P] Implement secret-redaction logging in `backend/src/mbp/logging.py`: a `logging.Filter` that replaces values of keys `password`, `password_encrypted`, `encryption_key`, `token`, `admin_password` in record args/dicts and any string registered via `register_secret(value)` with `***`; `configure_logging()` installs it on the root logger and uvicorn loggers
- [X] T011 [P] Implement Argon2id hashing in `backend/src/mbp/security/passwords.py`: `hash_password(plain) -> str`, `verify_password(hash, plain) -> bool` (False on mismatch, never raises for wrong password), `needs_rehash(hash) -> bool`, and `dummy_verify()` that verifies against a fixed precomputed hash to equalize timing for unknown usernames
- [X] T012 [P] Implement encryption in `backend/src/mbp/security/crypto.py`: build `MultiFernet` from `settings.encryption_key` split on commas; `encrypt(plain: str) -> str`, `decrypt(token: str) -> str`; `validate_key()` raising `RuntimeError("MBP_ENCRYPTION_KEY is missing or invalid")` on any malformed key
- [X] T013 [P] Unit tests for passwords and crypto in `backend/tests/unit/test_security_primitives.py`: hash/verify round trip, wrong password returns False, encrypt/decrypt round trip including non-Latin text, decrypt with a second (rotation) key in the list, invalid key raises
- [X] T014 [P] Create `AdminAccount` model in `backend/src/mbp/models/admin.py` — table `admin_accounts`: `id` Integer PK; `username` String(64) "Required, unique, stored lower-cased, 1–64 chars"; `password_hash` String(255) "Argon2id hash; never exposed"; `last_login_at` nullable UTCDateTime; `created_at`/`updated_at` set automatically; `__repr__` excludes `password_hash`
- [X] T015 [P] Create `Session` model in `backend/src/mbp/models/session.py` — table `sessions`: `id` Integer PK; `token_hash` String(64) "SHA-256 hex of the cookie token; unique, indexed"; `admin_id` FK → `admin_accounts.id` ON DELETE CASCADE; `created_at`; `last_activity_at` "Updated on authenticated requests (≤ once/minute)"
- [X] T016 Export all models from `backend/src/mbp/models/__init__.py` and configure Alembic in `backend/alembic.ini` and `backend/migrations/env.py` to use `get_settings().database_url` and `Base.metadata` with `render_as_batch=True` (SQLite ALTER support)
- [X] T017 [P] Implement `AdminRepository` (`get_by_username` lower-cased lookup, `count`, `create`, `update_password_hash`, `touch_last_login`) in `backend/src/mbp/repositories/admin_repository.py`
- [X] T018 [P] Implement `SessionRepository` (`create(admin_id) -> plain_token` generating `secrets.token_urlsafe(32)` and storing only its SHA-256 hex; `get_valid(plain_token, idle_minutes)` returning None if missing or `now - last_activity_at >= idle`; `touch(session)` updating `last_activity_at` only if older than 60 s; `delete(session)`; `purge_expired(idle_minutes)`) in `backend/src/mbp/repositories/session_repository.py`
- [X] T019 Implement error format in `backend/src/mbp/api/errors.py`: Pydantic `Error {code: str, detail: str | None, fields: dict[str,str] | None}`; `ApiError(status, code, detail=None, fields=None)` exception; handlers mapping `ApiError` to JSON, `RequestValidationError` to 422 `{"code":"validation_error","fields":{<field>: <error type>}}` with input values **omitted** (so submitted passwords are never echoed), and unhandled exceptions to 500 `{"code":"internal_error"}` with the exception logged through the redaction filter
- [X] T020 Implement auth and CSRF dependencies in `backend/src/mbp/security/sessions.py`: `require_session` reads cookie `mbp_session`, calls `SessionRepository.get_valid`, touches it, returns the admin, else raises `ApiError(401, "not_authenticated")`; `require_csrf` raises `ApiError(403, "csrf_failed")` for POST/PUT/PATCH/DELETE without header `X-Requested-With: mbp`; helpers `set_session_cookie(response, token)` (HttpOnly, SameSite=Strict, Secure=`settings.cookie_secure`, Path=/) and `clear_session_cookie(response)`
- [X] T021 Implement app factory in `backend/src/mbp/main.py`: `create_app()` calls `configure_logging()`, `crypto.validate_key()` (startup fails if invalid), registers error handlers, mounts routers under `/api` where every router except health and login is included with `dependencies=[Depends(require_session), Depends(require_csrf)]`; module-level `app = create_app()`
- [X] T022 [P] Implement health endpoint `GET /api/health` → `{"status":"ok"}` (no auth, no data) in `backend/src/mbp/api/health.py`
- [X] T023 Create initial migration `backend/migrations/versions/0001_auth_and_instances.py` with tables `admin_accounts`, `sessions`, `login_attempts`, `db_instances`, `db_selections` exactly as in data-model.md (models for the last three are added in their stories; the migration is written now from data-model.md so the schema is created once)
- [X] T024 Create test fixtures in `backend/tests/conftest.py`: set `MBP_ENCRYPTION_KEY` to a generated Fernet key and `MBP_DATABASE_URL` to a temp-file SQLite URL before importing the app; create schema via `alembic upgrade head`; `client` fixture (TestClient with default header `X-Requested-With: mbp`); `admin` fixture creating an admin `admin`/`Adm1n-pass`; `auth_client` fixture that creates a session via `SessionRepository` and sets the `mbp_session` cookie
- [X] T025 [P] API tests for the foundation in `backend/tests/api/test_foundation.py`: health returns 200 without session; a request to a protected route without cookie → 401 `not_authenticated`; with an expired session (`last_activity_at` 31 min ago) → 401; POST without `X-Requested-With` → 403 `csrf_failed`; app startup with invalid `MBP_ENCRYPTION_KEY` raises

### Frontend foundation

- [X] T026 [P] Implement i18n in `frontend/src/i18n/index.ts`: i18next + react-i18next with resources from `locales/fa.json` and `locales/en.json`, default language `fa`, persisted choice read/written to `localStorage` key `mbp.lang` inside try/catch; on language change set `document.documentElement.lang` and `dir` (`rtl` for fa, `ltr` for en); export `formatDateTime(iso, lang)` using `Intl.DateTimeFormat` with locale `fa-IR` or `en-US`, `dateStyle: "medium"`, `timeStyle: "short"`
- [X] T027 [P] Create locale files `frontend/src/i18n/locales/fa.json` and `frontend/src/i18n/locales/en.json` with initial namespaces `common` (app name, save, cancel, delete, confirm, loading, retry), `nav`, `language` and `errors` (`not_authenticated`, `csrf_failed`, `validation_error`, `internal_error`, `network_error`, `instance_not_found`, `name_taken`, `not_selectable`, `unknown_database`, `invalid_credentials`, `host_not_found`, `connection_refused`, `timeout`, `auth_rejected`, `server_error`) — every key present in both files
- [X] T028 [P] Implement API client in `frontend/src/api/client.ts`: `apiFetch<T>(path, init)` prefixing `/api`, sending `credentials: "same-origin"`, JSON body, and header `X-Requested-With: mbp`; on non-2xx parse `Error` and throw `ApiError {status, code, detail, fields}`; on network failure throw code `network_error`; export `errorMessage(t, err)` returning `t("errors." + code)` with fallback `errors.internal_error`
- [X] T029 Implement app shell in `frontend/src/main.tsx` and `frontend/src/App.tsx`: QueryClient provider, MantineProvider with `DirectionProvider` synced to the current language (Vazirmatn font for fa via Google Fonts link in `frontend/index.html`), Notifications, React Router with routes `/login`, `/instances`, `/instances/new`, `/instances/:id`, `/instances/:id/edit`, `*` (not found); a `RequireAuth` wrapper placeholder that will be filled in US1
- [X] T030 [P] Implement `Layout` (header with app name, `LanguageSwitcher`, slot for sign-out button; content area using logical CSS properties only) in `frontend/src/components/Layout.tsx` and `LanguageSwitcher` (fa/en segmented control) in `frontend/src/components/LanguageSwitcher.tsx`
- [X] T031 [P] Implement `NotFoundPage` in `frontend/src/pages/NotFoundPage.tsx` using translated text
- [X] T032 [P] Frontend test `frontend/tests/i18n.test.ts`: recursively compare key sets of `fa.json` and `en.json` and fail listing any key missing in either; assert switching to `en` sets `dir="ltr"` and to `fa` sets `dir="rtl"`

**Checkpoint**: Backend boots, migrations apply, protected routes reject unauthenticated
requests, frontend shell renders in both languages.

---

## Phase 3: User Story 1 - Admin signs in and out (Priority: P1) 🎯 MVP

**Goal**: The admin can sign in with username/password, sign out, and nothing else is reachable
without signing in. Lockout after repeated failures.

**Independent Test**: Fresh install → any page/action blocked → sign in with valid credentials
succeeds → sign out → blocked again (quickstart rows 1–4, 19).

### Tests for User Story 1 ⚠️

- [X] T033 [P] [US1] Unit tests for throttling and bootstrap in `backend/tests/unit/test_auth_service.py`: 4 failures then success resets; 5 failures within 15 min sets `locked_until = now + 15 min`; correct password while locked still fails; failure after window expiry restarts count at 1; unknown usernames are throttled too; bootstrap creates admin only when table empty, lower-cases username, and fails when table empty and env vars unset
- [X] T034 [P] [US1] API tests in `backend/tests/api/test_auth_api.py` per contracts/openapi.yaml: `POST /api/auth/login` success returns `{username}` and sets `mbp_session` cookie with HttpOnly and SameSite=Strict; wrong password, unknown user and locked-out all return 401 with identical body `{"code":"invalid_credentials"}`; `GET /api/auth/me` 200 with cookie, 401 without; `POST /api/auth/logout` → 204, cookie cleared, subsequent `/api/auth/me` → 401
- [X] T035 [P] [US1] Route-coverage test in `backend/tests/api/test_route_coverage.py` (SC-002): iterate `app.routes`, call every `/api` route and method without a cookie (path params filled with `1`) and assert 401, except the allow-list `GET /api/health`, `POST /api/auth/login`

### Implementation for User Story 1

- [X] T036 [P] [US1] Create `LoginAttempt` model in `backend/src/mbp/models/login_attempt.py` — table `login_attempts`: `username` String(64) PK "Lower-cased attempted username"; `failure_count` Integer "≥ 0"; `window_started_at` UTCDateTime "Start of current 15-min window"; `locked_until` nullable UTCDateTime; export from `models/__init__.py`
- [X] T037 [P] [US1] Implement `LoginAttemptRepository` (`get`, `upsert`, `delete`) in `backend/src/mbp/repositories/login_attempt_repository.py`
- [X] T038 [US1] Implement `AuthService` in `backend/src/mbp/services/auth_service.py`: `bootstrap_admin(settings)` per research §5; `login(username, password) -> plain_token` applying data-model `login_attempts` transitions (if locked → fail without checking password; unknown user → `dummy_verify()` then record failure; mismatch → record failure; success → delete attempt row, rehash if `needs_rehash`, `touch_last_login`, purge expired sessions, create session); every failure raises `ApiError(401, "invalid_credentials")`; `logout(session)` deletes it
- [X] T039 [US1] Call `AuthService.bootstrap_admin` on startup (lifespan) in `backend/src/mbp/main.py`; startup fails with message "No admin account exists: set MBP_ADMIN_USERNAME and MBP_ADMIN_PASSWORD" when needed; register the admin password with `register_secret` so it is redacted
- [X] T040 [US1] Implement auth router in `backend/src/mbp/api/auth.py` per contracts: `POST /auth/login` (no session dependency, but CSRF header required; `LoginRequest` with `username` 1–64 and `password` 1–1024 chars) → `Me` + `set_session_cookie`; `POST /auth/logout` → 204 + `clear_session_cookie`; `GET /auth/me` → `Me`; register in `main.py` (login public, others protected)
- [X] T041 [P] [US1] Add auth API functions `login`, `logout`, `me` in `frontend/src/api/auth.ts`, and a `useMe()` TanStack Query hook (no retry on 401)
- [X] T042 [P] [US1] Add `auth` translation keys (title, username, password, sign in, sign out, signing in, session expired) to `frontend/src/i18n/locales/fa.json` and `frontend/src/i18n/locales/en.json`
- [X] T043 [US1] Implement `LoginPage` in `frontend/src/pages/LoginPage.tsx`: username/password form (required fields), submit calls `login`, shows `errors.invalid_credentials` on 401, on success invalidates `me` and navigates to the originally requested path or `/instances`; language switcher visible on the login page
- [X] T044 [US1] Implement `RequireAuth` in `frontend/src/App.tsx`: while `useMe` loads show a loader; on 401 redirect to `/login` with return path; globally, any query/mutation error with code `not_authenticated` clears the query cache and redirects to `/login` with a "session expired" notification
- [X] T045 [US1] Add sign-out button to `frontend/src/components/Layout.tsx` calling `logout`, clearing the query cache and navigating to `/login`
- [X] T046 [P] [US1] Component test `frontend/tests/LoginPage.test.tsx`: shows translated generic error on 401; navigates on success (mock `apiFetch`)

**Checkpoint**: US1 independently functional — the panel is locked behind sign-in.

---

## Phase 4: User Story 2 - Register and maintain database instances (Priority: P1)

**Goal**: The admin can create, list, view, edit and delete instances; passwords are encrypted
and never returned.

**Independent Test**: Sign in, add an instance, see it listed, edit notes/port, replace the
password, confirm the password never appears, delete it (quickstart rows 6, 7, 10, 18, 20).

### Tests for User Story 2 ⚠️

- [X] T047 [P] [US2] Unit tests for instance rules in `backend/tests/unit/test_instance_service.py`: name trimmed and uniqueness case-insensitive; port outside 1–65535 rejected; notes over 2,000 chars rejected; host with scheme or spaces rejected, IPv6 literal accepted; empty password on update keeps ciphertext; changing host/port/username/password clears `server_type`, `server_version`, `last_test_*`; changing only notes/name does not
- [X] T048 [P] [US2] API tests in `backend/tests/api/test_instances_api.py` per contracts: `POST /api/instances` 201 with `has_password: true` and no `password`/`password_encrypted` key; duplicate name (different case) → 409 `name_taken`; invalid fields → 422 `validation_error` with `fields`; `GET /api/instances` ordered by name; `GET /api/instances/{id}` 404 `instance_not_found`; `PATCH` partial update incl. password keep/replace; `DELETE` → 204 and selections removed (insert a `db_selections` row directly to verify cascade)
- [X] T049 [P] [US2] Secret-leak test in `backend/tests/api/test_secret_leak.py` (SC-003): create an instance with password `Leak-Canary-9f3b`, then call every instance endpoint (list, get, patch with a validation error, create with a validation error, delete) capturing logs with `caplog` at DEBUG; assert the canary string appears in no response body and no log record

### Implementation for User Story 2

- [X] T050 [P] [US2] Create `DbInstance` model in `backend/src/mbp/models/instance.py` — table `db_instances`: `id`; `name` String(100) "Required, trimmed, unique (case-insensitive via `name_normalized`)"; `name_normalized` String(100) "Lower-cased name; unique index"; `host` String(255) "Required; hostname, IPv4 or IPv6 literal; no scheme, no spaces"; `port` Integer "Required, 1–65535, default 3306"; `username` String(255) "Required, 1–255 chars, any characters"; `password_encrypted` Text "Fernet token; required; never returned or logged"; `notes` Text "Optional, ≤ 2,000 characters"; `server_type` String(16) nullable "`mysql` | `mariadb`"; `server_version` String(64) nullable; `last_test_at` nullable; `last_test_ok` Boolean nullable; `last_test_error_code` String(32) nullable; `created_at`/`updated_at`; relationship `selections` with `cascade="all, delete-orphan"`; `__repr__` excludes `password_encrypted`
- [X] T051 [P] [US2] Create `DbSelection` model in `backend/src/mbp/models/selection.py` — table `db_selections`: `id`; `instance_id` FK → `db_instances.id` ON DELETE CASCADE; `database_name` String(64) "Required; unique together with `instance_id`"; `created_at`; export both models from `models/__init__.py`
- [X] T052 [US2] Implement `InstanceRepository` (`list_ordered_by_name`, `get`, `get_by_name_normalized`, `add`, `delete`) in `backend/src/mbp/repositories/instance_repository.py`
- [X] T053 [US2] Add instance schemas to `backend/src/mbp/api/schemas.py`: `InstanceCreate`, `InstanceUpdate`, `Instance` exactly as contracts/openapi.yaml (password fields typed `SecretStr`; `Instance` has `has_password` and no password field); host validator rejecting `://`, whitespace and empty; `notes` default `""`
- [X] T054 [US2] Implement `InstanceService` in `backend/src/mbp/services/instance_service.py`: `create`, `update`, `delete`, `get`, `list` applying data-model rules (normalize name, `name_taken` 409, encrypt password with `crypto.encrypt`, keep password when empty, clear detection/test fields when connection fields change, `instance_not_found` 404); provide `get_decrypted_password(instance)` for internal use by the probe only
- [X] T055 [US2] Implement instances router CRUD in `backend/src/mbp/api/instances.py`: `GET /instances`, `POST /instances` (201), `GET /instances/{id}`, `PATCH /instances/{id}`, `DELETE /instances/{id}` (204); register as protected in `main.py`
- [X] T056 [P] [US2] Add typed API functions and TanStack hooks (`useInstances`, `useInstance`, `useCreateInstance`, `useUpdateInstance`, `useDeleteInstance`) in `frontend/src/api/instances.ts` with TS types mirroring `Instance`, `InstanceCreate`, `InstanceUpdate`
- [X] T057 [P] [US2] Add `instances` translation keys (list title, empty state, add, edit, delete, delete confirm text with instance name, fields name/host/port/username/password/notes, "password stored — leave empty to keep", host hint explaining `localhost` inside a container and using `host.docker.internal` or the container name, server type/version labels, last test labels, validation messages) to both locale files
- [X] T058 [P] [US2] Implement `ConfirmDialog` in `frontend/src/components/ConfirmDialog.tsx` (translated title/body/confirm/cancel, destructive style)
- [X] T059 [US2] Implement `InstancesPage` in `frontend/src/pages/InstancesPage.tsx`: table of name, host, port, username, server type/version (or "unknown"), last test result and `formatDateTime(last_test_at)`; "Add instance" button; row click to `/instances/:id`; empty state
- [X] T060 [US2] Implement `InstanceFormPage` in `frontend/src/pages/InstanceFormPage.tsx` for create and edit: Mantine form + zod (name 1–100, host 1–255 without scheme/spaces, port 1–65535 default 3306, username 1–255, password required on create / optional on edit with "password stored" hint and empty placeholder, notes ≤ 2,000 with counter); map server `fields` and `name_taken` to field errors; host hint shown under the host field; after save navigate to the instance detail page
- [X] T061 [US2] Implement initial `InstanceDetailPage` in `frontend/src/pages/InstanceDetailPage.tsx`: shows instance info and notes, Edit button, Delete button with `ConfirmDialog` (on confirm delete and navigate to `/instances`); leave placeholders for the connection-test (US3) and databases (US4) sections
- [X] T062 [P] [US2] Component test `frontend/tests/InstanceFormPage.test.tsx`: edit mode shows empty password with "password stored" hint and omits `password` from the PATCH body when left empty; invalid port shows translated error

**Checkpoint**: US1 + US2 work — instances can be fully managed and passwords never leak.

---

## Phase 5: User Story 3 - Test the connection to an instance (Priority: P2)

**Goal**: Test saved instances and unsaved form values; show server type/version on success or
a specific, translated error on failure, within 10 seconds.

**Independent Test**: Test reachable MySQL and MariaDB (type + version shown), then wrong
password, unknown host, closed port, blackholed IP (quickstart rows 5, 8, 9, 16).

**Depends on**: US2 (saved instances and the instance form).

### Tests for User Story 3 ⚠️

- [X] T063 [P] [US3] Unit tests for the probe in `backend/tests/unit/test_mysql_probe.py` (no network; patch `pymysql.connect`): version parsing (`8.4.3`, `11.8.2-MariaDB-ubu2404`, `5.5.5-10.11.6-MariaDB` → `10.11.6`); type detection from `VERSION()`/`@@version_comment`; classification table from research §7 (`gaierror` → `host_not_found`, errno 111 → `connection_refused`, socket timeout and deadline exceeded → `timeout`, 1045/1044/1698 → `auth_rejected`, others → `server_error`); sanitizer removes the password from server messages and truncates to 500 chars
- [X] T064 [P] [US3] API tests in `backend/tests/api/test_connection_api.py` (probe patched): `POST /api/instances/test-connection` returns result and stores nothing; `POST /api/instances/{id}/test-connection` persists `server_type`, `server_version`, `last_test_at`, `last_test_ok`, `last_test_error_code`; 404 for unknown id; result never contains the password
- [X] T065 [P] [US3] Integration tests in `backend/tests/integration/test_probe_real.py` marked `integration`, parametrized over testcontainers `mysql:8.4` and `mariadb:11.8` (session-scoped fixtures in `backend/tests/integration/conftest.py`): success detects correct type and version; wrong password → `auth_rejected`; closed port on localhost → `connection_refused`; host `nonexistent.invalid` → `host_not_found`; `10.255.255.1` → `timeout` in ≤ 12 s

### Implementation for User Story 3

- [X] T066 [US3] Implement `mysql_probe` in `backend/src/mbp/services/mysql_probe.py`: dataclasses `ConnParams(host, port, username, password)` and `ProbeResult(ok, server_type, server_version, error_code, error_detail, tested_at)`; `test_connection(params, timeout=settings.connect_timeout_seconds)` connecting with PyMySQL (`connect_timeout`, `read_timeout`, `write_timeout` = timeout, `charset="utf8mb4"`), running `SELECT VERSION(), @@version_comment`, closing the connection; the whole call executed in a worker thread with an overall deadline (`concurrent.futures` `result(timeout=...)`) mapping deadline expiry to `timeout`; error classification and sanitization per research §7; never log params.password
- [X] T067 [US3] Add `ConnectionParams` and `ConnectionTestResult` schemas to `backend/src/mbp/api/schemas.py` per contracts
- [X] T068 [US3] Add `InstanceService.test_saved(id)` in `backend/src/mbp/services/instance_service.py` that decrypts the password, runs the probe and persists `server_type`, `server_version`, `last_test_at`, `last_test_ok`, `last_test_error_code` (on failure keep previous type/version); if the instance was deleted meanwhile, discard the result without error
- [X] T069 [US3] Add endpoints `POST /instances/test-connection` and `POST /instances/{id}/test-connection` to `backend/src/mbp/api/instances.py` (declare the static path before `/{id}` routes)
- [X] T070 [P] [US3] Add `testConnectionParams` and `useTestInstance` mutation (invalidates the instance and list queries) in `frontend/src/api/instances.ts`
- [X] T071 [P] [US3] Add `connection` translation keys (test connection, testing…, success "Connected to {{type}} {{version}}", failure title, per-code explanatory sentences with a suggested fix for `host_not_found`, `connection_refused`, `timeout`, `auth_rejected`, `server_error`) to both locale files
- [X] T072 [US3] Implement `ConnectionResult` component in `frontend/src/components/ConnectionResult.tsx`: green alert with type/version on success, red alert with translated title + explanation on failure, `error_detail` shown as secondary text for `server_error`, and tested time via `formatDateTime`
- [X] T073 [US3] Add "Test connection" to `frontend/src/pages/InstanceFormPage.tsx` (uses current form values; on edit with empty password, test the saved instance after confirming unsaved connection fields are unchanged, otherwise require the password) and to `frontend/src/pages/InstanceDetailPage.tsx` (tests saved instance); disable the button while running and show `ConnectionResult`

**Checkpoint**: US3 works against both MySQL and MariaDB with clear errors.

---

## Phase 6: User Story 4 - Choose which databases to back up (Priority: P2)

**Goal**: List an instance's databases (system schemas hidden by default), select which are
included in backups, persist the selection, show "missing on server" and unreachable states.

**Independent Test**: Open a reachable instance, system schemas hidden, select two databases,
save, reload — still selected (quickstart rows 11–15).

**Depends on**: US2 (saved instances); reuses the probe connection code from US3.

### Tests for User Story 4 ⚠️

- [X] T074 [P] [US4] Unit tests for selection logic in `backend/tests/unit/test_selection_service.py`: merge marks `is_system` for the four system schemas and `selectable=false` for `information_schema`, `performance_schema`, `sys`; selected-but-absent names get `missing=true`; saving rejects non-selectable names (`not_selectable`) and names neither on server nor already selected (`unknown_database`); when unreachable, only removals and already-selected names are accepted; save replaces the set atomically
- [X] T075 [P] [US4] API tests in `backend/tests/api/test_databases_api.py` (probe patched): `GET /api/instances/{id}/databases` reachable and unreachable shapes per contracts `DatabaseList`; `PUT /api/instances/{id}/selection` success returns updated list; 422 cases with codes; 404 for unknown id
- [X] T076 [P] [US4] Integration test in `backend/tests/integration/test_databases_real.py` marked `integration`, parametrized over MySQL 8.4 and MariaDB 11.8: create databases `shop` and `blog`, list shows both plus system schemas flagged; select both and save; drop `blog` → listed as missing and still selected; a user granted only on `shop` sees only `shop` (and `information_schema`); create 500 databases and assert listing completes in < 5 s (SC-006)

### Implementation for User Story 4

- [X] T077 [US4] Add `list_databases(params, timeout)` to `backend/src/mbp/services/mysql_probe.py` running `SHOW DATABASES` with the same connect/deadline/classification behaviour as `test_connection`, returning names or a failure `ProbeResult`
- [X] T078 [P] [US4] Implement `SelectionRepository` (`list_names(instance_id)`, `replace(instance_id, names)` in one transaction) in `backend/src/mbp/repositories/selection_repository.py`
- [X] T079 [US4] Implement `SelectionService` in `backend/src/mbp/services/selection_service.py`: constants `SYSTEM_SCHEMAS = {"information_schema","performance_schema","mysql","sys"}` and `NON_SELECTABLE = {"information_schema","performance_schema","sys"}`; `get_listing(instance_id)` merging live names with stored selections into `DatabaseEntry` items sorted by name (unreachable → only stored selections with `missing=false`, plus `error_code`/`error_detail`); `save(instance_id, names)` applying the validation rules from data-model `db_selections` and returning the fresh listing
- [X] T080 [US4] Add `DatabaseEntry`, `DatabaseList`, `SelectionUpdate` (`databases`: unique strings 1–64 chars) schemas to `backend/src/mbp/api/schemas.py` and endpoints `GET /instances/{id}/databases` and `PUT /instances/{id}/selection` to `backend/src/mbp/api/instances.py`
- [X] T081 [P] [US4] Add `useDatabases(id)` query and `useSaveSelection(id)` mutation in `frontend/src/api/instances.ts`
- [X] T082 [P] [US4] Add `databases` translation keys (section title, show system schemas, system badge, missing-on-server badge with hint, filter placeholder, selected count "{{count}} selected", save selection, saved, unreachable message, privileges note "Only databases visible to this user are listed", empty state) to both locale files
- [X] T083 [US4] Implement `DatabaseSelector` in `frontend/src/components/DatabaseSelector.tsx`: name filter input; "show system schemas" switch (off by default); checkbox list (virtualized or paginated so 1,000 entries stay responsive) with system and missing badges, non-selectable rows disabled; local draft state with Save/Reset; unreachable state shows translated error with stored selections still listed and a Retry button; privileges note
- [X] T084 [US4] Add the databases section using `DatabaseSelector` to `frontend/src/pages/InstanceDetailPage.tsx`
- [X] T085 [P] [US4] Component test `frontend/tests/DatabaseSelector.test.tsx`: system schemas hidden by default and shown after toggle; `information_schema` checkbox disabled, `mysql` enabled; missing badge rendered; filter narrows the list

**Checkpoint**: All four user stories work independently and together.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Packaging, CI and end-to-end validation

- [X] T086 [P] Create `backend/Dockerfile`: builder stage with `uv` installing locked deps into a venv; runtime `python:3.12-slim` with only the venv and app, non-root user `mbp` (uid 10001), `/data` volume owned by it, `CMD` running `alembic upgrade head` then `uvicorn mbp.main:app --host 0.0.0.0 --port 8000`; plus `backend/.dockerignore`
- [X] T087 [P] Create `frontend/Dockerfile` (stage 1 `node:22-alpine` `npm ci && npm run build`; stage 2 `nginxinc/nginx-unprivileged:alpine` copying `dist/`) and `frontend/nginx.conf` (SPA fallback to `index.html`, `location /api/` proxy to `http://backend:8000`, security headers `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, a CSP allowing self and Google Fonts); plus `frontend/.dockerignore`
- [X] T088 Create `docker-compose.yml` at repository root: services `backend` (env from `.env`, named volume `mbp-data:/data`, `extra_hosts: ["host.docker.internal:host-gateway"]`, healthcheck on `/api/health`, no published ports) and `frontend` (port `8080:8080`, depends on healthy backend); one network `mbp-net`; no `docker.sock` mounts
- [X] T089 [P] Add CI workflow `.github/workflows/ci.yml`: backend job (ruff check, ruff format --check, pytest, pytest -m integration with Docker), migration smoke job running `alembic upgrade head` against a `postgres:16` service container (Principle V), frontend job (lint, format:check, test, build)
- [X] T090 [P] Write `README.md` at repository root: purpose, quick start with docker compose, env vars from `.env.example`, generating a Fernet key, how admin bootstrap works (env vars only used when no admin exists), addressing servers on the host (`host.docker.internal`) or in other containers (shared network + container name), Podman note, running tests
- [X] T091 Review all frontend components for hard-coded strings and physical CSS properties (`left/right`, `margin-left` etc.); replace with translation keys and logical properties; verify both languages render every screen (SC-008)
- [ ] T092 Run the full [quickstart.md](./quickstart.md) validation (automated checks and all 20 manual scenarios) and fix any failures

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup — blocks all user stories
- **US1 (Phase 3)**: depends on Foundational only
- **US2 (Phase 4)**: depends on Foundational only (API tests use the `auth_client` fixture, not
  the login endpoint); the frontend pages are reached through US1's `RequireAuth` when both exist
- **US3 (Phase 5)**: depends on US2 (instance model, service, form and detail page)
- **US4 (Phase 6)**: depends on US2; its probe function (T077) extends the module created in T066,
  so do US3 before US4 or implement T066's connection helper first
- **Polish (Phase 7)**: depends on all stories

### Story Completion Order

```text
Setup → Foundational ─┬─> US1 (auth) ───────────────────────────┐
                      └─> US2 (instances) ─> US3 (test conn) ─> US4 (databases) ─> Polish
```

### Within Each User Story

- Tests first, confirm they fail
- Models → repositories → services → API routes → frontend API hooks → pages/components
- Translation keys added in the same story as the UI that uses them

### Parallel Opportunities

- Setup: T003–T007 in parallel after T001–T002
- Foundational: T010–T015, T017–T018 in parallel; frontend T026–T028, T030–T032 in parallel with
  the backend foundation
- After Foundational: US1 and US2 in parallel (different files except `main.py` router
  registration and `Layout.tsx`)
- Within each story, all tasks marked [P] (tests, models, locale keys, frontend API hooks)

---

## Parallel Example: User Story 2

```bash
# Tests together:
Task: "Unit tests for instance rules in backend/tests/unit/test_instance_service.py"
Task: "API tests in backend/tests/api/test_instances_api.py"
Task: "Secret-leak test in backend/tests/api/test_secret_leak.py"

# Models together:
Task: "Create DbInstance model in backend/src/mbp/models/instance.py"
Task: "Create DbSelection model in backend/src/mbp/models/selection.py"

# Frontend preparation together:
Task: "Add typed API functions and hooks in frontend/src/api/instances.ts"
Task: "Add instances translation keys to both locale files"
Task: "Implement ConfirmDialog in frontend/src/components/ConfirmDialog.tsx"
```

---

## Implementation Strategy

### MVP First

1. Phase 1 Setup → Phase 2 Foundational
2. Phase 3 (US1) → **validate**: panel locked behind sign-in
3. Phase 4 (US2) → **validate**: instances managed, passwords never leak

US1 alone is a secure but empty shell; US1 + US2 is the smallest release that delivers value
(both are P1).

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. + US1 → sign-in works
3. + US2 → instance management (MVP release)
4. + US3 → connection testing with MySQL/MariaDB detection
5. + US4 → database selection (input for the upcoming backup feature)
6. Polish → containers, CI, docs, full quickstart run

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- Never log, return, or echo instance passwords or the admin password (Principle I)
- Commit after each task or logical group; stop at any checkpoint to validate the story

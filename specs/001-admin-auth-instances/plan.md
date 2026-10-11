# Implementation Plan: Admin Authentication and Database Instance Management

**Branch**: `001-admin-auth-instances` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-admin-auth-instances/spec.md`

## Summary

First feature of a greenfield project: admin sign-in with server-side sessions and login
throttling, CRUD for MySQL/MariaDB instances with encrypted passwords that are never returned,
connection testing with server type/version detection and classified, translatable errors, and
per-instance selection of databases to include in backups. Delivered as a FastAPI backend
(SQLAlchemy + Alembic, SQLite default) and a bilingual React SPA, packaged with multi-stage
Dockerfiles and one compose file. This feature also lays down the project skeleton
(repositories, settings, i18n, auth dependency, test harness) that later features build on.
Details: [research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend); TypeScript 5.x on Node.js 22 (frontend build)

**Primary Dependencies**: Backend — FastAPI, Pydantic v2, SQLAlchemy 2.0 (sync), Alembic,
PyMySQL, cryptography (Fernet), argon2-cffi, uvicorn. Frontend — React 18, Vite, React Router,
TanStack Query, react-i18next, Mantine v7, zod.

**Storage**: Internal DB via SQLAlchemy; SQLite default (`MBP_DATABASE_URL`), PostgreSQL/MySQL by
URL change only. Target servers accessed read-only over the network (connect + `SHOW DATABASES`).

**Testing**: pytest + FastAPI TestClient (unit/API, SQLite); pytest + testcontainers against
`mysql:8.4` and `mariadb:11.8` (integration, marker `integration`); Vitest + Testing Library
(frontend).

**Target Platform**: Linux containers (Docker or Podman); modern evergreen browsers.

**Project Type**: Web application (SPA frontend + REST backend).

**Performance Goals**: Connection test result ≤ 12 s worst case (10 s deadline); database list
of 500+ databases shown ≤ 5 s; sign-in + register instance < 2 min for the admin.

**Constraints**: No secrets in responses/logs/process args; every route authenticated except
login and health; no extra infrastructure services; no `docker.sock`; all UI text translated
(fa/en) with RTL/LTR.

**Scale/Scope**: Single admin; tens of instances; up to ~1,000 databases per instance; ~6
screens (login, instance list, instance form, instance detail/databases, layout with language
switcher, not-found).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | How this plan complies |
|---|-----------|--------|------------------------|
| I | Security first | ✅ Pass | Auth dependency applied globally with explicit allow-list (login, health); Argon2id admin hash; Fernet-encrypted instance passwords, key from `MBP_ENCRYPTION_KEY`, startup fails without it; responses expose only `has_password`; log redaction filter; route-coverage and secret-leak tests. |
| II | Trustworthy backups | ✅ N/A-compatible | No backups in this feature. Connection-test outcomes are persisted and shown (no silent failures). |
| III | MySQL & MariaDB | ✅ Pass | Server type + version detected on test and stored; integration tests parametrized over MySQL 8.4 and MariaDB 11.8. |
| IV | Simple architecture | ✅ Pass | React SPA + FastAPI only; no queues/caches/workers. APScheduler not needed yet. |
| V | DB-agnostic storage | ✅ Pass | SQLAlchemy ORM + repository classes, portable types only, Alembic migrations; tests run on SQLite, migrations also smoke-tested on PostgreSQL in CI. |
| VI | Containerized | ✅ Pass | Separate multi-stage Dockerfiles, non-root; one compose file, isolated network; targets reached by host/port; `host.docker.internal` via `host-gateway`; no `docker.sock`. |
| VII | Streaming | ✅ N/A-compatible | No dumps in this feature; database listing is small, bounded data. |
| VIII | Bilingual UI | ✅ Pass | react-i18next with `fa.json`/`en.json`; `dir` switched on `<html>`; Mantine RTL; API returns error codes translated by UI; `Intl.DateTimeFormat` per locale; key-parity test. |
| IX | Testing | ✅ Pass | pytest for services and every endpoint; real-container integration tests for connection/listing. |
| X | Code quality | ✅ Pass | ruff (lint + format), ESLint + Prettier, English comments; enforced in CI. |
| XI | Pluggable storage | ✅ N/A-compatible | No remote storage in this feature. |

**Gate result (pre-research)**: PASS — no violations.
**Gate result (post-design)**: PASS — data model uses only portable types; contracts never
include password fields in responses; no new services introduced.

## Project Structure

### Documentation (this feature)

```text
specs/001-admin-auth-instances/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── openapi.yaml     # Phase 1 output
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
backend/
├── pyproject.toml               # deps, ruff and pytest config
├── alembic.ini
├── Dockerfile                   # multi-stage, non-root
├── migrations/
│   └── versions/                # 0001_auth_and_instances.py
├── src/mbp/
│   ├── main.py                  # app factory, router registration, startup checks
│   ├── config.py                # settings from MBP_* env vars
│   ├── db.py                    # engine/session factory
│   ├── logging.py               # secret-redaction filter
│   ├── security/
│   │   ├── passwords.py         # Argon2id hash/verify
│   │   ├── crypto.py            # MultiFernet encrypt/decrypt
│   │   └── sessions.py          # token create/lookup, auth + CSRF dependencies
│   ├── models/                  # SQLAlchemy ORM models
│   ├── repositories/            # admin, session, login_attempt, instance, selection
│   ├── services/
│   │   ├── auth_service.py      # login, throttling, logout, bootstrap admin
│   │   ├── instance_service.py  # CRUD rules, change-invalidates-test logic
│   │   ├── mysql_probe.py       # connect, detect type/version, classify errors, list DBs
│   │   └── selection_service.py # merge listing + selections, validation
│   ├── api/
│   │   ├── schemas.py           # Pydantic request/response models
│   │   ├── errors.py            # Error model + exception handlers
│   │   ├── health.py
│   │   ├── auth.py
│   │   └── instances.py
└── tests/
    ├── conftest.py              # app + SQLite fixtures, authenticated client
    ├── unit/                    # crypto, passwords, throttling, error classification, selection merge
    ├── api/                     # every endpoint, route-coverage, secret-leak
    └── integration/             # testcontainers MySQL 8.4 + MariaDB 11.8

frontend/
├── package.json
├── vite.config.ts               # dev proxy /api → backend
├── Dockerfile                   # multi-stage → nginx-unprivileged
├── nginx.conf                   # SPA fallback + /api proxy
├── src/
│   ├── main.tsx
│   ├── App.tsx                  # router, auth guard, Mantine + direction providers
│   ├── i18n/
│   │   ├── index.ts             # i18next setup, dir/lang sync, date formatting helper
│   │   └── locales/{fa,en}.json
│   ├── api/                     # fetch client (adds X-Requested-With), typed calls, error-code mapping
│   ├── components/              # Layout, LanguageSwitcher, ConfirmDialog, ConnectionResult
│   └── pages/
│       ├── LoginPage.tsx
│       ├── InstancesPage.tsx
│       ├── InstanceFormPage.tsx
│       └── InstanceDetailPage.tsx   # info, test connection, databases + selection
└── tests/                       # i18n key parity, component tests

docker-compose.yml               # isolated network, data volume, host-gateway
.env.example
```

**Structure Decision**: Web application layout with `backend/` and `frontend/` at the repository
root, matching the constitution's two-Dockerfile, one-compose deployment. Backend code lives in a
`src/mbp` package (layers: api → services → repositories → models) so later features (backups,
scheduler, storage) add modules alongside without restructuring.

## Complexity Tracking

No constitution violations; nothing to justify.

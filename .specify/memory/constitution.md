<!--
Sync Impact Report
==================
Version change: (unversioned template) → 1.0.0
Bump rationale: Initial ratification; all placeholders replaced with project-specific content.

Modified principles (template placeholder → new title):
- [PRINCIPLE_1_NAME] → I. Security First (NON-NEGOTIABLE)
- [PRINCIPLE_2_NAME] → II. Trustworthy, Verified Backups (NON-NEGOTIABLE)
- [PRINCIPLE_3_NAME] → III. MySQL and MariaDB Compatibility
- [PRINCIPLE_4_NAME] → IV. Simple Architecture
- [PRINCIPLE_5_NAME] → V. Database-Agnostic Internal Storage
Added principles:
- VI. Containerized Deployment, Network-Only Access
- VII. Streaming for Large Databases
- VIII. Bilingual UI (Persian RTL / English LTR)
- IX. Testing Against Real Databases
- X. Code Quality and Consistency
- XI. Pluggable Remote Storage (S3-Compatible in MVP)

Added sections:
- Project Scope (MVP) (was [SECTION_2_NAME])
- Development Workflow & Quality Gates (was [SECTION_3_NAME])

Removed sections: none

Templates: not modified by this command (templates read the constitution at runtime).

Deferred TODOs: none. Ratification date set to the date of first adoption (2026-10-11).
-->

# MySQL Backup Panel Constitution

A self-hosted web application for managing backups of MySQL and MariaDB databases. Admins
register multiple database instances (on the host machine or inside Docker/Podman containers,
reached over the network), choose which databases to back up, run backups manually or on a
schedule, compress and download them, upload them to S3-compatible remote storage, and
automatically delete old backups via retention policies.

## Core Principles

### I. Security First (NON-NEGOTIABLE)

- Every API endpoint and every UI page MUST require an authenticated admin session. The only
  unauthenticated surfaces permitted are the login endpoint/page and a minimal health check that
  exposes no data.
- Target-database credentials and remote-storage secrets MUST be encrypted at rest. The
  encryption key MUST be supplied via an environment variable and MUST NOT be stored in the
  repository, the internal database, or container images. The application MUST refuse to start
  if the key is missing.
- Secrets MUST NOT appear in logs, error messages, backup run records, process listings
  (e.g. passwords passed on a dump tool's command line), or API responses. APIs MAY indicate that
  a secret is set but MUST NOT return its value.

Rationale: the panel holds credentials to production databases and copies of their data; a
single leak compromises every registered instance.

### II. Trustworthy, Verified Backups (NON-NEGOTIABLE)

- Every backup run MUST record: status, start/end time, duration, file size, checksum
  (SHA-256), and an error message on failure.
- Every backup file MUST be verified after creation: checksum computed and stored, and the
  compressed archive integrity-tested. A run whose verification fails MUST be marked failed.
- Failures (dump, compression, verification, upload, retention) MUST be persisted and visible in
  the UI. No failure path may be swallowed silently; a run MUST NOT remain in a "running" state
  after the process that owns it has stopped.
- Retention MUST only delete backups that are fully recorded, and MUST record what it deleted.

Rationale: an unverified or silently failed backup is worse than none, because it creates false
confidence.

### III. MySQL and MariaDB Compatibility

- On connection, the system MUST detect the server type (MySQL vs MariaDB) and version and store
  it with the instance.
- The dump tool and options MUST be selected to match the detected server (e.g.
  `mysqldump` vs `mariadb-dump`, `--single-transaction` for consistent InnoDB snapshots,
  inclusion of routines/triggers/events).
- Integration tests MUST cover both MySQL 8 and the current MariaDB LTS release.

Rationale: the two servers have diverged in tooling and flags; assuming one breaks the other.

### IV. Simple Architecture

- The system consists of a React SPA frontend and a FastAPI backend. Scheduling runs inside the
  backend process using APScheduler.
- The MVP MUST NOT introduce message queues, separate worker services, caches, or other
  additional infrastructure. Any such addition requires a constitution amendment with
  justification.

Rationale: a self-hosted tool must be easy to deploy, understand, and operate.

### V. Database-Agnostic Internal Storage

- The application's own data MUST be accessed through SQLAlchemy ORM behind a Repository layer;
  business logic MUST NOT issue raw SQL or depend on a specific dialect.
- SQLite is the default. PostgreSQL and MySQL MUST work by changing only the connection URL.
- All schema changes MUST be delivered as Alembic migrations; no runtime `create_all` in
  production paths.

Rationale: operators choose their own storage; the codebase stays portable and testable.

### VI. Containerized Deployment, Network-Only Access

- Frontend and backend MUST each have a separate, optimized multi-stage Dockerfile (minimal
  runtime image, no build toolchain in the final stage, non-root user).
- A single `docker-compose.yml` MUST run the stack on an isolated network.
- Target databases MUST be reached over the network only. The Docker/Podman socket
  (`docker.sock`) MUST NEVER be mounted or used.

Rationale: socket access grants host root; network access is sufficient and far safer.

### VII. Streaming for Large Databases

- Dumps MUST be streamed from the dump tool through compression (and checksumming) to the
  destination without loading the full dump into memory.
- Downloads and remote uploads MUST also stream (chunked / multipart), keeping memory usage
  bounded regardless of backup size.

Rationale: production databases can be far larger than the container's available memory.

### VIII. Bilingual UI (Persian RTL / English LTR)

- The UI MUST be fully available in Persian and English, with a visible language switcher.
- Persian MUST render with RTL layout; English MUST render with LTR layout.
- No user-facing string may be hard-coded in components; all text MUST come from translation
  files, and both locales MUST have complete keys.
- Dates, times, and numbers MUST be formatted according to the selected locale.

Rationale: the primary audience uses both languages; partial translation or broken direction
makes the tool unusable.

### IX. Testing Against Real Databases

- Backend business logic and API endpoints MUST be covered by pytest tests.
- Backup-related integration tests MUST run against real MySQL 8 and MariaDB LTS containers;
  mocks are not acceptable for verifying dump, compression, and verification behavior.
- A change that touches backup, retention, encryption, or authentication MUST include tests.

Rationale: backup correctness can only be proven against the real servers it targets.

### X. Code Quality and Consistency

- Python code MUST pass `ruff` formatting and linting.
- TypeScript code MUST pass ESLint and Prettier.
- Code comments MUST be written in English (regardless of UI language).

Rationale: consistent tooling keeps review focused on behavior rather than style.

### XI. Pluggable Remote Storage (S3-Compatible in MVP)

- Remote storage MUST be accessed through a storage interface; backup and retention logic MUST
  NOT depend on a specific provider.
- The MVP implements only S3-compatible storage. Other backends (SFTP, etc.) MUST be addable by
  implementing the interface, without changes to backup logic.

Rationale: keeps the MVP small while preserving a clean extension point.

## Project Scope (MVP)

In scope:

- Admin authentication.
- Registering multiple MySQL/MariaDB instances (host or containerized, reached over the network)
  with connection testing and server type/version detection.
- Selecting which databases per instance to back up.
- Manual and scheduled backups, compressed and verified.
- Backup history with status, size, checksum, duration, and errors.
- Downloading backup files.
- Uploading backups to S3-compatible storage.
- Retention policies that automatically delete old backups (local and remote).
- Bilingual (Persian/English) UI.

Out of scope for MVP: restore, notifications (email/chat/webhooks), non-S3 remote storage,
multi-user roles beyond admin, and additional infrastructure services. Introducing any of these
requires a scope amendment to this section.

## Development Workflow & Quality Gates

- Every change MUST pass formatting, linting, and the test suite before merge.
- Feature plans (`/speckit-plan`) MUST include a Constitution Check that evaluates each
  principle; any deviation MUST be listed with justification in the plan's complexity tracking.
- Reviews MUST explicitly check: authentication on new endpoints/pages, absence of secrets in
  logs and responses, streaming (no full-file buffering), translation keys for new UI text, and
  Alembic migrations for schema changes.
- New dependencies or services MUST be justified against Principle IV.

## Governance

- This constitution supersedes all other project practices and guidance. Where another document
  conflicts with it, the constitution wins.
- Amendments are made by updating this file, including a Sync Impact Report describing the
  change, and updating dependent artifacts where needed.
- Versioning follows semantic versioning:
  - MAJOR: removal or backward-incompatible redefinition of a principle or governance rule.
  - MINOR: a new principle or section, or materially expanded guidance.
  - PATCH: clarifications, wording, and typo fixes.
- Compliance is verified during planning (Constitution Check) and code review. Unjustified
  violations block merge.

**Version**: 1.0.0 | **Ratified**: 2026-10-11 | **Last Amended**: 2026-10-11

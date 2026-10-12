<!--
Sync Impact Report
==================
Version change: 2.1.0 → 3.0.0
Bump rationale: MAJOR. A rule is redefined: an agent on another server than the panel's
publishes a port (HTTPS) instead of listening only on the internal compose network, and may
dump databases on the panel's behalf.

Modified principles:
- I. Security First: remote agents are trusted only through a pinned certificate and
  per-server tokens that never travel (signed requests); tokens are encrypted at rest and
  shown once.
- VI. Containerized Deployment: the agent rule now has a local mode (unchanged) and a remote
  mode (HTTPS on the host's network, pinned certificate, signed requests); the allow-list
  gains database connection tests, database lists and dumps with the same fixed tool options.
Modified sections:
- Project Scope (MVP): adds managing several servers from one panel.

Templates: not modified. Deferred TODOs: none.

Previous report (2.1.0)
-----------------------
Version change: 2.0.0 → 2.1.0
Bump rationale: MINOR. Materially expanded guidance: the agent may now deploy registered
projects (git + docker compose), and deployment enters the scope.

Modified principles:
- I. Security First: deploy credentials and environment values encrypted at rest and masked in
  logs; bot deploys confirmed with a TOTP code; the panel's own compose project protected.
- VI. Containerized Deployment: the agent's allow-list gains deploy operations for registered
  projects, always as fixed argument lists inside the projects directory.
Modified sections:
- Project Scope (MVP): adds deploying projects from git with docker compose (phase 2).

Templates: not modified. Deferred TODOs: none.

Previous report (2.0.0)
-----------------------
Version change: 1.1.0 → 2.0.0
Bump rationale: MAJOR. Principle VI no longer forbids docker.sock outright: an optional,
isolated agent service may use it. Principle IV allows that one additional service.

Modified principles:
- I. Security First: rules for container management (the agent's limits, the panel's own
  containers protected, audit log, read-only mode, bot actions confirmed with a TOTP code,
  environment values never returned, bot logs off by default).
- IV. Simple Architecture: one optional additional service, the Docker agent.
- VI. Containerized Deployment: the backend and frontend still never mount docker.sock; only
  the agent may, and only when an admin turns it on.
Modified sections:
- Project Scope (MVP): adds container monitoring and control (phase 1 of container
  management); deployment, exec, and creating/removing containers stay out of scope.

Templates: not modified. Deferred TODOs: none.

Previous report (1.1.0)
-----------------------
Version change: 1.0.0 → 1.1.0
Bump rationale: MINOR. Materially expanded guidance: a second admin interface (messenger
bots) under Principle I, in-process bot polling under Principle IV, and notifications moved
from "out of scope" into the MVP scope.

Modified principles:
- I. Security First: rules for the Bale/Telegram bot interface (registered admins only,
  private chats only, confirmation for destructive actions, no secrets through chat, bot
  tokens and webhook secrets encrypted at rest).
- IV. Simple Architecture: bot long polling and alert delivery run as threads inside the
  backend; no inbound webhook endpoint or extra service.
Modified sections:
- Project Scope (MVP): adds messenger bots and notifications/alerts; removes notifications
  from "out of scope".

Templates: not modified. Deferred TODOs: none.

Previous report (1.0.0)
-----------------------
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
- Messenger bots (Bale, Telegram) are a second admin interface and MUST answer only users
  registered as bot admins in the panel (by numeric user ID or a one-time, expiring link code
  stored only as a hash), and only in private chats. Anyone else MAY learn their own user ID and
  nothing else. Destructive actions MUST ask for confirmation. Secrets (database passwords,
  storage keys, tokens) MUST NOT be entered or shown through a bot. Bot tokens and webhook
  signing secrets are secrets under this principle. Sending backup files through a bot copies
  data to a third party and MUST be off unless an admin turns it on.

- Container management goes through the Docker agent only (see VI). The panel MUST refuse to
  control its own containers, MUST record every start/stop/restart (who, from where, result)
  in an audit log, and MUST offer a read-only mode and per-container hide/lock rules. The
  agent MUST NOT return environment variable values. Controlling a container from a bot
  MUST require a fresh TOTP code of a panel account with two-step verification on. Showing
  container logs in a bot copies them to a third party and MUST be off unless an admin
  turns it on.
- Other servers: the panel MUST trust an agent on another server only through the certificate
  it pinned when the server was connected, after the agent proved it holds that server's
  token. Every request MUST be signed with the token, bound to the time and to the pinned
  certificate; the token MUST NOT be sent over the network, MUST be encrypted at rest, and
  MUST be shown only once (a new token replaces it). Database credentials MAY be sent to a
  server's agent only over that pinned connection, for one operation, and the agent MUST NOT
  store them.
- Deploying projects: repository credentials (tokens, SSH keys) and environment values MUST be
  encrypted at rest, never returned by the API, never passed on a command line, and masked in
  deploy logs. Deploying from a bot MUST require a fresh TOTP code like other bot actions on
  containers. A project MUST NOT be deployed or removed under the panel's own compose project
  name. Whoever can deploy can run any container on the host; deploying is therefore limited
  to admins, and the panel says so.

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
  backend process using APScheduler. Messenger bots use outbound long polling and alerts are
  delivered by threads inside the same process; no inbound webhook endpoint is exposed.
- The MVP MUST NOT introduce message queues, separate worker services, caches, or other
  additional infrastructure. Any such addition requires a constitution amendment with
  justification.
- Exception (2.0.0): the optional Docker agent, a small HTTP service built from the backend
  image. It exists so that docker.sock is isolated in one minimal process instead of being
  given to the backend.

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
- Target databases MUST be reached over the network only. The backend and frontend MUST
  NEVER mount or use the Docker/Podman socket (`docker.sock`).
- Only the agent service may mount `docker.sock`, and only when an admin turns it on (compose
  profile, off by default, on the panel's server; `docker-compose.agent.yml` on another
  server). On the panel's server the agent MUST listen only on the internal compose network
  with no published port and answer only requests carrying the shared secret. On another
  server it MAY publish one port, and MUST serve only HTTPS with its own certificate and
  answer only requests signed with that server's token (see I). Every agent MUST implement
  only a fixed allow-list of operations (list, inspect, stats, logs, start, stop, restart;
  for registered projects: git init/remote/fetch/checkout/log and docker compose config/pull/
  build/up/ps/down; for databases on its server: connection test, database list, and dump
  with the panel's fixed dump options); run these only as fixed argument lists, never through
  a shell, inside the project's directory under the projects root, with git limited to https
  and ssh transports and dump passwords only in a private option file; never execute
  commands in containers; refuse to control or deploy over the panel's or its own
  containers; and run with a read-only filesystem, no capabilities and no-new-privileges.

Rationale: socket access grants host root; network access is sufficient for backups and far
safer, and container management keeps that power in one small, auditable component.

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
- Notifications and alerts (backup failures, stale backups, low disk space, daily summary)
  delivered to messenger bots and a signed webhook, with configurable rules and a history.
- Managing backups from Bale and Telegram bots (inline buttons) for registered admins.
- Container monitoring and control through the optional agent: list, state, usage, logs,
  start/stop/restart from the panel and the bots, container and host alerts, audit log.
- Deploying projects from git with docker compose through the agent: registration with
  encrypted credentials and variables, deploy history with logs, redeploying an earlier
  commit, a backup of chosen databases before each deploy, deploys from the bots, alerts.
- Several servers managed by one panel through their agents: adding and connecting servers,
  their containers, projects deployed on them, and backups of databases on them taken by
  their agent.
- Bilingual (Persian/English) UI.

Out of scope for MVP: restore, email notifications, non-S3 remote storage,
multi-user roles beyond admin, additional infrastructure services (beyond the agent), and,
for containers, exec/terminal and managing images, volumes and networks directly; for
deployment, automatic deploys from git webhooks and domains/TLS (planned as later phases). Introducing any of these
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

**Version**: 3.0.0 | **Ratified**: 2026-10-11 | **Last Amended**: 2026-10-12

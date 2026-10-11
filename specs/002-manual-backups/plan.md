# Implementation Plan: Manual Backups with Compression, Verification, History and Download

**Branch**: `002-manual-backups` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-manual-backups/spec.md`

## Summary

Adds on-demand logical backups to the feature 001 panel. Starting a backup creates one `queued`
run per database and returns immediately. An in-process `BackupRunner`, started in the FastAPI
lifespan with a bounded thread pool (default 2 workers), runs the right dump tool for the
detected server type as a subprocess:

- Oracle `mysqldump` 8.4 for MySQL, copied from the official image.
- `mariadb-dump` for MariaDB, from Debian.

Credentials go only through a `0600` `--defaults-extra-file`. Output is streamed through gzip,
bzip2 or nothing into a hidden temp file while a SHA-256 hash is computed. The file is then
re-read to verify the checksum, archive integrity and the `-- Dump completed` marker, and is
atomically published under a non-colliding name. Every outcome is recorded. Failures delete the
temp file, and restart recovery fails runs that were interrupted.

The UI adds:

- backup actions and live run status on the instance page (polling)
- a filterable, sortable history page with streamed downloads and deletion
- global and per-instance backup settings with a live file-name preview

All of it is in Persian and English. Details: [research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 5 / Node 22 (frontend), unchanged from
feature 001.

**Primary Dependencies**:

- No new Python packages: `subprocess`, `gzip`, `bz2`, `hashlib` and `concurrent.futures` come
  from the standard library.
- No new npm packages.
- The image gains the `mariadb-client` package (Debian) and the `mysqldump` binary (copied from
  `mysql:8.4`).

**Storage**:

- **Internal DB**: new tables `backup_settings` and `backup_runs`, plus three override columns
  on `db_instances`, via Alembic `0002`.
- **Backup files**: under `MBP_BACKUP_ROOT` (default `/backups`), a new Compose volume.

**Testing**:

- **Unit/API**: pytest, with a fake dump script for fault injection.
- **Integration**: pytest + testcontainers. Real dumps against `mysql:8.4` and `mariadb:11.8`,
  restored into the server and compared.
- **Frontend**: Vitest.

**Target Platform**: Linux containers (amd64/arm64), single backend process.

**Project Type**: Web application (existing `backend/` + `frontend/`).

**Performance Goals**: start request returns in < 1 s; UI shows status changes within 5 s
(2 s polling); history with 10,000 runs filters and sorts in < 2 s; backup throughput is limited
by the server and the compressor, not by the panel.

**Constraints**:

- Memory stays bounded per run (1 MiB chunks), with < 300 MB total for a 10 GB backup and
  download.
- Passwords never appear on a command line, in the environment, in logs or in responses.
- Paths stay inside `MBP_BACKUP_ROOT`.
- One backend process, because the queue is in memory.

**Scale/Scope**: tens of instances, up to hundreds of databases; up to ~10 GB per dump;
10,000+ history rows; 3 new screens (history, global settings, instance backup section/overrides).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | How this plan complies |
|---|-----------|--------|------------------------|
| I | Security first | ✅ Pass | <ul><li>All new routes sit behind the session and CSRF dependencies; the feature 001 route-coverage test covers them automatically.</li><li>Credentials are passed only through a `0600` option file in a `0700` temp dir, deleted in `finally`. No password in argv, in the environment (`MYSQL_PWD` is never set), in logs or in responses.</li><li>Error text is sanitized.</li><li>Downloads need the session; the path comes from the database and is re-checked against the storage root.</li><li>Storage paths are confined to the root (`..`, absolute paths and symlinks are rejected).</li></ul> |
| II | Trustworthy backups | ✅ Pass | <ul><li>Every run records status, timestamps, duration, size, compression, SHA-256 and the error code and message.</li><li>`success` only after checksum + full decompress + marker verification.</li><li>Temp-then-atomic-publish.</li><li>Failures delete partial files.</li><li>Startup recovery fails interrupted runs.</li><li>Failures show in the history and on the instance page.</li></ul> |
| III | MySQL & MariaDB | ✅ Pass | <ul><li>Server type and version are detected per run, with a tool and options chosen per type (research §1, §3; checked against MySQL 8.0 and MariaDB 11.8).</li><li>Integration tests back up and restore on MySQL 8.4 and MariaDB 11.8.</li></ul> |
| IV | Simple architecture | ✅ Pass | <ul><li>An in-process thread pool in the FastAPI lifespan; no queue, worker or broker service.</li><li>APScheduler isn't needed until scheduling exists.</li><li>Polling instead of websockets.</li></ul> |
| V | DB-agnostic storage | ✅ Pass | <ul><li>Only portable types.</li><li>A duplicate guard via a nullable unique `active_key` instead of a partial index, which MySQL lacks.</li><li>Alembic `0002`.</li><li>The CI migration matrix (SQLite, PostgreSQL, MySQL) already exists.</li></ul> |
| VI | Containerized | ✅ Pass | <ul><li>The multi-stage build copies one binary from the official `mysql:8.4` image (no extra runtime service).</li><li>A new named volume `mbp-backups`.</li><li>Still no `docker.sock`.</li><li>Non-root user `mbp` owns `/backups`.</li></ul> |
| VII | Streaming | ✅ Pass | <ul><li>The dump's stdout goes chunk-by-chunk through the compressor and hasher to disk; verification also streams.</li><li>Downloads use `FileResponse`, and nginx `proxy_buffering off` on the download route.</li><li>An RSS test is in the suite.</li></ul> |
| VIII | Bilingual UI | ✅ Pass | <ul><li>All new strings, statuses, error codes, units and durations are in `fa.json`/`en.json` (key-parity test).</li><li>Dates via `formatDateTime`.</li><li>The date-range input is Gregorian (documented in research §12).</li></ul> |
| IX | Testing | ✅ Pass | <ul><li>pytest for services and endpoints, plus fault injection.</li><li>Real-container backup and restore tests on both servers.</li></ul> |
| X | Code quality | ✅ Pass | ruff and ESLint/Prettier unchanged; English comments. |
| XI | Pluggable storage | ✅ Pass (prep) | <ul><li>No remote storage yet.</li><li>Local file access sits behind a small `LocalBackupStore` (path resolution, publish, open, delete), so the upload feature can add a remote store next to it without touching the runner.</li></ul> |

**Gate result (pre-research)**: PASS. **Gate result (post-design)**: PASS. Two design points
are noted under Complexity Tracking because they aren't obvious, not because they violate a
principle.

## Project Structure

### Documentation (this feature)

```text
specs/002-manual-backups/
├── plan.md              # This file
├── research.md          # Phase 0 (incl. experimental verification of tools/options)
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   └── openapi.yaml     # Phase 1
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks (not created here)
```

### Source Code (repository root)

New (+) and changed (~) files only:

```text
backend/
├── ~ Dockerfile                      # + mariadb-client, + COPY --from=mysql:8.4 mysqldump, /backups owned by mbp
├── + scripts/install-dump-tools.sh   # host tooling for integration tests (research §9)
├── + migrations/versions/0002_backups.py
├── src/mbp/
│   ├── ~ config.py                   # backup_root, backup_concurrency, mysqldump_path, mariadb_dump_path
│   ├── ~ main.py                     # lifespan: recovery + BackupRunner start/stop; register routers
│   ├── models/
│   │   ├── + backup_settings.py
│   │   ├── + backup_run.py
│   │   └── ~ instance.py             # override columns
│   ├── repositories/
│   │   ├── + backup_settings_repository.py
│   │   └── + backup_run_repository.py   # create (active_key), progress, finish, query/filter/sort/page
│   ├── backups/                      # + new package: the backup engine
│   │   ├── naming.py                 # pattern validation, rendering, sanitizing, root confinement
│   │   ├── store.py                  # LocalBackupStore: temp path, atomic publish, open, delete, cleanup
│   │   ├── dump_command.py           # tool + options per server type, option file writer
│   │   ├── pipeline.py               # subprocess → compressor → hasher → temp file; progress callback
│   │   ├── verify.py                 # checksum + decompress + marker
│   │   ├── errors.py                 # stderr/OSError → error_code + sanitized message
│   │   └── runner.py                 # BackupRunner: thread pool, enqueue, run lifecycle, recovery, shutdown
│   ├── services/
│   │   ├── + backup_settings_service.py # global + per-instance overrides, effective settings, preview
│   │   └── + backup_service.py          # start (all/single, skip duplicates), list, get, delete
│   └── api/
│       ├── ~ schemas.py              # settings, run, page, start request/response
│       ├── + backup_settings.py      # /backup-settings, /backup-settings/preview, /instances/{id}/backup-settings
│       └── + backups.py              # /instances/{id}/backups, /backups/runs[...], download
└── tests/
    ├── + fakes/fake_dump.py          # scriptable fake dump tool (research §10)
    ├── unit/   + test_naming.py, test_dump_command.py, test_pipeline.py, test_verify.py,
    │             test_backup_errors.py, test_runner.py
    ├── api/    + test_backup_settings_api.py, test_backups_api.py, test_downloads.py,
    │             test_backup_faults.py, test_backup_memory.py
    └── integration/ + test_backup_restore_real.py

frontend/src/
├── api/ + backups.ts                 # types, hooks, polling (refetchInterval while active)
├── i18n/locales/ ~ fa.json, en.json  # backups.*, settings.*, runStatus.*, errors.* (new codes), units.*
├── + format.ts                       # formatBytes, formatDuration (locale-aware)
├── components/
│   ├── + RunStatusBadge.tsx
│   ├── + RunTable.tsx                # shared by instance page and history
│   ├── + BackupActions.tsx           # "back up all" / single database picker + skipped notices
│   └── + BackupSettingsForm.tsx      # used globally and for instance overrides (inherit toggles, preview)
├── pages/
│   ├── + BackupHistoryPage.tsx       # filters, sort, paging, download, delete
│   ├── + BackupSettingsPage.tsx
│   └── ~ InstanceDetailPage.tsx      # backups section, recent runs, overrides
├── ~ App.tsx                         # routes /backups, /settings/backups
└── components/ ~ Layout.tsx          # nav links: Instances, Backups, Settings

frontend/ ~ nginx.conf                # download location: proxy_buffering off, long timeout
docker-compose.yml ~                  # volume mbp-backups:/backups, MBP_BACKUP_CONCURRENCY
.env.example, README.md ~             # backup storage, concurrency, single-process note, bind-mount option
.github/workflows/ci.yml ~            # install dump tools before integration tests
```

**Structure Decision**: Keep the existing web-app layout. The backup engine gets its own
`mbp.backups` package. It's a cohesive subsystem (naming, store, pipeline, verify, runner) that
later features reuse: scheduling calls `runner.enqueue`, and remote storage adds a store next to
`LocalBackupStore`. Services and API follow feature 001's layering
(api → services → repositories/engine → models).

## Complexity Tracking

No constitution violations. Two decisions to note:

| Decision | Why Needed | Simpler Alternative Rejected Because |
|----------|------------|-------------------------------------|
| Copy Oracle `mysqldump` from `mysql:8.4` instead of installing a client package | Debian 13 has no `mysql-client`, and `mariadb-client` owns `/usr/bin/mysqldump` (verified, research §1) | One MariaDB tool for both server types loses MySQL 8 compatibility and contradicts the planning input; Oracle's APT repo conflicts with `mariadb-client` |
| Backend must run as a single process | The run queue and worker pool live in memory | A multi-process-safe queue needs a broker or DB polling worker, which Principle IV excludes for the MVP |

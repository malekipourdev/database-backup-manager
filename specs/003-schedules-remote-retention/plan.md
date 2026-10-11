# Implementation Plan: Scheduled Backups, Remote Storage and Retention

**Branch**: `003-schedules-remote-retention` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

## Summary

Adds cron schedules (APScheduler `BackgroundScheduler` in the backend process), S3-compatible
uploads (boto3 behind a `RemoteStorage` protocol), and a retention service applied after each
backup and on an hourly timer. One Alembic migration (`0003`) adds `backup_schedules`,
`remote_storage_settings`, retention columns on `backup_settings` and `db_instances`, and
schedule/retention/remote columns on `backup_runs`.

## Technical Context

- **New dependencies**: `apscheduler>=3.10,<4` (named in Constitution IV), `boto3` (S3),
  `tzdata` (IANA zones in slim images); dev: `moto[server]` (local S3 API for API tests).
- **Integration tests**: RustFS (MinIO-compatible; MinIO no longer publishes images), MySQL 8.4,
  MariaDB 11.8 via testcontainers.

## Design

- **Scheduler** (`backups/scheduler.py`): one APScheduler job per enabled schedule
  (`CronTrigger.from_crontab` in the schedule's zone), `coalesce=True`, `max_instances=1`,
  `misfire_grace_time` from settings. Jobs only queue runs through `BackupService.start(...,
  trigger="schedule")`; the existing runner does the work, so concurrency limits and the
  one-active-run-per-database guard apply unchanged. API writes call `sync(id)`; deleting a
  server calls `sync_all()`. Next run times are computed from the trigger, so the API does not
  depend on the scheduler thread.
- **Remote storage** (`backups/remote.py`): `RemoteStorage` protocol (`check`, `upload`,
  `delete`, `open_stream`, `size`) and `S3RemoteStorage`. Uploads use `upload_file` with
  64 MiB multipart parts and concurrency 4, then verify the stored size. Checksums are sent
  "when required" only, for compatibility with S3-compatible services. Errors map to stable
  codes and are sanitized of the secret.
- **Upload flow** (`runner.py`): the run is marked `remote_status="uploading"` in the same
  commit that marks it successful, so it never looks done-but-not-uploaded. The upload then runs
  in the same worker. Failure sets `failed` + `remote_error`; `POST /backups/runs/{id}/upload`
  claims and re-queues it. `recover()` fails uploads left "uploading" by a crash.
- **Retention** (`services/retention_service.py`): candidates are successful runs with a local
  file or a remote copy, grouped per (server, database), newest first. `expired()` applies
  keep-last and max-age and always skips index 0. Local deletion sets `file_deleted_at` /
  `file_deleted_reason`; remote deletion sets `remote_status="deleted"`. A process-wide lock
  serializes passes. `POST /retention/apply` supports `dry_run`.
- **Security fix**: database names starting with `-` or containing control characters are
  rejected in the API, in `BackupService`, in the runner and in `build_args`.

## Constitution Check

| Principle | Status |
|-----------|--------|
| I. Security First | All new routes are behind the session + CSRF dependencies (route-coverage test). S3 secret encrypted with the Fernet key, write-only in the API, registered for log redaction. |
| II. Trustworthy Backups | Upload and retention failures are persisted on the run and shown in the UI; a crash never leaves "uploading". Retention only touches successful runs and records what it deleted. |
| III. MySQL/MariaDB | Unchanged dump path; integration tests cover both servers end to end with remote storage. |
| IV. Simple Architecture | APScheduler inside the backend; no queues or workers. |
| V. DB-agnostic | ORM + repositories only; migration verified on SQLite, PostgreSQL and MySQL in CI. |
| VI. Containers | No Dockerfile changes needed; no socket access. |
| VII. Streaming | Multipart uploads from the file; remote downloads stream in 1 MiB chunks. |
| VIII. Bilingual UI | All strings in `fa.json`/`en.json` (key-parity test). |
| IX. Real databases | `tests/integration/test_remote_real.py`: real dump → S3 → retention → download → restore. |
| X. Code quality | ruff, ESLint, Prettier clean. |
| XI. Pluggable storage | Backup and retention code depend only on the `RemoteStorage` protocol. |

No deviations.

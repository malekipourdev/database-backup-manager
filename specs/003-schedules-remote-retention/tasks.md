# Tasks: Scheduled Backups, Remote Storage and Retention

**Input**: [spec.md](./spec.md), [plan.md](./plan.md)

## Phase 1: Foundation

- [X] T001 Add `apscheduler`, `boto3`, `tzdata` and dev `moto[server]` to `backend/pyproject.toml`.
- [X] T002 Models: `BackupSchedule`, `RemoteStorageSettings`; retention columns on
  `BackupSettings` and `DbInstance`; schedule/retention/remote columns on `BackupRun`.
- [X] T003 Migration `0003_schedules_remote_retention.py` (upgrade/downgrade, `alembic check` clean).
- [X] T004 Settings `schedule_misfire_grace_seconds`, `retention_interval_minutes`; compose and
  `.env.example`.

## Phase 2: Security fix

- [X] T005 Reject option-like database names (`is_safe_database_name`) in schemas, service,
  runner and `build_args`; tests in `tests/api/test_dbname_injection.py`.

## Phase 3: US1 Scheduled backups

- [X] T006 `backups/scheduler.py` (APScheduler, `fire_schedule`, `next_fire_times`, retention sweep job).
- [X] T007 `services/schedule_service.py`, `api/schedules.py` (CRUD, preview); lifespan wiring.
- [X] T008 Tests `tests/api/test_schedules_api.py` (validation, time zones, firing, skip, cascade, real job).

## Phase 4: US2 Remote storage

- [X] T009 `backups/remote.py` (`RemoteStorage` protocol, `S3RemoteStorage`).
- [X] T010 `services/remote_storage_service.py`, `api/storage.py` remote endpoints.
- [X] T011 Runner upload after success, retry endpoint, recovery, download fallback, delete remote copy.
- [X] T012 Tests `tests/api/test_remote_storage.py` (moto S3 server) and
  `tests/integration/test_remote_real.py` (RustFS + MySQL/MariaDB).

## Phase 5: US3 Retention

- [X] T013 `services/retention_service.py` (`expired`, `RetentionService.apply`, dry run).
- [X] T014 Retention endpoints (global, per server, apply); runs after each backup and hourly.
- [X] T015 Tests `tests/api/test_retention.py`.

## Phase 6: Frontend

- [X] T016 API modules `api/schedules.ts`, `api/storage.ts`; run fields and retry upload.
- [X] T017 `ScheduleForm`, `ScheduleList`, `SchedulesPage`; schedules on the server page.
- [X] T018 `RemoteStorageForm`, `RetentionSettings`, `InstanceStoragePolicyPanel`.
- [X] T019 Run table: scheduled marker, remote status, retry upload, retention removal.
- [X] T020 Translations (fa/en) and tests (`ScheduleForm`, `StorageSettings`, `RunPolling`).

## Phase 7: Polish

- [X] T021 README: schedules, remote storage, retention, restore from remote, security notes.
- [X] T022 Untrack `frontend/tsconfig.tsbuildinfo` (build output).

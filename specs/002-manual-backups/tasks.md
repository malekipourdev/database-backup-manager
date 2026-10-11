---

description: "Task list for Manual Backups with Compression, Verification, History and Download"
---

# Tasks: Manual Backups with Compression, Verification, History and Download

**Input**: Design documents from `/specs/002-manual-backups/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/openapi.yaml](./contracts/openapi.yaml),
[quickstart.md](./quickstart.md)

**Tests**: Included. Constitution Principle IX requires pytest coverage of business logic and
endpoints, plus real-container integration tests. Principle II and SC-003 require proof that
failures are never silent. Within each story, write the tests first and confirm they fail.

**Organization**: Tasks are grouped by user story (US1–US5 from spec.md).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story the task belongs to

## Path Conventions

Existing web-app layout from feature 001: `backend/src/mbp/`, `backend/tests/`, `frontend/src/`,
`frontend/tests/`. The new backup engine lives in `backend/src/mbp/backups/`.

- All code comments are in English.
- Every user-visible string goes in **both** `frontend/src/i18n/locales/fa.json` and `en.json`.
  The feature 001 key-parity test enforces this.
- No password may appear in argv, the environment, logs or responses.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dump tools in the image and on test hosts, configuration, storage volume

- [X] T001 Update `backend/Dockerfile` runtime stage per research §1:
  - Add `FROM mysql:8.4 AS mysqldump` and `COPY --from=mysqldump /usr/bin/mysqldump /usr/local/bin/mysqldump`.
  - `apt-get install -y --no-install-recommends mariadb-client`, then remove `/var/lib/apt/lists/*`.
  - Create `/backups` owned by `mbp:mbp` and add it to `VOLUME`.
  - Keep the non-root user.
- [X] T002 [P] Create `backend/scripts/install-dump-tools.sh` (executable, `set -euo pipefail`):
  - `docker create mysql:8.4`, then `docker cp <id>:/usr/bin/mysqldump backend/.tools/mysqldump`, then `docker rm`.
  - Print the `mysqldump --version` output.
  - Print a hint to install `mariadb-client` for `/usr/bin/mariadb-dump`.
  - Add `backend/.tools/` to `.gitignore`.
- [X] T003 [P] Extend settings in `backend/src/mbp/config.py`:
  - `backup_root: str = "/backups"`
  - `backup_concurrency: int = 2` (validated `>= 1`)
  - `mysqldump_path: str = "/usr/local/bin/mysqldump"`
  - `mariadb_dump_path: str = "/usr/bin/mariadb-dump"`
  - `backup_progress_interval_seconds: float = 2.0`
- [X] T004 [P] Update `docker-compose.yml`:
  - Named volume `mbp-backups` mounted at `/backups` on `backend`.
  - Env `MBP_BACKUP_CONCURRENCY: ${MBP_BACKUP_CONCURRENCY:-2}`.
  - Add `mbp-backups` to `volumes:`.
- [X] T005 [P] Document the new variables in `.env.example`: `MBP_BACKUP_CONCURRENCY`, plus a comment that `MBP_BACKUP_ROOT` is the in-container path of the backup volume.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema, models, repositories, and the backup engine primitives every story uses

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Schema and data access

- [X] T006 [P] Create `BackupSettings` model in `backend/src/mbp/models/backup_settings.py`. Table `backup_settings`:
  - `id` Integer PK, "Always 1"
  - `storage_dir` String(255): "Relative path inside the storage root; `""` = the root itself. No absolute path, no `..` segment, no empty segments. Default `""`."
  - `name_pattern` String(255), default `{instance}/{database}_{date}_{time}`
  - `compression` String(8): "`gzip` | `bzip2` | `none`. Default `gzip`."
  - `updated_at` UTCDateTime
- [X] T007 [P] Create `BackupRun` model in `backend/src/mbp/models/backup_run.py`. Table `backup_runs`, with the fields exactly as in data-model.md:
  - `instance_id` FK → `db_instances.id` nullable `ON DELETE SET NULL`
  - `instance_name` String(100)
  - `database_name` String(64)
  - `trigger` String(8): `all`|`single`
  - `status` String(10): `queued`|`running`|`success`|`failed`, indexed
  - `active_key` String(200) nullable **unique**
  - `requested_at` indexed; `started_at`, `finished_at` nullable
  - `duration_ms`, `bytes_processed` (default 0) and `file_size` as BigInteger
  - `compression` String(8) nullable
  - `checksum_sha256` String(64) nullable
  - `file_path` String(1024) nullable, "Relative to the storage root"
  - `server_type` String(16) nullable; `server_version` String(64) nullable
  - `error_code` String(32) nullable
  - `error_message` Text nullable, "≤ 1,000 chars, never contains secrets"
  - Indexes on `instance_id` and `database_name`
- [X] T008 Add override columns to `DbInstance` in `backend/src/mbp/models/instance.py`: `backup_storage_dir` String(255) nullable, `backup_name_pattern` String(255) nullable, `backup_compression` String(8) nullable ("NULL means inherit the global value"). Export the new models from `backend/src/mbp/models/__init__.py`.
- [X] T009 Write migration `backend/migrations/versions/0002_backups.py` (`down_revision="0001"`):
  - Create `backup_settings` and insert row id=1 with the defaults.
  - Create `backup_runs` with all indexes and constraints. Use naming-convention names, so the feature 001 `test_migrations_match_models` (`alembic check`) passes.
  - Add the three nullable columns to `db_instances` via `batch_alter_table`.
  - `downgrade` reverses all of it.
- [X] T010 [P] Implement `BackupSettingsRepository` (`get()` returning row id=1, `save(...)`) in `backend/src/mbp/repositories/backup_settings_repository.py`.
- [X] T011 [P] Implement `BackupRunRepository` in `backend/src/mbp/repositories/backup_run_repository.py`:
  - `create_queued(instance, database_name, trigger) -> BackupRun | None`: sets `active_key=f"{instance.id}:{database_name}"` and `instance_name`. Inserts in a SAVEPOINT and returns `None` on `IntegrityError`.
  - `get(id)`.
  - `mark_running(run, server_type, server_version, compression, file_path)`.
  - `update_progress(run_id, bytes_processed)`: a single UPDATE in its own session.
  - `finish_success(run, size, checksum, file_path)` and `finish_failed(run, code, message)`. Both set `finished_at` and `duration_ms` and clear `active_key`.
  - `list_active()`.
  - `delete(run)`.

### Backup engine (`backend/src/mbp/backups/`)

- [X] T012 [P] Implement naming in `backend/src/mbp/backups/naming.py`:
  - `ALLOWED = {"instance","database","date","time","datetime","server_type"}`.
  - `validate_pattern(p)` returns error codes: `missing_database`, `missing_datetime`, `unknown_placeholder`, `absolute_path`, `parent_segment`, `too_long`.
  - `validate_storage_dir(d)` returns `absolute_path`, `parent_segment`, `empty_segment`.
  - `sanitize_segment(s)` replaces `/ \ : * ? " < > |`, control characters and leading dots with `_`, keeps Unicode letters, and truncates to 120 UTF-8 bytes.
  - `render(pattern, instance, database, server_type, now_utc, compression) -> PurePosixPath`. Dates are UTC: `{date}`=YYYY-MM-DD, `{time}`=HHMMSS, `{datetime}`=YYYY-MM-DD_HHMMSS. It appends `.sql`/`.sql.gz`/`.sql.bz2`.
- [X] T013 [P] Implement `LocalBackupStore` in `backend/src/mbp/backups/store.py`, rooted at `settings.backup_root`:
  - `resolve(relative) -> Path`: raises `StorageError` unless `resolved.is_relative_to(root.resolve())`.
  - `prepare(storage_dir, rendered) -> (final_rel, temp_path)`: creates directories and builds the temp path `.<name>.<run_id>.mbp-partial` in the same directory.
  - `publish(temp_path, final_rel) -> final_rel`: `os.link`, retried with `_2`, `_3`… on `FileExistsError`. Falls back to an exists-check + `os.replace` on `EPERM`/`EXDEV`, then unlinks the temp file.
  - `open_for_download(rel) -> Path`, `exists(rel)`, `delete(rel)` (a missing file is OK), `discard(temp_path)`.
  - `cleanup_partials() -> int`: recursively deletes `*.mbp-partial`.
- [X] T014 [P] Implement the dump command in `backend/src/mbp/backups/dump_command.py`, per research §3:
  - `tool_for(server_type)` returns the configured absolute path. It raises `ToolMissing` if the file doesn't exist or isn't executable.
  - `build_args(tool, cnf_path, host, port, server_type, server_version, database) -> list[str]`:
    - `--defaults-extra-file=<cnf>` comes first.
    - Then `--host`, `--port`, then `--single-transaction --quick --routines --triggers --events --hex-blob --no-tablespaces --default-character-set=utf8mb4`.
    - Add `--set-gtid-purged=OFF` for mysql, and `--column-statistics=0` only for mysql with major < 8.
    - The database name is the last positional argument.
  - `write_option_file(user, password) -> TemporaryCredentials`: a context manager. It creates a `mkdtemp` dir (0700) holding `client.cnf` (0600) with `[client]`, then `user="…"` and `password="…"`, both escaping `\` and `"`. Both are removed on exit.
- [X] T015 [P] Implement verification in `backend/src/mbp/backups/verify.py`:
  - `verify(path, compression, expected_sha256) -> VerifyResult(ok, reason)`.
  - It streams the file in 1 MiB chunks, computing SHA-256 of the raw bytes and decompressing with `gzip.open`/`bz2.open` (raw for `none`). Any exception gives `reason="corrupt"`.
  - It keeps the last 4 KiB of the decompressed data and requires `b"\n-- Dump completed"` (`reason="no_marker"`). A hash mismatch gives `reason="checksum_mismatch"`.
- [X] T016 Implement the streaming pipeline in `backend/src/mbp/backups/pipeline.py`:
  - `run_dump(args, temp_path, compression, on_progress, interval) -> PipelineResult(returncode, sha256, size, bytes_processed, stderr_tail)`.
  - Launch with `subprocess.Popen(args, stdout=PIPE, stderr=<tempfile>, env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": <cred dir>}, start_new_session=True)`.
  - Read stdout in 1 MiB chunks into a compressor (`gzip.GzipFile(fileobj=…, mode="wb")`, `bz2.BZ2File`, or raw) over a `HashingWriter` that wraps the temp file and updates SHA-256 and the size.
  - Call `on_progress(bytes_processed)` at most every `interval` seconds.
  - Close the compressor, `flush` + `os.fsync`, then `wait()`. Read the last 64 KiB of stderr.
  - Expose `terminate()` (SIGTERM to the process group) for shutdown.
- [X] T017 Implement error classification in `backend/src/mbp/backups/errors.py`:
  - `classify_dump_failure(returncode, stderr_tail, password) -> (code, message)` per the research §7 table (`missing_privileges`, `auth_rejected`, `database_not_found`, `connection_lost`, `dump_failed`).
  - `classify_os_error(exc)`: `disk_full` for `ENOSPC`/`EDQUOT`, else `storage_error`.
  - The message is the last stderr lines with the password replaced by `***`, truncated to 1,000 chars.
- [X] T018 [P] Create the fake dump tool `backend/tests/fakes/fake_dump.py` (executable, `#!/usr/bin/env python3`), per research §10:
  - It parses the `--defaults-extra-file` arg, reads the option file and asserts the password is not in `sys.argv`.
  - Its behaviour is selected by the database name prefix:
    - `ok_`: ~200 KB SQL, then `-- Dump completed on …`
    - `big_`: N MiB from env `FAKE_DUMP_MB`
    - `nomarker_`, `crash_`: half the output, then stderr `Lost connection to server during query (2013)` and exit 2
    - `denied_`: stderr `Got error: 1044: Access denied for user …` and exit 2
    - `missing_`: error 1049
    - `slow_`: sleeps `FAKE_DUMP_SLEEP` before output
- [X] T019 Add backup fixtures to `backend/tests/conftest.py`:
  - Set `MBP_BACKUP_ROOT` to a per-session temp dir and point `MBP_MYSQLDUMP_PATH`/`MBP_MARIADB_DUMP_PATH` at `tests/fakes/fake_dump.py`.
  - A `backup_root` fixture that empties the dir after each test.
  - A `probe_ok` fixture that monkeypatches `mysql_probe.test_connection` to return success with `server_type="mysql"`, `server_version="8.4.3"`.
  - A helper `wait_for_run(client, run_id, timeout=10)` that polls until the run is finished.
- [X] T020 [P] Unit tests for the engine primitives in `backend/tests/unit/test_naming.py`, `test_dump_command.py` and `test_verify.py`:
  - pattern validation codes; rendering with UTC; Persian names kept; `/` in names sanitized
  - storage-dir rejections (`/etc`, `a/../b`, `a//b`)
  - argument order (option file first, database last, no password anywhere in args), mysql vs mariadb options, the `--column-statistics=0` rule
  - option file mode `0600` and escaping, removed after the context exits
  - verify: OK for gzip/bzip2/none; corrupt gzip; truncated bzip2; missing marker; checksum mismatch
- [X] T021 [P] Unit tests for `LocalBackupStore` in `backend/tests/unit/test_store.py`: `resolve` rejects `..` and symlink escapes; `publish` never overwrites and adds `_2`; `cleanup_partials` removes only `*.mbp-partial`; `delete` of a missing file is OK.

**Checkpoint**: Engine primitives tested in isolation; migration applies and `alembic check`
passes.

---

## Phase 3: User Story 1 - Back up an instance's databases on demand (Priority: P1) 🎯 MVP

**Goal**: "Back up all marked" or one database from the instance page. One verified,
compressed file per database, recorded as a run, running in the background.

**Independent Test**: Instance with `shop` and `blog` marked → back up all → two `success` runs,
two verified files. Single backup → one run, one file (quickstart rows 1–3).

### Tests for User Story 1 ⚠️

- [X] T022 [P] [US1] API tests in `backend/tests/api/test_backups_api.py` (fake tool + `probe_ok`), per contracts:
  - `POST /api/instances/{id}/backups {"scope":"all"}` → 202 with one `queued` run per marked database. Each reaches `success`, and the files exist under `backup_root` with the default pattern path and `.sql.gz`.
  - `{"scope":"single","database":"ok_x"}` → exactly one run, also allowed for unmarked databases.
  - `information_schema` → 422 `not_selectable`.
  - `all` with nothing marked → 422 `no_databases_selected`.
  - Unknown instance → 404.
  - A successful run records `started_at`, `finished_at`, `duration_ms`, `file_size`, `compression`, `checksum_sha256` (matching `sha256` of the file), `server_type` and `trigger`.
  - The request returns in < 1 s even with a `slow_` database (SC-006).
- [X] T023 [P] [US1] Integration test in `backend/tests/integration/test_backup_restore_real.py`, marked `integration`, parametrized over `mysql:8.4`/`mariadb:11.8` with the feature 001 fixtures. Skip with a clear reason if the real tool paths are missing.
  - Seed `shop`: an InnoDB table with Persian text and a BLOB, a view, a procedure, a trigger and an event.
  - Back up through the API using the real tools and wait for `success`.
  - Decompress and pipe into `docker exec -i <container> mysql|mariadb -uroot -p… restored` (create `restored` first).
  - Assert equal `CHECKSUM TABLE` results and row counts, and that the procedure, trigger, event and view exist in `restored`.
  - Repeat for compression `bzip2` and `none` (SC-002, SC-009).

### Implementation for User Story 1

- [X] T024 [US1] Implement `BackupSettingsService.effective_for(instance) -> EffectiveSettings(storage_dir, name_pattern, compression)` in `backend/src/mbp/services/backup_settings_service.py`: each value is the instance override if not NULL, else global. Editing APIs come in US5.
- [X] T025 [US1] Implement `BackupRunner` in `backend/src/mbp/backups/runner.py`:
  - `start()` creates a `ThreadPoolExecutor(max_workers=settings.backup_concurrency, thread_name_prefix="mbp-backup")`. `enqueue(run_id)` submits `_execute(run_id)`.
  - `_execute`:
    1. Load the run and instance in a fresh session. A missing instance → `failed` `instance_deleted`.
    2. Run `mysql_probe.test_connection(conn_params(instance))`. On failure → `failed` with the probe code.
    3. Compute the effective settings and `naming.render`, then `store.prepare`.
    4. `mark_running`.
    5. Use `dump_command.write_option_file`, then `pipeline.run_dump` with `on_progress` → `update_progress`.
    6. `verify`, then `store.publish`, then `finish_success`.
  - Every exception path calls `store.discard(temp)` and `finish_failed`, so no run is ever left `running` by a handled error.
  - Register the decrypted password with `register_secret`.
- [X] T026 [US1] Wire the runner into the lifespan in `backend/src/mbp/main.py`. It is created after admin bootstrap and stored on `app.state.backup_runner`, with a dependency `get_runner(request)`. Shutdown is handled in US2.
- [X] T027 [US1] Implement `BackupService.start(instance_id, scope, database)` in `backend/src/mbp/services/backup_service.py`:
  - `all` uses the stored selection (feature 001 `SelectionRepository.list_names`). If it's empty → `ApiError(422, "no_databases_selected")`.
  - `single` rejects `NON_SELECTABLE` with `not_selectable`.
  - It creates runs via `create_queued` and collects `skipped=[{database, reason:"already_in_progress"}]` for `None` results.
  - It commits, then `runner.enqueue` for each created run, and returns `(created, skipped)`.
- [X] T028 [US1] Add schemas `BackupRun`, `StartBackupRequest` (discriminated on `scope`) and `StartBackupResponse` to `backend/src/mbp/api/schemas.py`, per contracts:
  - `file_name` is the basename of `file_path`; `file_available` is derived via `store.exists`.
  - `elapsed_ms` is set for running runs.
  - Never expose `active_key` or absolute paths.
- [X] T029 [US1] Create router `backend/src/mbp/api/backups.py` with `POST /instances/{id}/backups` (202) and `GET /backups/runs/{run_id}`. Register it as protected in `backend/src/mbp/main.py`.
- [X] T030 [P] [US1] Add `frontend/src/format.ts`:
  - `formatBytes(n, lang)`: B/KB/MB/GB with `Intl.NumberFormat` and unit translation keys.
  - `formatDuration(ms, t)`: `h`/`m`/`s` translation keys.
- [X] T031 [P] [US1] Add `frontend/src/api/backups.ts`:
  - Types mirroring `BackupRun`, `StartBackupRequest` and `StartBackupResponse`.
  - `useStartBackup(instanceId)` (invalidates `["backups", …]`).
  - `useRun(runId)`.
  - `useInstanceRuns(instanceId)`: `GET /backups/runs?instance_id=…&page_size=10`.
- [X] T032 [P] [US1] Add `backups` and `runStatus` keys to both locale files:
  - `backups`: back up all marked, back up this database, pick database, started N, nothing marked hint, recent backups, size, duration, checksum, compression, file
  - `runStatus`: queued, running, success, failed
- [X] T033 [P] [US1] Implement `RunStatusBadge` in `frontend/src/components/RunStatusBadge.tsx` (colors: gray queued, blue running with loader, green success, red failed) and `RunTable` in `frontend/src/components/RunTable.tsx`:
  - Columns: database, status, requested/started (formatDateTime), duration, size, compression.
  - Checksum is shown truncated with a copy action and `dir="ltr"`.
  - It supports an optional `instance` column and an actions slot.
- [X] T034 [US1] Implement `BackupActions` in `frontend/src/components/BackupActions.tsx`:
  - "Back up all marked databases" is disabled with a hint when the selection is empty.
  - A database `Select` (from `useDatabases`, excluding non-selectable entries) with a "Back up" button.
  - On success, a notification shows how many started.
- [X] T035 [US1] Add a "Backups" section to `frontend/src/pages/InstanceDetailPage.tsx` with `BackupActions` and a `RunTable` of `useInstanceRuns`.
- [X] T036 [P] [US1] Component test `frontend/tests/BackupActions.test.tsx`: "back up all" disabled without marked databases; the single-database start sends `{"scope":"single","database":…}`.

**Checkpoint**: Backups can be produced and verified end to end. This is the MVP.

---

## Phase 4: User Story 2 - See failures clearly; never keep broken files (Priority: P1)

**Goal**: Every failure ends `failed` with a specific, translated reason. No partial or
unverified file ever remains. Interrupted runs are recovered on restart.

**Independent Test**: Fault injection (crash, denied, missing database, no marker, disk full,
corruption, restart). Each run is `failed` with the right code and zero `*.mbp-partial` files
remain (SC-003).

**Depends on**: US1 (runner).

### Tests for User Story 2 ⚠️

- [X] T037 [P] [US2] Fault-injection tests in `backend/tests/api/test_backup_faults.py`, using the fake tool. Each case asserts the `error_code`, a non-empty `error_message` without the password, and no files under `backup_root`:
  - `crash_` → `connection_lost`
  - `denied_` → `missing_privileges`
  - `missing_` → `database_not_found`
  - `nomarker_` → `verification_failed`
  - Probe failure → the probe code (e.g. `timeout`)
  - Disk full (monkeypatch `HashingWriter.write` to raise `OSError(errno.ENOSPC)`) → `disk_full`
  - Corruption (monkeypatch a hook to flip a byte before `verify`) → `verification_failed`
  - Tool missing (path to a nonexistent file) → `tool_missing`
  - Instance deleted before start → `instance_deleted`
- [X] T038 [P] [US2] Recovery test in `backend/tests/api/test_backup_recovery.py`: insert `queued` and `running` rows with `active_key` set and create `x.mbp-partial` files, then start the app (`TestClient` context). The rows become `failed`/`interrupted` with `active_key` NULL, and the partial files are gone.
- [X] T039 [P] [US2] Unit tests for `classify_dump_failure`/`classify_os_error` in `backend/tests/unit/test_backup_errors.py`. Use real stderr samples from mysqldump 8.4 and mariadb-dump 11.8 (1044, 1045, 1049, 2013, "Couldn't execute"), and check password scrubbing and the 1,000-char truncation.
- [X] T040 [P] [US2] Security test in `backend/tests/api/test_backup_secrets.py`: during a `slow_` run, read `/proc/<pid>/cmdline` and `/proc/<pid>/environ` of the child, and assert the instance password appears in neither. After the run, assert the option-file directory no longer exists.

### Implementation for User Story 2

- [X] T041 [US2] Harden `backend/src/mbp/backups/runner.py`:
  - Map each failure through `errors.py`: dump exit, `OSError`, `ToolMissing`, `StorageError`, `VerifyResult.reason` → `verification_failed`.
  - Wrap `_execute` in a top-level `try/except Exception` that records `failed` with code `dump_failed` and a generic message, and logs it through the redaction filter.
  - Guarantee `discard(temp)` in `finally`.
  - Add a test hook `_before_verify(temp_path)` (no-op by default) used by the corruption test.
- [X] T042 [US2] Implement recovery and shutdown:
  - `BackupRunner.recover(db)` sets every `queued`/`running` run to `failed` with code `interrupted` and message "interrupted by panel restart", clears `active_key`, and calls `store.cleanup_partials()`.
  - `BackupRunner.stop()` terminates live pipelines (SIGTERM to the process group), then `shutdown(wait=True, cancel_futures=True)` with a 10 s bound. Their runs end `interrupted`.
  - Call `recover` before `start` in the lifespan, and `stop` on exit, in `backend/src/mbp/main.py`.
- [X] T043 [P] [US2] Add translation keys for the new error codes to both locale files:
  - `errors.<code>` for `missing_privileges`, `database_not_found`, `connection_lost`, `dump_failed`, `disk_full`, `verification_failed`, `interrupted`, `instance_deleted`, `tool_missing`, `storage_error`
  - `backups.explain.<code>`: one sentence each with a suggested fix
- [X] T044 [US2] Show failures in `frontend/src/components/RunTable.tsx`: failed rows show the translated `errors.<code>` with an expandable `backups.explain.<code>`, plus `error_message` in an LTR code block.

**Checkpoint**: Failures are always visible and never leave files behind.

---

## Phase 5: User Story 3 - Watch progress without blocking, run in parallel safely (Priority: P2)

**Goal**: Live status and progress via polling, parallel runs up to the limit with FIFO
queueing, and duplicate runs refused.

**Independent Test**: Start long runs on two instances, both progress live, and a duplicate
start for the same database is skipped (quickstart rows 4–5).

**Depends on**: US1.

### Tests for User Story 3 ⚠️

- [X] T045 [P] [US3] Concurrency tests in `backend/tests/api/test_backup_concurrency.py` (`MBP_BACKUP_CONCURRENCY=2`, `slow_` databases):
  - Start 3 runs: at most 2 are `running` at once, and the third is `queued` until one finishes, then starts (FIFO).
  - Fire 10 parallel start requests for the same database from threads: exactly one run is created and the rest report `skipped: already_in_progress` (SC-007).
  - `all` with one database already running → the others are created and that one is skipped.
  - `bytes_processed` increases while running, and `elapsed_ms` is set.
- [X] T046 [P] [US3] Memory test in `backend/tests/api/test_backup_memory.py`: `big_` with `FAKE_DUMP_MB=1024`. Assert the process's max RSS growth (`resource.getrusage(RUSAGE_SELF).ru_maxrss` before/after) stays below 300 MB, and the run ends `success` (SC-004 for the write path).

### Implementation for User Story 3

- [X] T047 [US3] Make progress writes efficient in `backend/src/mbp/backups/runner.py`. `on_progress` calls `BackupRunRepository.update_progress` in its own short session, at most every `settings.backup_progress_interval_seconds`, and never holds a transaction open during the dump.
- [X] T048 [US3] Add the history listing endpoint `GET /backups/runs` with the `instance_id` and `status` (multi) filters to `backend/src/mbp/api/backups.py`, so the UI can poll active runs. Full filtering, sorting and paging come in US4 and extend the same endpoint.
- [X] T049 [US3] Add polling to `frontend/src/api/backups.ts`. `useInstanceRuns` and `useRun` set `refetchInterval: (query) => hasActive(query.state.data) ? 2000 : false`, where `hasActive` checks for `queued`/`running`.
- [X] T050 [P] [US3] Show live progress in `frontend/src/components/RunTable.tsx`: running rows show `formatBytes(bytes_processed)` and `formatDuration(elapsed_ms)`, and queued rows show their queue position.
- [X] T051 [US3] Show the `skipped` list from `StartBackupResponse` as a warning notification in `frontend/src/components/BackupActions.tsx` ("`shop`: already in progress"), and disable the single-database button while that database has an active run.
- [X] T052 [P] [US3] Component test `frontend/tests/RunPolling.test.tsx` (fake timers): polling runs while a run is `running` and stops after `success`; the skipped notification is rendered.

**Checkpoint**: Responsive UI, safe parallelism, no duplicates.

---

## Phase 6: User Story 4 - Browse history, download and delete backups (Priority: P2)

**Goal**: History page with filters, sorting and paging, streamed downloads, and deletion of file
and record.

**Independent Test**: Several runs across two instances. Filter and sort; the downloaded file's
SHA-256 equals the recorded one; delete removes the row and the file (quickstart rows 9–13).

**Depends on**: US1 (runs exist). US3's listing endpoint is extended here.

### Tests for User Story 4 ⚠️

- [X] T053 [P] [US4] API tests in `backend/tests/api/test_backup_history_api.py` (insert runs directly):
  - Filters `instance_id`, `database`, multi-`status`, `from`/`to`, combined.
  - Each `sort` value with `asc`/`desc`; default `requested_at desc`.
  - Paging with `total` correct; `page_size` max 200 → 422 above.
  - Unknown `sort` → 422.
  - Runs of a deleted instance keep `instance_name` and return `instance_id: null`.
  - 10,000 rows filtered and sorted in < 2 s (SC-008).
- [X] T054 [P] [US4] Download and delete tests in `backend/tests/api/test_downloads.py`:
  - Download a `success` run: 200, `Content-Disposition` with a UTF-8 `filename*` (Persian instance name), the right media type, and a SHA-256 of the body equal to `checksum_sha256`.
  - The `Range` header gives 206.
  - A failed run → 409 `file_unavailable`; a file removed on disk → 409 and `file_available: false` in the listing.
  - No session → 401.
  - A tampered `file_path` (`../../etc/passwd` set in the database) → 409, never serving outside the root.
  - Deletion:
    - DELETE `success` → 204, file and row gone.
    - DELETE `failed` → 204.
    - DELETE `running` → 409 `run_active`.
    - Unknown → 404 `run_not_found`.
- [X] T055 [P] [US4] Download memory test in `backend/tests/api/test_backup_memory.py`: stream a 1 GiB file through `TestClient` (iterating chunks) and keep RSS growth < 300 MB (SC-004 for the read path).

### Implementation for User Story 4

- [X] T056 [US4] Implement `BackupRunRepository.query(filters, sort, order, page, page_size) -> (items, total)` in `backend/src/mbp/repositories/backup_run_repository.py`:
  - Whitelist the sort columns `requested_at`, `duration_ms`, `file_size`, `instance_name`, `database_name`, `status`, with `id` as a tie-breaker.
  - `from` is inclusive and `to` exclusive on `requested_at`.
- [X] T057 [US4] Complete `GET /backups/runs` in `backend/src/mbp/api/backups.py` with all query parameters from the contracts. Validation: `page ≥ 1`, `1 ≤ page_size ≤ 200`, and enums for `sort`, `order` and `status`.
- [X] T058 [US4] Implement the download in `backend/src/mbp/api/backups.py`: `GET /backups/runs/{run_id}/download`.
  - Load the run (404 if missing). Require `success` and `store.exists`, else 409 `file_unavailable`.
  - Resolve the path with `store.open_for_download` (409 if it escapes the root).
  - Return `FileResponse(path, media_type=…, filename=<basename>, content_disposition_type="attachment")`.
- [X] T059 [US4] Implement `BackupService.delete(run_id)` and `DELETE /backups/runs/{run_id}`. A queued/running run → 409 `run_active`. Otherwise call `store.delete(file_path)` (a missing file is OK), then delete the row and commit.
- [X] T060 [US4] Update `frontend/nginx.conf`: add `location ~ ^/api/backups/runs/[0-9]+/download$` with `proxy_pass http://backend:8000`, `proxy_buffering off`, `proxy_request_buffering off`, `proxy_read_timeout 1h` and the same forwarded headers. Declare it before `location /api/`.
- [X] T061 [P] [US4] Extend `frontend/src/api/backups.ts`:
  - `useRunHistory(filters, sort, page)`, with polling while any listed run is active.
  - `useDeleteRun()`.
  - `downloadUrl(runId)` returning `/api/backups/runs/${id}/download`.
- [X] T062 [P] [US4] Add `history` translation keys to both locale files: title, filters (instance, database, status, from, to, clear), sort labels, empty state, download, delete, delete confirm (mentioning file + record, plus a "latest successful backup of this database" variant), file missing, page info.
- [X] T063 [US4] Implement `BackupHistoryPage` in `frontend/src/pages/BackupHistoryPage.tsx`:
  - Filter bar: an instance `Select` populated from `useInstances` plus "deleted instance" values from the results; a database `TextInput`; a status `MultiSelect`; two `<input type="date">` mapped to UTC `from`/`to`; Clear.
  - The filters sync to URL search params.
  - `RunTable` with an instance column and sortable headers.
  - Mantine `Pagination` (50 per page).
  - The download action is a plain `<a href={downloadUrl} download>`, disabled with "file missing" when `!file_available`.
  - Delete uses `ConfirmDialog`, using the "latest successful" text when applicable, and is hidden for active runs.
- [X] T064 [US4] Add the `/backups` route in `frontend/src/App.tsx` and nav links (Instances, Backups) in `frontend/src/components/Layout.tsx`. Add `nav.backups` to both locale files.
- [X] T065 [P] [US4] Component test `frontend/tests/BackupHistoryPage.test.tsx`:
  - Filters produce the expected query string.
  - The download link points to the download URL and is disabled when `file_available` is false.
  - Delete asks for confirmation and calls DELETE.

**Checkpoint**: Backups can be found, retrieved and cleaned up.

---

## Phase 7: User Story 5 - Configure where and how backups are stored (Priority: P3)

**Goal**: Edit global defaults and per-instance overrides, with a live preview and validation.

**Independent Test**: Change the global compression to bzip2 and the pattern; an inheriting
instance uses them, while an instance overriding `none` keeps `none` (quickstart rows 14–16).

**Depends on**: Foundational (US1 already reads effective settings).

### Tests for User Story 5 ⚠️

- [X] T066 [P] [US5] API tests in `backend/tests/api/test_backup_settings_api.py`:
  - `GET /api/backup-settings` returns the defaults (US5-1).
  - PUT validation errors in `fields`: pattern without `{database}` → `missing_database`, without date/time → `missing_datetime`, `{foo}` → `unknown_placeholder`, storage dir `/etc` → `absolute_path`, `../x` → `parent_segment`, compression `zip` → enum error.
  - Preview returns e.g. `prod/shop_2026-10-11_130820.sql.bz2`.
  - `GET/PUT /api/instances/{id}/backup-settings` with null = inherit; `effective` reflects the overrides.
  - An end-to-end run uses the override (`none` → `.sql`).
  - Changing settings leaves existing runs' `file_path`/`compression` unchanged (FR-014).

### Implementation for User Story 5

- [X] T067 [US5] Extend `backend/src/mbp/services/backup_settings_service.py`:
  - `get_global()`, `update_global(data)` and `preview(storage_dir, pattern, compression, instance_name, database_name)`, all validated with `naming.validate_*` and raising `ApiError(422, "validation_error", fields=…)`.
  - `get_instance(id) -> {overrides, effective}` and `update_instance(id, overrides)`.
- [X] T068 [US5] Add the schemas `BackupSettings`, `InstanceBackupOverrides`, `InstanceBackupSettings`, `PatternPreviewRequest` and `PatternPreview` to `backend/src/mbp/api/schemas.py`. Create router `backend/src/mbp/api/backup_settings.py` with `GET/PUT /backup-settings`, `POST /backup-settings/preview` and `GET/PUT /instances/{id}/backup-settings`, registered as protected in `main.py`.
- [X] T069 [P] [US5] Add `useBackupSettings`, `useSaveBackupSettings`, `useInstanceBackupSettings`, `useSaveInstanceBackupSettings` and `previewPattern` to `frontend/src/api/backups.ts`.
- [X] T070 [P] [US5] Add `settings` translation keys to both locale files:
  - title, storage dir (with "relative to the backup volume" help), pattern (with the placeholder list help), compression options gzip/bzip2/none
  - preview, inherit global, override, saved
  - one validation message per code
- [X] T071 [US5] Implement `BackupSettingsForm` in `frontend/src/components/BackupSettingsForm.tsx`:
  - The fields are storage dir (LTR), pattern (LTR) with clickable placeholder chips, and compression `SegmentedControl`.
  - In `mode="instance"`, each field has an "inherit global" checkbox that sends `null`.
  - A debounced (300 ms) server-side preview.
  - Server `fields` errors are mapped to translated messages.
- [X] T072 [US5] Implement `BackupSettingsPage` in `frontend/src/pages/BackupSettingsPage.tsx` (global). Add the `/settings/backups` route in `frontend/src/App.tsx` and a "Settings" nav link in `frontend/src/components/Layout.tsx` (`nav.settings` in both locales).
- [X] T073 [US5] Add a "Backup settings" panel to `frontend/src/pages/InstanceDetailPage.tsx`: it shows the effective values and opens `BackupSettingsForm` in instance mode.
- [X] T074 [P] [US5] Component test `frontend/tests/BackupSettingsForm.test.tsx`: an "inherit" toggle sends `null`; the preview text updates; a `missing_database` server error is shown translated.

**Checkpoint**: All five stories work independently and together.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T075 [P] Update `.github/workflows/ci.yml`: in the backend job, before the integration tests, run `sudo apt-get install -y mariadb-client` and `backend/scripts/install-dump-tools.sh`, and export `MBP_MYSQLDUMP_PATH`/`MBP_MARIADB_DUMP_PATH`. The migrations matrix already covers `0002`.
- [X] T076 [P] Update `README.md`:
  - "Backups" section: where files are stored (the `mbp-backups` volume, `docker compose exec backend ls /backups`) and how to use a host bind mount instead (`./backups:/backups`, `chown 10001:10001`).
  - `MBP_BACKUP_CONCURRENCY`, and that the backend must run as a single process.
  - The dump tools used per server type.
  - Restore instructions (`gunzip -c … | mysql …`).
  - Trim the grant list (`PROCESS` is no longer needed, research §3).
- [X] T077 Verify the image: `docker compose build backend` then `docker compose run --rm backend sh -c '/usr/local/bin/mysqldump --version && /usr/bin/mariadb-dump --version && id -u && test -w /backups'`. Record the image size change in the PR description.
- [X] T078 Review all new frontend code for hard-coded strings and physical CSS properties. Run `npm run lint` (i18n rule) and the key-parity test, and fix findings.
- [X] T079 Run `uv run ruff check . && uv run ruff format --check . && uv run pytest && uv run pytest -m integration` and the frontend checks, and fix failures.
- [ ] T080 Run the [quickstart.md](./quickstart.md) validation (all 19 manual scenarios, including the browser ones and `ps -ef` during a backup) and fix any failures.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: depends on Setup (T003 config). Blocks all stories.
- **US1 (Phase 3)**: Foundational.
- **US2 (Phase 4)**: US1 (hardens the runner).
- **US3 (Phase 5)**: US1.
- **US4 (Phase 6)**: US1. It extends the listing endpoint from US3 (T048), so do T048 first or
  create the endpoint in T057 directly.
- **US5 (Phase 7)**: Foundational only. Its frontend touches `InstanceDetailPage.tsx`, which US1
  also edits.
- **Polish (Phase 8)**: all stories.

### Story Completion Order

```text
Setup → Foundational ─┬─> US1 ─┬─> US2
                      │        ├─> US3 ─> US4
                      │        └─────────> US4
                      └─> US5 (backend anytime; UI after US1 touches InstanceDetailPage)
                                                        ─> Polish
```

### Within Each Story

- Tests first (they must fail), then repositories/engine → services → API → frontend API hooks
  → components/pages.
- Translation keys go in the same story as the UI that uses them, in both locale files.

### Parallel Opportunities

- Setup: T002–T005 together.
- Foundational:
  - T006/T007 together, then T008 → T009.
  - T010/T011 together.
  - T012–T015 and T018 together (separate files).
  - T020/T021 after their modules.
- After US1: US2, US3 and US5 can proceed in parallel. US2 and US3 both edit `runner.py`, so
  coordinate T041/T042 with T047.
- Within each story: all [P] tests, locale-key tasks and frontend API hooks.

---

## Parallel Example: Foundational engine

```bash
Task: "Implement naming in backend/src/mbp/backups/naming.py"
Task: "Implement LocalBackupStore in backend/src/mbp/backups/store.py"
Task: "Implement dump command builder in backend/src/mbp/backups/dump_command.py"
Task: "Implement verification in backend/src/mbp/backups/verify.py"
Task: "Create fake dump tool backend/tests/fakes/fake_dump.py"
```

## Parallel Example: User Story 2

```bash
Task: "Fault-injection tests in backend/tests/api/test_backup_faults.py"
Task: "Recovery test in backend/tests/api/test_backup_recovery.py"
Task: "Unit tests for error classification in backend/tests/unit/test_backup_errors.py"
Task: "Process args/env security test in backend/tests/api/test_backup_secrets.py"
Task: "Translation keys for new error codes in both locale files"
```

---

## Implementation Strategy

### MVP First

1. Setup → Foundational.
2. US1, then **validate**: verified backups are produced and restore cleanly on MySQL and
   MariaDB.
3. US2, then **validate**: fault injection is clean. US1 + US2 (both P1) is the smallest
   trustworthy release. Shipping US1 without US2 would violate Principle II.

### Incremental Delivery

1. + US1 + US2 → trustworthy on-demand backups (release)
2. + US3 → live progress, parallel runs, duplicate guard
3. + US4 → history, download, delete
4. + US5 → configurable storage, naming and compression
5. Polish → CI tools, README, image check, full quickstart

---

## Notes

- [P] = different files, no dependencies on incomplete tasks.
- Never log, return or pass on the command line any database password (Principle I).
- A run must never stay `running` after its worker exits. Every code path ends in
  `finish_success` or `finish_failed`.
- Commit after each task or logical group, and stop at any checkpoint to validate the story.

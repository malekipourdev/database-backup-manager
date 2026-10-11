# Research: Manual Backups

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-10-11

The stack is fixed by the constitution and feature 001. Decisions §1 and §3 were checked
experimentally on 2026-10-11 against the real base image and real servers; results are noted
inline.

## 1. Dump tools in the backend image

- **Decision**: Use two tools, each called by **absolute path**, both configurable through
  settings:
  - **MySQL servers** → Oracle `mysqldump` 8.4 at `/usr/local/bin/mysqldump`, copied in a
    multi-stage build from the official `mysql:8.4` image (`COPY --from=mysql:8.4
    /usr/bin/mysqldump`).
  - **MariaDB servers** → `mariadb-dump` at `/usr/bin/mariadb-dump`, from Debian's
    `mariadb-client` package.
- **Why not "install both client packages"** (the planning input): verified on
  `python:3.12-slim`, which is Debian 13 (trixie):
  - Debian has **no** `mysql-client` package (`Candidate: (none)`). `default-mysql-client` and
    `mariadb-client` both install MariaDB 11.8 tools.
  - `mariadb-client` installs `/usr/bin/mysqldump` as a **symlink to `mariadb-dump`**. Oracle's
    `mysql-community-client` (from Oracle's APT repository) ships the same file, so the two
    packages conflict.
- **Verification of the chosen approach**:
  - `ldd` of Oracle `mysqldump` 8.4 lists only `libssl3`, `libcrypto3`, `libz`, `libstdc++`,
    `libgcc_s`, `libc`, `libm` and `libresolv`. All of these are present on the Debian image
    ("all-libs-found").
  - `mysqldump --version` prints `Ver 8.4.11 … MySQL Community Server`.
  - Because `mysqldump` on PATH is ambiguous (the Debian symlink also exists), the code never
    relies on PATH.
- **Version compatibility**: `mysqldump` 8.4 dumped a MySQL **8.0** server successfully (§3).
  MySQL 8.0 and 8.4 servers are covered by one client.
- **`--column-statistics=0`**: only needed when Oracle `mysqldump` ≥ 8.0 talks to a server
  without `information_schema.COLUMN_STATISTICS`, i.e. MariaDB or MySQL < 8.0. With the
  server-type routing above that never happens for supported servers, so the flag is **not**
  passed. The option builder adds it only if a MySQL server reports a major version < 8, which
  keeps 5.7 working if it is ever used.
- **Alternatives considered**:
  - `mariadb-dump` for both server types: it doesn't fully understand MySQL 8-only features
    (e.g. invisible columns, functional index syntax), and the input explicitly asks for
    `mysqldump` with MySQL.
  - Oracle's APT repository with a renamed `mariadb-client`: fragile package pinning, and
    Oracle's Debian 13 support lags.
  - A separate tools container: violates the constitution's "no extra services".

## 2. Execution model: in-process runner with a bounded thread pool

- **Decision**: A `BackupRunner` is created in the FastAPI lifespan. It owns a
  `ThreadPoolExecutor(max_workers=MBP_BACKUP_CONCURRENCY)`, default 2.
  - Starting a backup inserts `queued` run rows and submits each run id to the executor, then
    returns `202` immediately (SC-006).
  - The executor's FIFO queue gives "queued in request order" (FR-005).
  - Each worker drives one dump subprocess through a blocking pipeline (§4). Threads were chosen
    over asyncio subprocesses because the data layer is synchronous SQLAlchemy (feature 001,
    research §1). The `gzip`/`bz2`/`hashlib` C code releases the GIL on large buffers, so
    parallel runs make real progress.
- **Single process requirement**: the queue lives in memory, so the backend must run as **one**
  uvicorn process. That is the current default (`CMD … uvicorn` with no `--workers`); the plan
  records it as a deployment constraint.
- **Startup recovery** (FR-019): before accepting requests, the lifespan marks every run in
  `queued`/`running` as `failed` with code `interrupted` and clears its active key. It then
  deletes all `*.mbp-partial` files under the storage area.
- **Shutdown**: the lifespan's exit calls `executor.shutdown(wait=False, cancel_futures=True)`
  and sends SIGTERM to running dump processes. Their runs are then finalized as `interrupted`.
  Anything missed (e.g. SIGKILL) is caught by startup recovery.
- **Alternatives considered**: APScheduler job store (fits the later scheduling feature, but adds
  nothing for immediate runs); a separate worker process or Celery (forbidden by Principle IV).

## 3. Dump options and least privileges

- **Decision**: The options are:

  ```text
  common:   --single-transaction --quick --routines --triggers --events --hex-blob
            --no-tablespaces --default-character-set=utf8mb4
  mysql:    + --set-gtid-purged=OFF   (+ --column-statistics=0 only if server major < 8)
  database: passed as the single positional argument (no --databases)
  ```

  - `--no-tablespaces` removes the need for the `PROCESS` privilege on MySQL ≥ 8.0.21.
  - `--set-gtid-purged=OFF` keeps `SET @@GLOBAL.GTID_PURGED` out of the file, so it can be
    restored into any server. It also avoids the extra `RELOAD` that `--single-transaction`
    needs when GTIDs are on.
  - Without `--databases`, the dump has no `CREATE DATABASE`/`USE` statements, so it can be
    restored into a database of any name (§9).
- **Verified 2026-10-11** with a seeded database (InnoDB table with Persian text, a procedure,
  a trigger and an event) and a user granted only `SELECT, SHOW VIEW, TRIGGER, EVENT,
  LOCK TABLES, PROCESS`:

  | Tool → server | Exit | Ends with `-- Dump completed on …` | Routine + trigger + event in file |
  |---------------|------|------------------------------------|-----------------------------------|
  | `mysqldump` 8.4 → MySQL 8.0 | 0 | yes | 3/3 |
  | `mariadb-dump` 11.8 → MariaDB 11.8 | 0 | yes | 3/3 |
  | `mysqldump` 8.4 → MySQL 8.0 after `REVOKE PROCESS` | 0 | — | — |

  So `PROCESS` is not required with these options. The README grant list stays a superset and
  can be trimmed later.

## 4. Streaming pipeline (Principle VII)

- **Decision**: Each run follows this sequence:
  1. **Pre-flight**: `mysql_probe.test_connection` (feature 001). This classifies connection
     failures with the existing codes and returns `server_type`/`server_version` for tool
     selection (FR-006).
  2. **Credentials file**: written to a private temp dir (`mkdtemp`, 0700) with mode `0600`. It
     contains only `[client]`, `user` and `password`, with values double-quoted and `\`/`"`
     escaped. Host and port are passed as arguments, since they aren't secret. The file and its
     directory are deleted in `finally`.
  3. **Launch**: `Popen([tool, "--defaults-extra-file=<cnf>", "--host", host, "--port", port,
     *options, database], stdout=PIPE, stderr=<temp file>, env=<minimal env>)`.
     - `--defaults-extra-file` must be the first argument.
     - The environment has `PATH`, `LANG=C.UTF-8` and `HOME=<tempdir>` only, with no `MYSQL_PWD`.
     - stderr goes to a file so a full pipe can't deadlock the dump. Its last 64 KiB are read on
       failure.
  4. **Write**: the worker reads stdout in 1 MiB chunks and writes them through the compressor
     (`gzip.GzipFile`, `bz2.BZ2File`, or nothing) into a hashing writer wrapped around the temp
     file. It counts uncompressed `bytes_processed` along the way. Memory stays bounded at a few
     MiB per run.
  5. **Progress**: written to the database at most every 2 seconds, in its own short session.
  6. **Finish**: wait for the process, close the compressor, then `flush` + `os.fsync`.
- **Alternatives considered**:
  - Piping through external `gzip`/`bzip2` processes: an extra process to supervise and an extra
    failure mode, with no meaningful speed gain at this scale.
  - `asyncio.create_subprocess_exec`: doesn't fit the synchronous data layer (§2).

## 5. Temp files, final names and atomic publish (FR-013, FR-017)

- **Decision**:
  - **Temp file**: `<final-dir>/.<final-name>.<run_id>.mbp-partial`. It lives in the same
    directory as the final file, so the publish step is a same-filesystem link or rename.
  - **Publish**: after successful verification, publish with `os.link(temp, final)`, which fails
    atomically with `FileExistsError` if the name exists. On conflict, try `name_2`, `name_3`,
    and so on. Then unlink the temp file. If the filesystem doesn't support hard links (`EPERM`
    or `EXDEV`), fall back to a check followed by `os.replace` (best-effort no-overwrite).
  - **Listing**: temp files never appear in listings, because listings come from database rows
    with status `success` and never from scanning the directory.
- **Name rendering**:
  - Pattern placeholders are filled; dates and times are in UTC (FR-010).
  - Each path segment is sanitized: `/ \ : * ? " < > |`, control characters and leading dots are
    replaced with `_`, while Unicode letters are kept. Each segment is truncated to 120 bytes.
  - The compression extension is appended.
  - The final directory is `resolve()`d and must satisfy `is_relative_to(backup_root)`, which
    also catches symlinks (FR-012).

## 6. Verification (FR-021)

- **Decision**: after the write completes, re-open the temp file and stream it once:
  - Compute a SHA-256 over the raw bytes and compare it with the hash recorded during writing.
    A mismatch means the data changed on disk.
  - Decompress fully with `gzip.open`/`bz2.open`, or read the raw bytes for `none`. Any
    `OSError`/`EOFError`/`BadGzipFile` fails verification. This is the in-Python equivalent of
    `gzip -t` / `bzip2 -t`.
  - Keep the last 4 KiB of the decompressed stream, and require it to contain
    `\n-- Dump completed` (the marker verified in §3).
- **Alternatives considered**: calling `gzip -t`/`bzip2 -t` binaries (extra processes for no
  benefit); checking only the marker during writing (doesn't prove the bytes on disk are
  readable).

## 7. Error classification (FR-020)

| Condition | `error_code` |
|-----------|--------------|
| Pre-flight probe failure | probe code (`host_not_found`, `connection_refused`, `timeout`, `auth_rejected`, `server_error`) |
| stderr contains error `1044`, `1142`, `1227` or "Access denied … to database" | `missing_privileges` |
| stderr `1045` | `auth_rejected` |
| stderr `1049` / "Unknown database" | `database_not_found` |
| stderr `2002`/`2003`/`2006`/`2013` or "Lost connection" | `connection_lost` |
| any other non-zero exit | `dump_failed` |
| `OSError` with `errno.ENOSPC` (or `EDQUOT`) | `disk_full` |
| any verification check fails | `verification_failed` |
| interrupted by shutdown or found active on startup | `interrupted` |
| instance deleted before the run started | `instance_deleted` |
| dump tool binary missing or not executable | `tool_missing` |
| invalid or unwritable storage path | `storage_error` |

- `error_message` holds the sanitized detail: the last stderr lines, password removed,
  truncated to 1,000 characters.
- The UI translates `error_code` and shows `error_message` as secondary text, the same pattern
  as connection testing.

## 8. Duplicate-run guard (FR-004, SC-007)

- **Decision**: `backup_runs.active_key` is a nullable `String(200)` with a **unique**
  constraint.
  - It is set to `"<instance_id>:<database_name>"` while the run is `queued`/`running`, and set
    to `NULL` when the run finishes.
  - Creating a run that collides raises an `IntegrityError` → the database is reported as
    "skipped: already in progress".
  - This works the same on SQLite, PostgreSQL and MySQL, where multiple NULLs are allowed in a
    unique index (Principle V).
- **Alternatives considered**: a partial unique index (MySQL doesn't support it); an in-memory
  lock (lost on restart and racy between the check and the insert).

## 9. Restore check in integration tests

- **Decision**: For each server (`mysql:8.4`, `mariadb:11.8`), the integration tests:
  1. Seed a database (tables with UTF-8 and binary data, a view, a routine, a trigger and an
     event).
  2. Run a real backup through the API and wait for `success`.
  3. Decompress the file and pipe it into a fresh database via
     `docker exec -i <container> mysql|mariadb -uroot -p… restored`, so the server's own client
     handles `DELIMITER`.
  4. Compare row counts and checksums (`CHECKSUM TABLE`) and confirm the routine, trigger and
     event exist.
- **Tooling for tests**: integration tests need the two dump binaries on the test host.
  - `backend/scripts/install-dump-tools.sh` copies `mysqldump` out of `mysql:8.4` (`docker
    create` + `docker cp`) into `backend/.tools/`. `mariadb-dump` comes from the OS package
    manager.
  - Paths are passed via `MBP_MYSQLDUMP_PATH`/`MBP_MARIADB_DUMP_PATH`.
  - Tests skip with a clear message when a tool is missing.
  - CI runs the script.

## 10. Fault injection without real servers (SC-003)

- **Decision**: unit and API tests point the dump tool paths at a small fake-dump script in
  `tests/fakes/`. Its behaviour is chosen by the database name:
  - `ok_*`: emits SQL plus the marker
  - `nomarker_*`: exits 0 without the marker
  - `crash_*`: writes half the output, then exits 2 with "Lost connection" on stderr
  - `denied_*`: exits 2 with error 1044
  - `slow_*`: sleeps, for testing the queue and duplicates
- **Other faults**:
  - **Disk full**: monkeypatch the hashing writer to raise `OSError(ENOSPC)` after N bytes.
  - **Corruption**: a test hook flips a byte between writing and verification.
  - **Interrupted panel**: create `running` rows and a `.mbp-partial` file, then start the app.

## 11. Downloads (FR-024)

- **Decision**:
  - **Endpoint**: Starlette `FileResponse` (chunked, constant memory, supports `Range`) behind
    the session dependency. The path is taken only from the database row and re-checked against
    the storage root. The response uses `Content-Disposition: attachment` with an RFC 5987
    UTF-8 `filename*`, and the media type matches the compression (`application/gzip`,
    `application/x-bzip2`, `application/sql`).
  - **Browser side**: a plain same-origin link, so the browser streams to disk and the
    `SameSite=Strict` session cookie is sent.
  - **nginx**: a dedicated `location ~ ^/api/backups/runs/\d+/download$` with
    `proxy_buffering off` and a long `proxy_read_timeout`. Otherwise nginx would spool large
    files to its own temp directory, with a 1 GiB cap by default.
- **Alternatives considered**: `fetch` + Blob in the SPA (holds the whole file in browser
  memory); signed URLs (unneeded, since the cookie session already authorizes the request).

## 12. Frontend polling and date filters

- **Decision**:
  - **Polling**: TanStack Query `refetchInterval: 2000` on the run lists and run detail, only
    while the displayed data contains a `queued`/`running` run; otherwise polling stops.
    No websockets.
- **Date range filter**: native `<input type="date">` pair. Browsers render it in the Gregorian
  calendar even in Persian, but results and all displayed dates still use `formatDateTime`
  (Persian calendar for `fa`).
  - Mantine's date pickers have no Jalali calendar either. Adding a Jalali picker library is
    deferred.
- **Formatting**: sizes use `Intl.NumberFormat` with B/KB/MB/GB units; durations use `h m s`
  keys from the translation files.

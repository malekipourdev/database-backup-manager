# Feature Specification: Scheduled Backups, Remote Storage and Retention

**Feature Branch**: `003-schedules-remote-retention`
**Created**: 2026-10-11
**Status**: Implemented
**Input**: "Add the remaining MVP features: scheduled (cron) backups, uploading backups to
remote S3-compatible storage, and a retention policy that automatically deletes old backups."

## User Scenarios & Testing

### User Story 1 - Scheduled backups (Priority: P1)

An admin defines cron schedules per server, for example "every night at 02:00 Tehran time,
back up all marked databases", so backups happen without anyone pressing a button.

**Acceptance Scenarios**:

1. **Given** a server with marked databases, **When** the admin saves a schedule with
   `0 2 * * *` and `Asia/Tehran`, **Then** the next run times are shown and backups of every
   marked database are queued at 02:00 Tehran time, marked "Scheduled" in the history.
2. **Given** a schedule fires while a backup of the same database is still running, **Then**
   that database is skipped and the schedule shows "Skipped (already running)".
3. **Given** a schedule whose server has no marked databases, **When** it fires, **Then** no
   run is created and the schedule shows "No databases marked".
4. **Given** an invalid cron expression or time zone, **When** saving, **Then** the field is
   rejected with a translated message.
5. **Given** a server is deleted, **Then** its schedules are deleted and never fire again.

### User Story 2 - Upload to S3-compatible storage (Priority: P1)

An admin configures a bucket (AWS S3, MinIO, RustFS, Ceph, ArvanCloud...) so each verified
backup is also stored off the server.

**Acceptance Scenarios**:

1. **Given** valid settings, **When** the admin clicks "Test connection", **Then** the panel
   proves it can write and delete in the bucket; failures name the reason (bucket missing,
   access denied, endpoint unreachable).
2. **Given** upload is on, **When** a backup succeeds, **Then** the file is streamed to
   `<prefix>/<relative path>` with its SHA-256 as metadata, and the run shows "Stored remotely".
3. **Given** the upload fails, **Then** the backup stays successful, the run shows "Upload
   failed" with the sanitized reason, and "Retry upload" uploads it again.
4. **Given** a server set to "Never" (or "Always"), **Then** it overrides the global switch.
5. **Given** the local file is gone, **When** downloading, **Then** the remote copy is streamed.
6. The secret key is encrypted at rest and never returned or logged.

### User Story 3 - Retention (Priority: P1)

An admin sets "keep the last N" and/or "delete after N days", separately for local files and
remote copies, globally or per server.

**Acceptance Scenarios**:

1. **Given** keep-last 7, **When** the 8th backup of a database succeeds, **Then** the oldest
   local file is deleted and its run records "removed by retention" with the time.
2. **Given** a max age of 30 days, **Then** older backups are deleted by the hourly sweep,
   **except** the newest backup of each database, which is always kept.
3. **Given** "Preview and apply now", **Then** the admin sees exactly what would be deleted
   before confirming.
4. **Given** a remote copy cannot be deleted, **Then** the error is recorded on the run and
   reported; the deletion is retried on the next pass.
5. Failed, queued and running runs are never touched.

### Edge Cases

- The panel is down when a schedule should fire: it still runs if the panel is back within
  `MBP_SCHEDULE_MISFIRE_GRACE_SECONDS`; missed runs are coalesced into one.
- The panel restarts during an upload: the upload is marked failed ("interrupted") on start.
- Runs of a deleted server keep their name and fall under the global retention policy.
- A database name starting with `-` (would be parsed as a dump option) is rejected everywhere.

## Requirements

- **FR-001**: Admins MUST be able to create, edit, enable/disable and delete cron schedules
  per server, with an IANA time zone and scope "all marked databases" or "one database".
- **FR-002**: Schedules MUST run inside the backend with APScheduler (Constitution IV).
- **FR-003**: Remote storage MUST be behind a provider-neutral interface; S3-compatible only.
- **FR-004**: Uploads and remote downloads MUST stream with bounded memory (multipart).
- **FR-005**: The remote secret MUST be encrypted at rest and never returned or logged.
- **FR-006**: Upload failures MUST be visible on the run and retryable.
- **FR-007**: Retention MUST support keep-last and max-age for local and remote copies,
  globally with per-server override, and MUST never delete the newest backup of a database.
- **FR-008**: Retention MUST record what it deleted (time and reason on the run) and report
  errors; it MUST only consider successful, fully recorded runs.
- **FR-009**: All new UI MUST be translated to Persian and English (Constitution VIII).

## Success Criteria

- **SC-001**: A schedule's backups appear within seconds of the scheduled time.
- **SC-002**: A backup of any size uploads with memory use bounded by part size x concurrency.
- **SC-003**: No secret appears in API responses, logs or run records (tested).
- **SC-004**: Real MySQL 8.4 and MariaDB 11.8 backups upload to a real S3 server, are removed
  locally by retention, download from the remote copy and restore identically (tested).

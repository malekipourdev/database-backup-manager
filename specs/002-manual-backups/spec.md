# Feature Specification: Manual Backups with Compression, Verification, History and Download

**Feature Branch**: `002-manual-backups`

**Created**: 2026-10-11

**Status**: Draft

**Input**: User description: "Manual on-demand backups with compression, history, download and
verification. From an instance's page, the admin can start a backup immediately, either of all
databases marked for backup on that instance or of a single selected database. Each database
produces its own backup file. Backup settings (global defaults, overridable per instance):
storage directory, file naming pattern (with placeholders such as instance name, database name,
date/time), and compression type (gzip, bzip2, or none). While a backup is running, the admin sees
its progress/status (queued, running, success, failed) without blocking the UI, and can start
backups for other instances in parallel. Two backups of the same database cannot run at the same
time. After each backup, the file is verified (archive integrity + checksum). The run is recorded
with: instance, database, start/end time, duration, file size, compression type, checksum, status,
and a readable error message on failure. A backup history page lists all runs with filters
(instance, database, status, date range) and sorting. From the history, the admin can download a
backup file directly (streamed, works for large files) and delete a backup (file + record, with
confirmation). Partial or failed backup files must never appear as successful and must be cleaned
up."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Back up an instance's databases on demand (Priority: P1)

On an instance's page, the admin clicks "Back up now". A separate backup run starts for each
database marked for backup on that instance. Alternatively, the admin picks one database and backs
up only that one. Each run produces its own compressed, verified backup file. The admin can keep
using the panel while backups run.

**Why this priority**: Producing a trustworthy backup file is the core value of the product.
Everything else in this feature (history, download, settings) depends on it.

**Independent Test**: With a reachable instance that has two databases marked for backup, click
"Back up now". Two runs appear and finish as successful, and two verified files exist in the
storage directory. Then back up a single database and confirm exactly one new run and one new
file.

**Acceptance Scenarios**:

1. **Given** an instance with databases `shop` and `blog` marked for backup, **When** the admin
   chooses "Back up all marked databases", **Then** two runs are created (one per database), each
   produces its own file, and both end as successful.
2. **Given** an instance, **When** the admin chooses "Back up this database" for `shop` only,
   **Then** exactly one run is created and one file is produced for `shop`.
3. **Given** an instance with no databases marked for backup, **When** the admin opens its page,
   **Then** "Back up all marked databases" is unavailable, with a hint to mark databases first.
4. **Given** a backup that completes, **When** it is recorded, **Then** the run shows instance,
   database, start time, end time, duration, file size, compression type, checksum and status
   "success".
5. **Given** a run is in progress, **When** the admin navigates elsewhere in the panel or reloads
   the page, **Then** the backup keeps running and its current status is shown when the admin
   returns.

---

### User Story 2 - See failures clearly; never keep broken files (Priority: P1)

When a backup cannot be completed, for example because the server is unreachable, the user lacks
privileges, the disk is full, the dump stops halfway, or verification fails, the run is marked
"failed" with a readable explanation. No partial or unverified file is left behind or offered as
a usable backup.

**Why this priority**: A failed backup that looks successful is worse than no backup
(Constitution Principle II). This is as important as producing backups at all.

**Independent Test**: Trigger failures on purpose (stop the database server mid-run, revoke
privileges, fill the storage disk, corrupt the file before verification). Each run ends "failed"
with a specific message, no file remains in the storage directory, and no download is offered.

**Acceptance Scenarios**:

1. **Given** an unreachable instance, **When** a backup is started, **Then** the run ends "failed"
   with the same kind of connection explanation as the connection test (host not found, refused,
   timeout, credentials rejected).
2. **Given** the database user lacks a privilege needed for the dump, **When** a backup runs,
   **Then** it fails with a message naming the missing permission as reported by the server.
3. **Given** a dump that is interrupted partway (server stops, connection lost), **When** the run
   ends, **Then** it is "failed" and the partial file has been deleted.
4. **Given** the storage location runs out of space, **When** a backup is writing, **Then** the
   run fails with "not enough disk space" and the partial file is deleted.
5. **Given** a produced file fails verification, **When** the run is recorded, **Then** it is
   "failed" with "verification failed", and the file is deleted.
6. **Given** the panel is stopped or restarted while runs are queued or running, **When** it
   starts again, **Then** those runs are marked "failed" with the message "interrupted by panel
   restart", and their partial files are deleted.

---

### User Story 3 - Watch progress without blocking, run in parallel safely (Priority: P2)

While backups run, the admin sees each run's status change (queued → running → success/failed)
and, while running, how much data has been written so far and the elapsed time. The admin can
start backups on other instances at the same time. Starting a second backup of a database that is
already queued or running is refused.

**Why this priority**: Large databases take a long time. Admins need feedback and must not be
blocked from other work. Preventing duplicate runs protects the server and avoids confusing
history.

**Independent Test**: Start a large backup on instance A, then immediately start a backup on
instance B. Both show live status. Try to start the same database on A again: the request is
refused with a clear message.

**Acceptance Scenarios**:

1. **Given** a running backup, **When** the admin views the instance page or the history page,
   **Then** status, bytes written so far and elapsed time update automatically within 5 seconds,
   without a page reload.
2. **Given** a backup of `shop` on instance A is queued or running, **When** the admin starts a
   backup of `shop` on instance A again, **Then** no new run is created and the admin is told a
   backup of that database is already in progress.
3. **Given** "Back up all marked databases" while one of them is already running, **When** the
   request is made, **Then** runs are created for the others, and the admin is told which
   database was skipped and why.
4. **Given** backups running on instance A, **When** the admin starts backups on instance B,
   **Then** they are accepted and run in parallel up to the concurrency limit; any beyond the
   limit wait as "queued" and start automatically.

---

### User Story 4 - Browse history, download and delete backups (Priority: P2)

A history page lists all backup runs. The admin can filter by instance, database, status and
date range, and sort by any column. From a successful run, the admin downloads the backup file
directly in the browser, which works for very large files. The admin can delete a backup, which
removes both its file and its record after confirmation.

**Why this priority**: Backups are only useful if they can be found and retrieved. Deleting is
needed to free space until retention policies arrive in a later feature.

**Independent Test**: Create several runs across two instances, including a failure. Filter by
instance and status, sort by size, download a successful file and compare its checksum with the
recorded one, then delete it and confirm both the record and the file are gone.

**Acceptance Scenarios**:

1. **Given** runs on several instances, **When** the admin filters by instance, database, status
   and/or a date range, **Then** only matching runs are listed, and the filters can be combined
   and cleared.
2. **Given** the history list, **When** the admin sorts by start time, duration, size, instance,
   database or status, **Then** the order changes accordingly. The default is newest first.
3. **Given** a successful run, **When** the admin clicks download, **Then** the browser downloads
   the file under its stored file name, and the downloaded file's checksum equals the recorded
   checksum.
4. **Given** a multi-gigabyte backup file, **When** it is downloaded, **Then** the download starts
   immediately and completes without the panel slowing down or running out of memory.
5. **Given** a completed run (success or failed), **When** the admin chooses delete and confirms,
   **Then** the record is removed and, if a file exists, the file is deleted from storage.
6. **Given** a run that is queued or running, **Then** it cannot be deleted.
7. **Given** a successful run whose file was removed from disk outside the panel, **When** the
   history is shown, **Then** the run is marked "file missing", download is unavailable, and the
   record can still be deleted.

---

### User Story 5 - Configure where and how backups are stored (Priority: P3)

In global settings the admin sets the default storage directory, file naming pattern and
compression type (gzip, bzip2 or none). On an instance, the admin can override any of these or
keep the global default. A preview shows the file name the current pattern will produce.

**Why this priority**: Sensible defaults let backups work without configuring anything. Settings
refine where files go and how they're named.

**Independent Test**: Change the global compression to bzip2 and the naming pattern, back up an
instance that uses the defaults (gets the new settings), and one that overrides compression to
none (keeps its override).

**Acceptance Scenarios**:

1. **Given** a fresh installation, **Then** global defaults exist: storage directory = the root of
   the backup storage area, pattern = `{instance}/{database}_{date}_{time}`, compression = gzip.
2. **Given** the global settings, **When** the admin edits the pattern, **Then** a live preview
   shows the resulting file name for an example instance and database, including the extension
   added for the chosen compression.
3. **Given** a pattern without `{database}` or without a date/time placeholder, **When** the admin
   saves, **Then** it is rejected, because files of different databases or different runs would
   collide.
4. **Given** an instance that overrides compression to "none" and inherits everything else,
   **When** a backup runs, **Then** it uses no compression and the global directory and pattern.
5. **Given** a storage directory outside the backup storage area (for example `/etc` or a path
   with `..`), **When** the admin saves, **Then** it is rejected.
6. **Given** settings are changed, **Then** existing backup files and their records are not
   moved or renamed. Only new runs use the new settings.

---

### Edge Cases

- **Two runs produce the same file name** (same second, pattern without seconds): a numeric suffix
  is added. An existing file is never overwritten.
- **Special characters in names**: characters in instance or database names that are unsafe in
  file names (`/`, `\`, `:`, spaces, control characters) are replaced in the generated file name.
  Persian and other non-Latin letters are kept.
- **Empty database (no tables)**: the backup succeeds with a small but valid file.
- **Database dropped after it was marked**: a backup of it fails with "database not found on
  server". Other databases in the same request are unaffected.
- **Instance deleted while its backup runs**: the run finishes or fails normally and keeps the
  instance name it started with. Deleting an instance never deletes its backup files or history.
- **Instance renamed**: existing history keeps the name at the time of the run; new runs use the
  new name.
- **Deleting the only successful backup of a database**: allowed after confirmation. The
  confirmation text says it is the latest successful backup.
- **Admin's session expires during a long backup**: the backup continues; the admin sees the
  result after signing in again.
- **Download interrupted**: the admin can simply start the download again.
- **Many runs**: the history stays usable with at least 10,000 runs (paged, 50 per page).

## Requirements *(mandatory)*

### Functional Requirements

**Starting backups**

- **FR-001**: Admin MUST be able to start, from an instance's page, a backup of all databases
  currently marked for backup on that instance. One run is created per database.
- **FR-002**: Admin MUST be able to start, from an instance's page, a backup of a single database
  chosen from the databases currently on that instance, whether or not it is marked for backup.
  System schemas `information_schema`, `performance_schema` and `sys` are excluded, as in feature
  001.
- **FR-003**: Starting backups MUST return immediately. Backups run in the background and the UI
  is never blocked waiting for them.
- **FR-004**: System MUST NOT create a run for a database (same instance and database name) that
  already has a run queued or running. The admin is told which databases were skipped and why.
- **FR-005**: System MUST run backups of different databases in parallel up to a concurrency
  limit (default 2 simultaneous runs, configurable at deployment). Additional runs wait as
  "queued" and start automatically in the order they were requested.
- **FR-006**: System MUST detect the server type and version at the start of each run and use a
  compatible dump method. The dump MUST be a consistent snapshot for transactional tables, and
  MUST include the routines, triggers and events of the database.
- **FR-007**: The dump MUST be streamed and compressed while it is produced, never held fully in
  memory (Constitution Principle VII).

**Settings**

- **FR-008**: System MUST provide global backup settings: storage directory, file naming pattern
  and compression type (`gzip`, `bzip2`, `none`), with the defaults in US5 scenario 1.
- **FR-009**: Each instance MUST allow overriding each setting individually, or inheriting the
  global value. The effective settings are shown on the instance page.
- **FR-010**: The naming pattern MUST support the placeholders `{instance}`, `{database}`,
  `{date}` (YYYY-MM-DD), `{time}` (HHMMSS), `{datetime}` (YYYY-MM-DD_HHMMSS) and `{server_type}`.
  `/` in a pattern creates subdirectories. The file extension (`.sql`, `.sql.gz`, `.sql.bz2`) is
  added automatically. Dates and times use UTC so names sort chronologically.
- **FR-011**: A pattern MUST contain `{database}` and at least one of `{date}`, `{time}`,
  `{datetime}`; otherwise saving is rejected. Unknown placeholders MUST be rejected.
- **FR-012**: The storage directory MUST be inside the backup storage area configured at
  deployment. Absolute paths outside it, `..` segments and symbolic links leading outside it MUST
  be rejected.
- **FR-013**: Unsafe file-name characters from instance or database names MUST be replaced. The
  generated name MUST never overwrite an existing file (a numeric suffix is added instead).
- **FR-014**: Each run MUST record the effective settings it used (compression type and final
  file path), so later settings changes don't affect existing runs.

**Status, progress and failure handling**

- **FR-015**: Each run MUST have one of the statuses `queued`, `running`, `success`, `failed`.
  Allowed transitions: queued → running → success | failed, and queued → failed (e.g. on restart).
- **FR-016**: While running, the run MUST expose bytes written so far and elapsed time. The UI
  MUST refresh status and progress automatically at least every 5 seconds while any visible run is
  queued or running.
- **FR-017**: A backup MUST be written under a temporary name and only receive its final name
  after it has been completely written and successfully verified. Files under temporary names
  MUST never be listed as backups or offered for download.
- **FR-018**: On any failure (connection, permission, dump error, disk full, verification, panel
  stopped), the run MUST be marked `failed` and any partial or unverified file MUST be deleted.
- **FR-019**: On startup, the system MUST mark all runs left `queued` or `running` as `failed`
  ("interrupted by panel restart") and delete leftover temporary files in the storage area.
- **FR-020**: Failure messages MUST be readable and specific, covering at least: connection
  failure (same categories as connection testing), missing privileges, database not found,
  dump error (with the server's message, stripped of secrets), not enough disk space,
  verification failed, interrupted by restart. Messages MUST be translatable (Persian/English),
  and MUST never contain passwords.

**Verification and recording**

- **FR-021**: After writing, every backup MUST be verified: (a) a SHA-256 checksum is computed and
  stored; (b) the compressed archive is fully read back and decompressed without error (for
  `none`, the file is read back completely); (c) the dump content ends with the dump tool's
  completion marker. A run is `success` only if all checks pass.
- **FR-022**: Each run MUST record: instance (reference and name at run time), database, status,
  start time, end time, duration, file size, compression type, checksum, stored file name, error
  message (on failure), and whether it was started for "all marked" or a single database.

**History, download and deletion**

- **FR-023**: System MUST provide a history page listing all runs, paged at 50 per page, with
  filters for instance, database, status and date range (by start time), combinable, and sorting
  by start time, duration, size, instance, database and status. The default sort is start time,
  newest first.
- **FR-024**: Admin MUST be able to download the file of a successful run. The download MUST be
  streamed, start without waiting for the whole file to be read, use bounded memory regardless of
  file size, and use the stored file name.
- **FR-025**: Admin MUST be able to delete a completed run (success or failed) after confirmation.
  This removes its file (if any) and its record. Runs that are queued or running MUST NOT be
  deletable.
- **FR-026**: If a successful run's file no longer exists on disk, the history MUST show it as
  "file missing" and disable download.
- **FR-027**: Deleting an instance MUST NOT delete its backup files or history records. Runs keep
  the instance name they were recorded with.

**General**

- **FR-028**: All new pages, messages, statuses and dates MUST be bilingual (Persian RTL / English
  LTR). Dates and durations are shown in the selected language's format. File sizes are shown in
  human-readable units.
- **FR-029**: All new pages and actions MUST require the authenticated admin (Constitution
  Principle I). Downloads MUST NOT be reachable through unauthenticated or guessable links.

### Key Entities

- **Backup Settings (global)**: the single set of default storage directory, naming pattern and
  compression type.
- **Instance Backup Overrides**: per-instance optional values for each setting; an empty value
  means "inherit global". Belongs to one Database Instance (feature 001).
- **Backup Run**: one attempt to back up one database of one instance. Attributes: instance
  reference (nullable after instance deletion), instance name at run time, database name, trigger
  ("all marked" or "single"), status, requested/start/end time, duration, bytes written
  (progress), final file size, compression type, checksum, stored file path, error code and
  readable message.
- **Backup File**: the verified file on disk belonging to exactly one successful Backup Run.
  Temporary files of runs in progress are not Backup Files.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An admin can start a backup of all marked databases of an instance with at most 2
  clicks from the instance page.
- **SC-002**: 100% of runs that end `success` have a file whose checksum matches the recorded
  checksum and that decompresses without error (verified by re-checking every successful file in
  tests).
- **SC-003**: In fault-injection tests (server stopped mid-dump, privileges revoked, disk full,
  corrupted file, panel killed mid-run), 100% of runs end `failed` with a specific message, and 0
  partial or temporary files remain afterwards.
- **SC-004**: A 10 GB database can be backed up and downloaded while the panel's memory use stays
  below 300 MB throughout.
- **SC-005**: Status changes of a run are visible in the UI within 5 seconds without reloading.
- **SC-006**: Starting a backup returns control to the admin within 1 second, regardless of
  database size.
- **SC-007**: Duplicate runs for the same database never execute at the same time (verified by
  concurrent start requests in tests).
- **SC-008**: The history page with 10,000 runs shows filtered and sorted results within 2
  seconds.
- **SC-009**: Backups succeed and verify on both MySQL 8 and the current MariaDB LTS release.
- **SC-010**: Every screen and message of this feature is fully usable in both Persian and
  English, with no untranslated text.

## Assumptions

- **Storage area**: The backup storage area is a single directory fixed at deployment (by default
  a dedicated volume mounted into the panel, e.g. `/backups`). The storage directory setting is a
  path relative to this area. This keeps the admin from writing files anywhere on the server.
- **Backup format**: A backup is a logical SQL dump of one database, including its schema, data,
  routines, triggers and events. Physical/binary backups and backups of user accounts and grants
  are out of scope.
- **Compression**: The default compression level of each format is used; choosing a level is out
  of scope.
- **Progress**: Progress means bytes written and elapsed time. A percentage or ETA is not shown,
  because the final size isn't known in advance.
- **Cancellation**: Cancelling a running backup is out of scope for this feature.
- **Scheduling and remote storage**: Scheduled backups, uploading to S3-compatible storage,
  retention policies, restore and notifications are separate features and out of scope here.
- **Encryption at rest**: Encrypting backup files is out of scope. Files are protected by the
  storage area's file permissions.
- **Concurrency limit**: The default limit of 2 simultaneous runs is a deployment setting, not
  an admin setting in the UI.
- **Time zone**: File names use UTC, while the UI shows dates in the admin's selected language
  format and local time.
- **History retention**: Run records are kept until the admin deletes them. Automatic cleanup
  arrives with retention policies.
- **Dependency on feature 001**: Instances, credentials, server-type detection, connection error
  categories and database selection come from feature 001.

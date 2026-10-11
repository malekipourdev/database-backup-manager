# Data Model: Manual Backups

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-10-11

This feature adds two tables and three columns. All are delivered in Alembic migration
`0002_backups` and use only portable types (Principle V). Timestamps are `UTCDateTime` (feature
001). File paths are stored **relative to the backup storage root** (`MBP_BACKUP_ROOT`).

## backup_settings (new, single row)

Global defaults (FR-008). Exactly one row, `id = 1`, created by the migration.

| Field | Type | Rules |
|-------|------|-------|
| id | Integer PK | Always 1 |
| storage_dir | String(255) | Relative path inside the storage root; `""` = the root itself. No absolute path, no `..` segment, no empty segments. Default `""`. |
| name_pattern | String(255) | Default `{instance}/{database}_{date}_{time}`. Must contain `{database}` and one of `{date}`, `{time}`, `{datetime}`. Only the known placeholders `{instance}`, `{database}`, `{date}`, `{time}`, `{datetime}`, `{server_type}` are allowed. No leading `/`, no `..` segment. |
| compression | String(8) | `gzip` \| `bzip2` \| `none`. Default `gzip`. |
| updated_at | UTCDateTime | |

## db_instances (feature 001): new override columns

FR-009. `NULL` means "inherit the global value". The same validation rules as above apply when
the value is non-null.

| Field | Type |
|-------|------|
| backup_storage_dir | String(255), nullable |
| backup_name_pattern | String(255), nullable |
| backup_compression | String(8), nullable |

**Effective settings** = override if not NULL, else the global value. They are computed by the
service and **snapshotted into each run** when it starts (FR-014).

## backup_runs (new)

One row per attempt to back up one database (spec: Backup Run).

| Field | Type | Rules |
|-------|------|-------|
| id | Integer PK | |
| instance_id | FK → db_instances.id, nullable | `ON DELETE SET NULL` (FR-027) |
| instance_name | String(100) | Instance name at request time; never updated |
| database_name | String(64) | Required |
| trigger | String(8) | `all` \| `single` |
| status | String(10) | `queued` \| `running` \| `success` \| `failed`; indexed |
| active_key | String(200), nullable, **unique** | `"<instance_id>:<database_name>"` while queued/running, else NULL (research §8) |
| requested_at | UTCDateTime | Set on insert; indexed (default sort) |
| started_at | UTCDateTime, nullable | Set on queued → running |
| finished_at | UTCDateTime, nullable | Set on → success/failed |
| duration_ms | BigInteger, nullable | `finished_at - started_at`; stored for sorting |
| bytes_processed | BigInteger | Uncompressed bytes read from the dump so far (progress); default 0 |
| file_size | BigInteger, nullable | Final compressed size; success only |
| compression | String(8), nullable | Effective compression snapshot |
| checksum_sha256 | String(64), nullable | Hex digest of the final file; success only |
| file_path | String(1024), nullable | Relative to the storage root; set when the final name is chosen, kept only on success |
| server_type | String(16), nullable | Detected at run start |
| server_version | String(64), nullable | Detected at run start |
| error_code | String(32), nullable | Codes in research §7 |
| error_message | Text, nullable | Sanitized, ≤ 1,000 chars, never contains secrets |

**Indexes**: `status`, `requested_at`, `instance_id`, `database_name`, unique `active_key`.

### State transitions (FR-015)

```text
           create (active_key set)
                  │
                  ▼
   ┌──────────  queued  ──────────┐
   │ worker picks up              │ startup recovery / shutdown / instance deleted
   ▼                              ▼
running ── pipeline ok + verified ──► success   (active_key=NULL, file_path, size, checksum)
   │
   └── any error / shutdown / startup recovery ──► failed  (active_key=NULL, temp file deleted,
                                                            error_code + error_message)
```

**Invariants**

- `status = success` ⇔ `checksum_sha256`, `file_size` and `file_path` are non-null and the file
  was verified (FR-021).
- `status ∈ {queued, running}` ⇔ `active_key` is non-null.
- A `failed` run never has a file on disk. Its `file_path` is cleared, and the temp file was
  deleted.
- Deleting a run (FR-025) is allowed only when `status ∈ {success, failed}`. It deletes the file
  first (a missing file is ignored), then the row.

## Derived (not stored)

| Field | Meaning |
|-------|---------|
| `file_available` | `status = success` and the file exists under the storage root (FR-026) |
| `file_name` | Base name of `file_path` (download name) |
| `elapsed_ms` | For running runs: `now - started_at` |

## Filesystem layout

```text
$MBP_BACKUP_ROOT/                       # /backups in the container (volume)
└── <storage_dir>/                      # effective setting, may be ""
    └── <rendered pattern>.<ext>        # e.g. prod/shop_2026-10-11_130820.sql.gz
        .<name>.<run_id>.mbp-partial    # temp file while running; never listed
```

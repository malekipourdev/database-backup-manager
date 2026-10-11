import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from mbp.backups.dump_command import is_safe_database_name

_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


def validate_host(value: str) -> str:
    """Hostname, IPv4 or IPv6 literal; no scheme, path, credentials or spaces."""
    value = value.strip()
    if not value or not _HOST_RE.match(value):
        raise ValueError("invalid_host")
    return value


def validate_database_name(value: str) -> str:
    if not is_safe_database_name(value):
        raise ValueError("invalid_database_name")
    return value


def validate_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("name_required")
    return value


# --- Auth ---


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=1024)


class Me(BaseModel):
    username: str


# --- Instances ---


class InstanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=1024)
    notes: str = Field(default="", max_length=2000)

    _name = field_validator("name")(validate_name)
    _host = field_validator("host")(validate_host)


class InstanceUpdate(BaseModel):
    """Partial update. Omitted or empty `password` keeps the stored password."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: SecretStr | None = Field(default=None, max_length=1024)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else validate_name(value)

    @field_validator("host")
    @classmethod
    def _host(cls, value: str | None) -> str | None:
        return None if value is None else validate_host(value)


class Instance(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    host: str
    port: int
    username: str
    notes: str
    has_password: Literal[True] = True
    server_type: Literal["mysql", "mariadb"] | None = None
    server_version: str | None = None
    last_test_at: datetime | None = None
    last_test_ok: bool | None = None
    last_test_error_code: str | None = None
    created_at: datetime
    updated_at: datetime


# --- Connection testing ---


class ConnectionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=1024)

    _host = field_validator("host")(validate_host)


ErrorCode = Literal[
    "host_not_found", "connection_refused", "timeout", "auth_rejected", "server_error"
]


class ConnectionTestResult(BaseModel):
    ok: bool
    tested_at: datetime
    server_type: Literal["mysql", "mariadb"] | None = None
    server_version: str | None = None
    error_code: ErrorCode | None = None
    error_detail: str | None = None


# --- Databases ---


class DatabaseEntry(BaseModel):
    name: str
    is_system: bool
    selectable: bool
    selected: bool
    missing: bool


class DatabaseList(BaseModel):
    reachable: bool
    error_code: str | None = None
    error_detail: str | None = None
    databases: list[DatabaseEntry]


class SelectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    databases: list[str] = Field(max_length=10000)

    @field_validator("databases")
    @classmethod
    def _names(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate_names")
        for name in value:
            if not is_safe_database_name(name):
                raise ValueError("invalid_name")
        return value


# --- Backups ---

Compression = Literal["gzip", "bzip2", "none"]
RunStatus = Literal["queued", "running", "success", "failed"]


class BackupSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_dir: str = Field(default="", max_length=255)
    name_pattern: str = Field(max_length=255)
    compression: Compression


class InstanceBackupOverrides(BaseModel):
    """null means "inherit the global value"."""

    model_config = ConfigDict(extra="forbid")

    storage_dir: str | None = Field(default=None, max_length=255)
    name_pattern: str | None = Field(default=None, max_length=255)
    compression: Compression | None = None


class InstanceBackupSettings(BaseModel):
    overrides: InstanceBackupOverrides
    effective: BackupSettingsBody


class PatternPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_dir: str = Field(default="", max_length=255)
    name_pattern: str = Field(max_length=255)
    compression: Compression
    instance_name: str = Field(default="prod", min_length=1, max_length=100)
    database_name: str = Field(default="shop", min_length=1, max_length=64)


class PatternPreview(BaseModel):
    path: str


RemoteStatus = Literal["uploading", "success", "failed", "deleted"]


class BackupRunOut(BaseModel):
    id: int
    instance_id: int | None
    instance_name: str
    database_name: str
    trigger: Literal["all", "single", "schedule"]
    schedule_id: int | None = None
    status: RunStatus
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    elapsed_ms: int | None = None
    bytes_processed: int
    file_size: int | None = None
    compression: Compression | None = None
    checksum_sha256: str | None = None
    file_name: str | None = None
    file_available: bool
    server_type: Literal["mysql", "mariadb"] | None = None
    server_version: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    file_deleted_at: datetime | None = None
    file_deleted_reason: Literal["retention"] | None = None
    remote_status: RemoteStatus | None = None
    remote_uploaded_at: datetime | None = None
    remote_deleted_at: datetime | None = None
    remote_error: str | None = None
    remote_available: bool = False
    # True if the file can be downloaded (from local storage, or else from the remote copy).
    download_available: bool = False


class StartAllRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["all"]


class StartSingleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["single"]
    database: str = Field(min_length=1, max_length=64)

    _database = field_validator("database")(validate_database_name)


class SkippedDatabase(BaseModel):
    database: str
    reason: Literal["already_in_progress"]


class StartBackupResponse(BaseModel):
    created: list[BackupRunOut]
    skipped: list[SkippedDatabase]


class RunPage(BaseModel):
    items: list[BackupRunOut]
    total: int
    page: int
    page_size: int


# --- Schedules ---

ScheduleScope = Literal["all", "single"]


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    cron: str = Field(min_length=1, max_length=100)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    scope: ScheduleScope
    database: str | None = Field(default=None, max_length=64)
    enabled: bool = True

    _name = field_validator("name")(validate_name)

    @field_validator("cron", "timezone")
    @classmethod
    def _strip(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("database")
    @classmethod
    def _database(cls, value: str | None) -> str | None:
        return None if value in (None, "") else validate_database_name(value)


class ScheduleOut(BaseModel):
    id: int
    instance_id: int
    instance_name: str
    name: str
    cron: str
    timezone: str
    scope: ScheduleScope
    database: str | None
    enabled: bool
    next_run_at: datetime | None = None
    last_fired_at: datetime | None = None
    last_result: str | None = None
    last_detail: str | None = None
    created_at: datetime
    updated_at: datetime


class SchedulePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cron: str = Field(min_length=1, max_length=100)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class SchedulePreview(BaseModel):
    next_runs: list[datetime]


# --- Remote storage ---


class RemoteStorageIn(BaseModel):
    """Empty or omitted `secret_access_key` keeps the stored secret."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    endpoint_url: str = Field(default="", max_length=255)
    region: str = Field(default="", max_length=64)
    bucket: str = Field(default="", max_length=255)
    prefix: str = Field(default="", max_length=255)
    access_key_id: str = Field(default="", max_length=255)
    secret_access_key: SecretStr | None = Field(default=None, max_length=1024)
    force_path_style: bool = True

    @field_validator("endpoint_url")
    @classmethod
    def _endpoint(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if value and not re.match(r"^https?://[A-Za-z0-9._\[\]:-]+(/[^\s]*)?$", value):
            raise ValueError("invalid_endpoint")
        return value

    @field_validator("bucket")
    @classmethod
    def _bucket(cls, value: str) -> str:
        value = value.strip()
        if value and not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,254}$", value):
            raise ValueError("invalid_bucket")
        return value

    @field_validator("prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        value = value.strip().strip("/")
        if any(part in ("", ".", "..") for part in value.split("/")) and value:
            raise ValueError("invalid_prefix")
        return value

    @field_validator("region", "access_key_id")
    @classmethod
    def _plain(cls, value: str) -> str:
        return value.strip()


class RemoteStorageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    provider: Literal["s3"]
    endpoint_url: str
    region: str
    bucket: str
    prefix: str
    access_key_id: str
    has_secret: bool
    force_path_style: bool


class RemoteTestOut(BaseModel):
    ok: bool
    error_code: str | None = None
    error_detail: str | None = None


# --- Retention ---


class RetentionPolicyBody(BaseModel):
    """null turns a rule off. The newest backup of each database is always kept."""

    model_config = ConfigDict(extra="forbid")

    local_keep_last: int | None = Field(default=None, ge=1, le=100000)
    local_max_age_days: int | None = Field(default=None, ge=1, le=36500)
    remote_keep_last: int | None = Field(default=None, ge=1, le=100000)
    remote_max_age_days: int | None = Field(default=None, ge=1, le=36500)


class InstanceStoragePolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remote_upload: Literal["inherit", "enabled", "disabled"] = "inherit"
    retention_override: bool = False
    retention: RetentionPolicyBody = Field(default_factory=RetentionPolicyBody)


class InstanceStoragePolicyOut(BaseModel):
    remote_upload: Literal["inherit", "enabled", "disabled"]
    retention_override: bool
    retention: RetentionPolicyBody
    effective_upload: bool
    effective_retention: RetentionPolicyBody


class RetentionApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True


class RetentionItemOut(BaseModel):
    run_id: int
    target: Literal["local", "remote"]
    instance_name: str
    database_name: str
    file_name: str | None
    finished_at: datetime | None
    error_code: str | None = None
    error_message: str | None = None


class RetentionReportOut(BaseModel):
    dry_run: bool
    deleted: list[RetentionItemOut]
    errors: list[RetentionItemOut]

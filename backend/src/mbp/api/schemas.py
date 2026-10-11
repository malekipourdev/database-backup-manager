import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


def validate_host(value: str) -> str:
    """Hostname, IPv4 or IPv6 literal; no scheme, path, credentials or spaces."""
    value = value.strip()
    if not value or not _HOST_RE.match(value):
        raise ValueError("invalid_host")
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
            if not 1 <= len(name) <= 64:
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


class BackupRunOut(BaseModel):
    id: int
    instance_id: int | None
    instance_name: str
    database_name: str
    trigger: Literal["all", "single"]
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


class StartAllRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["all"]


class StartSingleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["single"]
    database: str = Field(min_length=1, max_length=64)


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

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
    two_factor_enabled: bool = False


class LoginResponse(BaseModel):
    """Signed in (`username`), or `two_factor_required` with a `challenge` for step two."""

    username: str
    two_factor_required: bool = False
    # Short-lived token for POST /auth/login/2fa; not a session.
    challenge: str | None = None


class SecondFactorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge: str = Field(min_length=1, max_length=2000)
    # A 6-digit authenticator code or a recovery code.
    code: SecretStr = Field(min_length=1, max_length=40)


class TwoFactorStatus(BaseModel):
    enabled: bool
    recovery_codes_left: int


class PasswordConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: SecretStr = Field(min_length=1, max_length=1024)


class CodeConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: SecretStr = Field(min_length=1, max_length=40)


class PasswordAndCode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: SecretStr = Field(min_length=1, max_length=1024)
    code: SecretStr = Field(min_length=1, max_length=40)


class TwoFactorSetup(BaseModel):
    # Shown once so the admin can scan or type it; never stored in plain text.
    secret: str
    otpauth_uri: str
    qr_svg: str


class RecoveryCodes(BaseModel):
    recovery_codes: list[str]


# --- Instances ---


class InstanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=1024)
    notes: str = Field(default="", max_length=2000)
    # Another server whose agent reaches the database; None: the panel connects itself.
    server_id: int | None = None

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
    # Sent as null: the panel connects itself; omitted: unchanged.
    server_id: int | None = None

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
    server_id: int | None = None
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
    server_id: int | None = None

    _host = field_validator("host")(validate_host)


# host_not_found | connection_refused | timeout | auth_rejected | server_error, or an
# agent's error (agent_unreachable, agent_timeout, ...) for a database on another server.
ErrorCode = str


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
    file_deleted_reason: Literal["retention", "manual"] | None = None
    remote_status: RemoteStatus | None = None
    remote_uploaded_at: datetime | None = None
    remote_deleted_at: datetime | None = None
    remote_error: str | None = None
    remote_available: bool = False
    # When the panel may delete the remote copy (7 days after upload); see REMOTE_PROTECTION.
    remote_deletable_at: datetime | None = None
    remote_deletable: bool = False
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
    # Remote copies are protected for 7 days anyway; a shorter age limit would be misleading.
    remote_max_age_days: int | None = Field(default=None, ge=7, le=36500)


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


# --- Bots ---

Platform = Literal["bale", "telegram"]
NotifyLevel = Literal["info", "warning", "error", "off"]
_URL_RE = r"^https?://[A-Za-z0-9._\[\]:-]+(/[^\s]*)?$"
# No user:password@ part: the URL is stored and shown in plain text, credentials must not be.
_PROXY_RE = r"^(https?|socks5h?)://[A-Za-z0-9._\[\]:-]+/?$"


class BotSettingsIn(BaseModel):
    """Empty or omitted `token` keeps the stored token."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    token: SecretStr | None = Field(default=None, max_length=256)
    api_base_url: str = Field(default="", max_length=255)
    proxy_url: str = Field(default="", max_length=255)
    allow_file_download: bool = False
    max_file_mb: int = Field(default=20, ge=1, le=2000)

    @field_validator("api_base_url")
    @classmethod
    def _base(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if value and not re.match(_URL_RE, value):
            raise ValueError("invalid_url")
        return value

    @field_validator("proxy_url")
    @classmethod
    def _proxy(cls, value: str) -> str:
        value = value.strip()
        if value and not re.match(_PROXY_RE, value):
            raise ValueError("invalid_proxy")
        return value


class BotSettingsOut(BaseModel):
    platform: Platform
    enabled: bool
    has_token: bool
    api_base_url: str
    proxy_url: str
    allow_file_download: bool
    max_file_mb: int
    bot_username: str | None = None
    running: bool = False
    last_ok_at: datetime | None = None
    last_error: str | None = None


class BotTestOut(BaseModel):
    ok: bool
    username: str | None = None
    error_code: str | None = None
    error_detail: str | None = None


class BotAdminCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Platform
    user_id: int = Field(gt=0, lt=2**63)
    display_name: str = Field(min_length=1, max_length=100)

    _name = field_validator("display_name")(validate_name)


class BotAdminUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    notify_level: NotifyLevel | None = None
    language: Literal["fa", "en"] | None = None


class BotAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: Platform
    user_id: int
    display_name: str
    enabled: bool
    notify_level: NotifyLevel
    language: Literal["fa", "en"]
    last_seen_at: datetime | None = None
    created_at: datetime


class LinkCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=100)

    _name = field_validator("display_name")(validate_name)


class LinkCodeOut(BaseModel):
    code: str
    expires_at: datetime
    bot_username: str | None = None
    deep_link: str | None = None


# --- Notifications ---

EventName = Literal[
    "backup_failed",
    "upload_failed",
    "stale_backup",
    "disk_low",
    "schedule_problem",
    "retention_error",
    "container_down",
    "container_restarting",
    "container_unhealthy",
    "container_resources",
    "host_resources",
    "agent_unreachable",
    "site_down",
    "cert_expiring",
    "deploy_failed",
    "deploy_succeeded",
    "backup_succeeded",
    "recovered",
    "daily_summary",
]
Channel = Literal["bale", "telegram", "webhook"]


class NotificationRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    channels: list[Channel]


class NotificationSettingsIn(BaseModel):
    """Empty or omitted `webhook_secret` keeps the stored secret."""

    model_config = ConfigDict(extra="forbid")

    rules: dict[EventName, NotificationRule]
    cooldown_minutes: int = Field(ge=0, le=10080)
    stale_hours: int = Field(ge=1, le=720)
    disk_free_percent: int = Field(ge=1, le=90)
    daily_summary_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(min_length=1, max_length=64)
    webhook_enabled: bool = False
    webhook_url: str = Field(default="", max_length=500)
    webhook_secret: SecretStr | None = Field(default=None, max_length=256)
    clear_webhook_secret: bool = False

    @field_validator("webhook_url")
    @classmethod
    def _webhook(cls, value: str) -> str:
        value = value.strip()
        if value and not re.match(_URL_RE, value):
            raise ValueError("invalid_url")
        return value


class EventInfo(BaseModel):
    name: EventName
    severity: Literal["info", "warning", "error"]


class NotificationSettingsOut(BaseModel):
    rules: dict[str, NotificationRule]
    cooldown_minutes: int
    stale_hours: int
    disk_free_percent: int
    daily_summary_time: str
    timezone: str
    webhook_enabled: bool
    webhook_url: str
    has_webhook_secret: bool
    events: list[EventInfo]


class NotificationTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channels: list[Channel] = Field(min_length=1)


class NotificationTestOut(BaseModel):
    results: dict[str, str]


class NotificationLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    event: str
    severity: Literal["info", "warning", "error"]
    subject: str
    params: dict
    run_id: int | None = None
    channels: dict[str, str]
    suppressed: bool


class NotificationLogPage(BaseModel):
    items: list[NotificationLogItem]
    total: int
    page: int
    page_size: int


# --- Containers ---

ContainerRefPattern = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"


class ContainerPort(BaseModel):
    private: int | None = None
    public: int | None = None
    type: str = "tcp"


class ContainerSummary(BaseModel):
    id: str
    name: str
    image: str
    state: str
    health: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    oom_killed: bool = False
    restart_count: int = 0
    restart_policy: str = "no"
    project: str | None = None
    service: str | None = None
    # Set on the panel's own containers (backend, frontend, agent): never controllable.
    panel: str | None = None
    ports: list[ContainerPort] = []
    locked: bool = False
    monitored: bool = True
    # crashed | restarting | unhealthy
    problem: str | None = None


class ContainerMount(BaseModel):
    type: str | None = None
    source: str | None = None
    destination: str | None = None
    read_only: bool = False


class ContainerNetwork(BaseModel):
    name: str
    ip: str | None = None


class ContainerDetails(ContainerSummary):
    image_id: str | None = None
    hostname: str | None = None
    # Variable names only; values can hold passwords and are never returned.
    env_names: list[str] = []
    mounts: list[ContainerMount] = []
    networks: list[ContainerNetwork] = []
    health_failing_streak: int | None = None
    health_last_output: str | None = None
    tty: bool = False


class ContainerList(BaseModel):
    containers: list[ContainerSummary]
    read_only: bool


class ContainerStats(BaseModel):
    cpu_percent: float | None = None
    memory_usage: int | None = None
    memory_limit: int | None = None
    memory_percent: float | None = None
    net_rx: int | None = None
    net_tx: int | None = None
    block_read: int | None = None
    block_write: int | None = None
    pids: int | None = None


class ContainerStatsMap(BaseModel):
    stats: dict[str, ContainerStats | None]


class ContainerStatsOne(BaseModel):
    stats: ContainerStats | None


class DockerInfo(BaseModel):
    version: str | None = None
    api_version: str | None = None
    os: str | None = None
    kernel: str | None = None
    cpus: int | None = None
    memory_total: int | None = None
    containers: int | None = None
    running: int | None = None
    stopped: int | None = None
    paused: int | None = None
    images: int | None = None
    name: str | None = None


class HostInfo(BaseModel):
    cpu_percent: float | None = None
    load: list[float] | None = None
    memory_total: int | None = None
    memory_available: int | None = None
    disk_total: int | None = None
    disk_free: int | None = None


class ServerInfo(BaseModel):
    docker: DockerInfo
    host: HostInfo


class LogLine(BaseModel):
    stream: Literal["stdout", "stderr"]
    time: str | None = None
    text: str


class ContainerLogs(BaseModel):
    lines: list[LogLine]
    truncated: bool = False


def _patterns(value: list[str]) -> list[str]:
    cleaned = []
    for item in value:
        item = item.strip()
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


class ContainerSettingsIO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_only: bool = False
    hidden: list[str] = Field(default=[], max_length=100)
    locked: list[str] = Field(default=[], max_length=100)
    monitor_all: bool = True
    monitored: list[str] = Field(default=[], max_length=500)
    cpu_percent: int = Field(default=90, ge=0, le=100)
    memory_percent: int = Field(default=90, ge=0, le=100)
    restart_count: int = Field(default=3, ge=0, le=100)
    restart_window_minutes: int = Field(default=10, ge=1, le=1440)
    host_memory_percent: int = Field(default=90, ge=0, le=100)
    host_disk_percent: int = Field(default=90, ge=0, le=100)
    bot_logs: bool = False

    @field_validator("hidden", "locked", "monitored")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        value = _patterns(value)
        if any(len(item) > 128 for item in value):
            raise ValueError("too_long")
        return value


class ContainerActionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor: str
    source: str
    server_id: int | None = None
    server_name: str = ""
    container: str
    action: str
    result: str
    detail: str | None = None


class ContainerActionPage(BaseModel):
    items: list[ContainerActionItem]
    total: int
    page: int
    page_size: int


class ContainerActionResult(BaseModel):
    container: ContainerSummary


# --- Projects and deployments ---


class ProjectEnvItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    # None keeps the stored value (values are never sent back to the browser).
    value: SecretStr | None = Field(default=None, max_length=32768)


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    # The server it is deployed on; None: the panel's own.
    server_id: int | None = None
    # A folder in the list (display only); empty: none.
    folder: str | None = Field(default=None, max_length=60)
    repo_url: str = Field(min_length=1, max_length=500)
    branch: str = Field(default="main", min_length=1, max_length=200)
    compose_file: str = Field(default="docker-compose.yml", min_length=1, max_length=200)
    auth_type: Literal["none", "token", "ssh_key"] = "none"
    # Empty keeps the stored credential.
    credential: SecretStr | None = Field(default=None, max_length=20000)
    clear_credential: bool = False
    env: list[ProjectEnvItem] = Field(default=[], max_length=200)
    backup_instance_id: int | None = None
    backup_databases: list[str] = Field(default=[], max_length=50)
    backup_required: bool = True
    # After a successful deploy: these domains proxied to web_target by the web server.
    web_domains: list[str] = Field(default=[], max_length=20)
    web_target: str | None = Field(default=None, max_length=300)
    # Build the images on this server and send them to the project's server; None: build
    # where it runs.
    build_server_id: int | None = None

    @field_validator("folder")
    @classmethod
    def _folder(cls, value: str | None) -> str | None:
        value = " ".join((value or "").split()) or None
        if value is not None and (
            "/" in value or any(ord(c) < 32 or 0x7F <= ord(c) < 0xA0 for c in value)
        ):
            raise ValueError("invalid_folder")
        return value

    @field_validator("web_domains")
    @classmethod
    def _domains(cls, value: list[str]) -> list[str]:
        names = [v.strip().lower() for v in value if v.strip()]
        pattern = r"([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}"
        if any(not re.fullmatch(pattern, n) for n in names):
            raise ValueError("invalid_domain")
        return list(dict.fromkeys(names))

    @field_validator("web_target")
    @classmethod
    def _target(cls, value: str | None) -> str | None:
        value = (value or "").strip() or None
        if value is not None and not re.fullmatch(
            r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[A-Za-z0-9._~/\-]*)?", value
        ):
            raise ValueError("invalid_target")
        return value

    @field_validator("repo_url", "branch", "compose_file", "name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("backup_databases")
    @classmethod
    def _databases(cls, value: list[str]) -> list[str]:
        if any(not is_safe_database_name(name) for name in value):
            raise ValueError("invalid_database_name")
        return list(dict.fromkeys(value))

    def to_data(self) -> dict:
        data = self.model_dump(exclude={"credential", "env"})
        if self.credential is not None and self.credential.get_secret_value():
            data["credential"] = self.credential.get_secret_value()
        data["env"] = [
            {"name": item.name, "value": item.value.get_secret_value() if item.value else None}
            for item in self.env
        ]
        return data


class DeploymentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    project_name: str
    status: str
    step: str | None = None
    ref: str
    commit_sha: str | None = None
    commit_message: str | None = None
    trigger: str
    actor: str
    error_code: str | None = None
    error_detail: str | None = None
    backup_run_ids: list[int] = []
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DeploymentDetail(DeploymentSummary):
    # The log from `offset` on, and its full length (for the next request).
    log: str
    log_size: int


class DeploymentPage(BaseModel):
    items: list[DeploymentSummary]
    total: int
    page: int
    page_size: int


class ProjectOut(BaseModel):
    id: int
    name: str
    folder: str | None = None
    server_id: int
    server_name: str
    repo_url: str
    branch: str
    compose_file: str
    auth_type: str
    has_credential: bool
    # Names only; values are never returned.
    env_names: list[str]
    backup_instance_id: int | None
    backup_databases: list[str]
    backup_required: bool
    web_domains: list[str] = []
    web_target: str | None = None
    build_server_id: int | None = None
    build_server_name: str | None = None
    created_at: datetime
    updated_at: datetime
    last_deployment: DeploymentSummary | None = None
    last_success: DeploymentSummary | None = None


class ProjectState(BaseModel):
    available: bool
    error_code: str | None = None
    exists: bool = False
    commit_sha: str | None = None
    commit_message: str | None = None


class DeployIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A branch, tag or commit; empty deploys the project's branch.
    ref: str | None = Field(default=None, max_length=200)


# --- Servers ---


class ServerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=8443, ge=1, le=65535)
    notes: str = Field(default="", max_length=2000)

    _name = field_validator("name")(validate_name)
    _host = field_validator("host")(validate_host)


class ServerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=60)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else validate_name(value)

    @field_validator("host")
    @classmethod
    def _host(cls, value: str | None) -> str | None:
        return None if value is None else validate_host(value)


class ServerOut(BaseModel):
    id: int
    name: str
    # local | remote
    kind: str
    host: str | None
    port: int | None
    notes: str
    paired: bool
    cert_fingerprint: str | None
    paired_at: datetime | None
    last_seen_at: datetime | None
    last_error: str | None
    agent_hostname: str | None
    docker_version: str | None
    projects: int
    instances: int
    created_at: datetime


class ServerSetup(BaseModel):
    """Shown once: the agent's token and the commands that install it on the server."""

    server: ServerOut
    token: str
    install_command: str


# --- Web servers (nginx, Apache; read from the host's configuration) ---


class WebBackend(BaseModel):
    # proxy | fastcgi | uwsgi | grpc | scgi
    kind: str
    target: str
    # The servers of an nginx upstream named by the target, if any.
    servers: list[str] = []


class WebSite(BaseModel):
    # nginx | apache
    server: str
    # server_name / ServerName and ServerAlias; empty for a catch-all block.
    names: list[str] = []
    ports: list[int] = []
    ssl: bool = False
    default_server: bool = False
    root: str | None = None
    redirect: str | None = None
    backends: list[WebBackend] = []
    certificate: str | None = None
    file: str
    line: int
    # False: in sites-available (or a conf.d file turned off) but not loaded by the server.
    enabled: bool = True
    # Served by its maintenance page for now.
    maintenance: bool = False
    # The panel's maintenance page itself (hidden in the list).
    maintenance_page: bool = False
    # Access and error log files, if any.
    logs: dict[str, str | None] = {}


class WebServer(BaseModel):
    kind: str
    config: str
    # Why the main configuration file could not be read, if it could not.
    error: str | None = None
    warnings: list[str] = []
    files: int = 0
    sites: list[WebSite] = []


class WebServerList(BaseModel):
    # False: the host's /etc is not mounted in the agent.
    available: bool
    servers: list[WebServer] = []


WebKind = Literal["nginx", "apache"]


class WebServiceStatus(BaseModel):
    kind: str
    service: str
    # active | inactive | failed | activating | reloading | not_installed | unknown
    state: str
    sub_state: str | None = None
    since: str | None = None
    pid: int | None = None
    version: str | None = None
    # From the service's journal, and the panel's own last reload / restart.
    last_reload: str | None = None
    panel_reload: datetime | None = None
    systemd: bool = False


class WebStatusList(BaseModel):
    servers: list[WebServiceStatus]


class WebResult(BaseModel):
    ok: bool
    # config_test_failed | reload_failed | command_failed | backup_failed | ...
    code: str | None = None
    output: str = ""
    path: str | None = None


class WebTestResult(BaseModel):
    ok: bool
    output: str = ""


class WebFileContent(BaseModel):
    path: str
    content: str
    sha256: str
    size: int


class WebFileWrite(BaseModel):
    path: str = Field(max_length=500)
    content: str = Field(max_length=200_000)
    # Of the content that was read: refused if the file changed since.
    sha256: str | None = Field(default=None, max_length=64)


class WebPathIn(BaseModel):
    path: str = Field(max_length=500)


class WebRestoreIn(WebPathIn):
    backup: str = Field(max_length=32)


class WebEnabledIn(WebPathIn):
    enabled: bool


class WebMaintenanceIn(WebPathIn):
    on: bool


class WebBackupList(BaseModel):
    path: str
    backups: list[str]


class WebBackupContent(BaseModel):
    content: str


class WebSiteCreate(BaseModel):
    template: Literal["proxy", "php", "static", "redirect"]
    domains: list[str] = Field(min_length=1, max_length=50)
    name: str | None = Field(default=None, max_length=63)
    target: str | None = Field(default=None, max_length=300)
    root: str | None = Field(default=None, max_length=300)
    php_fpm: str | None = Field(default=None, max_length=300)
    permanent: bool = True
    keep_path: bool = True


class WebLogLines(BaseModel):
    path: str
    lines: list[str]


class WebCertificate(BaseModel):
    subject: str | None = None
    names: list[str] = []
    issuer: str | None = None
    not_before: datetime | None = None
    not_after: datetime | None = None
    error: str | None = None


class WebCertificates(BaseModel):
    certificates: dict[str, WebCertificate]


class WebPhpSockets(BaseModel):
    sockets: list[str]


class CertbotStatus(BaseModel):
    installed: bool
    version: str | None = None
    # certbot.timer, a cron file, or None
    auto_renew: str | None = None
    package_manager: str | None = None


class CertbotIssueIn(BaseModel):
    domains: list[str] = Field(min_length=1, max_length=50)
    email: str | None = Field(default=None, max_length=254)
    redirect: bool = True


class WebJob(BaseModel):
    id: str
    action: str
    target: str
    # running | success | failed
    status: str
    output: str = ""
    started_at: datetime
    finished_at: datetime | None = None


class WebServerSettingsIO(BaseModel):
    read_only: bool = False
    cert_warning_days: int = Field(default=14, ge=0, le=90)
    check_interval_minutes: int = Field(default=5, ge=1, le=1440)
    check_timeout_seconds: int = Field(default=10, ge=1, le=60)
    check_failures: int = Field(default=2, ge=1, le=20)
    # Given to Let's Encrypt for expiry notices.
    acme_email: str | None = Field(default=None, max_length=254)

    @field_validator("acme_email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        value = (value or "").strip() or None
        if value is not None and not re.fullmatch(
            r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,63}", value
        ):
            raise ValueError("invalid email")
        return value


class WebActionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor: str
    source: str
    server_id: int | None
    server_name: str
    kind: str
    action: str
    target: str
    result: str
    output: str | None = None


class WebActionPage(BaseModel):
    items: list[WebActionItem]
    total: int
    page: int
    page_size: int


class WebCheckResultItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    checked_at: datetime
    ok: bool
    code: int | None = None
    ms: int | None = None
    error: str | None = None


class WebCheckItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    server_id: int
    url: str
    enabled: bool
    created_at: datetime
    last_checked_at: datetime | None = None
    status: str | None = None
    last_code: int | None = None
    last_ms: int | None = None
    last_error: str | None = None
    failures: int = 0
    down_since: datetime | None = None
    # Of the last 24 hours, in percent.
    uptime: float | None = None
    recent: list[WebCheckResultItem] = []


class WebCheckList(BaseModel):
    checks: list[WebCheckItem]


class WebCheckIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)


class WebCheckUpdate(BaseModel):
    enabled: bool

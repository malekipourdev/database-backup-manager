"""Alert event types, their severities and default routing."""

from dataclasses import dataclass, field

SEVERITIES = ("info", "warning", "error")
CHANNELS = ("bale", "telegram", "webhook")

# event -> default severity
EVENTS: dict[str, str] = {
    "backup_failed": "error",
    "upload_failed": "error",
    "stale_backup": "error",
    "disk_low": "warning",
    "schedule_problem": "warning",
    "retention_error": "warning",
    "container_down": "error",
    "container_restarting": "error",
    "container_unhealthy": "warning",
    "container_resources": "warning",
    "host_resources": "warning",
    "agent_unreachable": "warning",
    "deploy_failed": "error",
    "deploy_succeeded": "info",
    "backup_succeeded": "info",
    "recovered": "info",
    "daily_summary": "info",
}
# Delivered to every recipient that has not turned notifications off, whatever its level:
# the admin asked for these explicitly (a summary at a set time, or the test button).
ALWAYS_DELIVERED = frozenset({"daily_summary", "test"})


@dataclass
class Event:
    type: str
    # Dedupe key for the cooldown, e.g. "backup_failed:3:shop".
    subject: str
    params: dict = field(default_factory=dict)
    run_id: int | None = None
    severity: str = ""

    def __post_init__(self) -> None:
        if not self.severity:
            self.severity = EVENTS.get(self.type, "info")


def default_rules() -> dict[str, dict]:
    return {name: {"enabled": True, "channels": list(CHANNELS)} for name in EVENTS}


def merged_rules(stored: dict | None) -> dict[str, dict]:
    """Stored rules over the defaults, ignoring unknown events and channels."""
    rules = default_rules()
    for name, rule in (stored or {}).items():
        if name not in rules or not isinstance(rule, dict):
            continue
        if isinstance(rule.get("enabled"), bool):
            rules[name]["enabled"] = rule["enabled"]
        if isinstance(rule.get("channels"), list):
            rules[name]["channels"] = [c for c in rule["channels"] if c in CHANNELS]
    return rules


def level_allows(level: str, event: Event) -> bool:
    """Does a recipient with this minimum level get this event?"""
    if level == "off":
        return False
    if event.type in ALWAYS_DELIVERED:
        return True
    order = {name: index for index, name in enumerate(SEVERITIES)}
    return order.get(event.severity, 0) >= order.get(level, 1)

"""Turns an alert event into a message in the recipient's language."""

from datetime import datetime
from zoneinfo import ZoneInfo

from mbp.bots.texts import digits, format_duration, format_size, format_time, t
from mbp.notifications.events import Event

SEVERITY_ICONS = {"info": "ℹ️", "warning": "⚠️", "error": "🚨"}


def _time(value: str | None, lang: str, zone: ZoneInfo) -> str:
    return format_time(datetime.fromisoformat(value) if value else None, lang, zone)


def _result(lang: str, code: str | None) -> str:
    if not code:
        return ""
    text = t(lang, f"result_{code}")
    return code if text == f"result_{code}" else text


def render(event: Event, lang: str, zone: ZoneInfo) -> str:
    text = _render(event, lang, zone)
    # Alerts about another server than the panel's own name it first.
    server = event.params.get("server")
    return f"🖥 {server}: {text}" if server else text


def _render(event: Event, lang: str, zone: ZoneInfo) -> str:
    p = dict(event.params)
    kind = event.type
    if kind == "backup_succeeded":
        remote = t(lang, "event_remote_suffix") if p.get("remote") else ""
        return t(
            lang,
            "event_backup_succeeded",
            instance=p.get("instance", ""),
            db=p.get("db", ""),
            size=format_size(p.get("size"), lang),
            duration=format_duration(p.get("duration_ms"), lang),
            remote=remote,
        )
    if kind == "stale_backup":
        return t(
            lang,
            "event_stale_backup",
            instance=p.get("instance", ""),
            db=p.get("db", ""),
            hours=str(p.get("hours", "")),
            last=_time(p.get("last_success"), lang, zone),
        )
    if kind == "disk_low":
        return t(
            lang,
            "event_disk_low",
            percent=digits(f"{p.get('free_percent', 0):.1f}", lang),
            free=format_size(p.get("free"), lang),
            total=format_size(p.get("total"), lang),
            threshold=str(p.get("threshold", "")),
        )
    if kind == "container_down":
        oom = t(lang, "event_container_down_oom") if p.get("oom") else ""
        code = digits(str(p.get("exit_code", "")), lang)
        return t(lang, "event_container_down", name=p.get("name", ""), code=code, oom=oom)
    if kind == "container_restarting":
        return t(
            lang,
            "event_container_restarting",
            name=p.get("name", ""),
            n=digits(str(p.get("restarts", "")), lang),
            minutes=digits(str(p.get("minutes", "")), lang),
        )
    if kind == "container_unhealthy":
        return t(lang, "event_container_unhealthy", name=p.get("name", ""))
    if kind == "container_resources":
        parts = []
        if p.get("cpu") is not None:
            parts.append(t(lang, "event_usage_cpu", value=digits(f"{p['cpu']:.0f}", lang)))
        if p.get("memory_percent") is not None:
            parts.append(
                t(
                    lang,
                    "event_usage_memory",
                    value=digits(f"{p['memory_percent']:.0f}", lang),
                    used=format_size(p.get("memory_usage"), lang),
                    limit=format_size(p.get("memory_limit"), lang),
                )
            )
        usage = ("، " if lang == "fa" else ", ").join(parts)
        return t(lang, "event_container_resources", name=p.get("name", ""), usage=usage)
    if kind == "host_resources":
        return t(
            lang,
            f"event_host_{p.get('kind', 'memory')}",
            percent=digits(f"{p.get('percent', 0):.0f}", lang),
            used=format_size(p.get("used"), lang),
            total=format_size(p.get("total"), lang),
            threshold=digits(str(p.get("threshold", "")), lang),
        )
    if kind in ("deploy_succeeded", "deploy_failed"):
        detail = p.get("detail")
        return t(
            lang,
            f"event_{kind}",
            project=p.get("project", ""),
            commit=p.get("commit") or "",
            message=p.get("message") or "",
            actor=p.get("actor", ""),
            error=_result(lang, p.get("error")),
            detail=f" — {detail}" if detail else "",
        ).strip()
    if kind == "agent_unreachable":
        return t(lang, "event_agent_unreachable", code=p.get("code", ""))
    if kind == "recovered" and p.get("kind") in (
        "container_down",
        "container_restarting",
        "container_unhealthy",
        "container_resources",
        "host_memory",
        "host_disk",
        "agent",
    ):
        return t(
            lang,
            f"event_recovered_{p['kind']}",
            name=p.get("name", ""),
            percent=digits(f"{p.get('percent', 0):.0f}", lang),
        )
    if kind == "recovered":
        if p.get("kind") == "disk_low":
            return t(lang, "event_recovered_disk", free=format_size(p.get("free"), lang))
        return t(lang, "event_recovered_stale", instance=p.get("instance", ""), db=p.get("db", ""))
    if kind == "schedule_problem":
        return t(
            lang,
            "event_schedule_problem",
            name=p.get("name", ""),
            instance=p.get("instance", ""),
            result=t(lang, f"result_{p.get('result', 'error')}"),
        )
    if kind == "daily_summary":
        lines = [
            t(lang, "event_daily_summary"),
            t(lang, "summary_runs", ok=p.get("ok", 0), failed=p.get("failed", 0)),
        ]
        if p.get("failed_list"):
            lines.append(
                t(
                    lang,
                    "summary_failed_list",
                    names="، ".join(p["failed_list"])
                    if lang == "fa"
                    else ", ".join(p["failed_list"]),
                )
            )
        if p.get("remote_enabled"):
            lines.append(
                t(
                    lang,
                    "summary_uploads",
                    ok=p.get("uploaded", 0),
                    failed=p.get("upload_failed", 0),
                )
            )
        lines.append(t(lang, "summary_stale", n=p.get("stale", 0)))
        if p.get("disk_total"):
            lines.append(
                t(
                    lang,
                    "summary_disk",
                    free=format_size(p.get("disk_free"), lang),
                    total=format_size(p.get("disk_total"), lang),
                )
            )
        return "\n".join(lines)
    if kind == "test":
        return t(lang, "event_test")
    # backup_failed, upload_failed, retention_error
    return t(
        lang,
        f"event_{kind}",
        instance=p.get("instance", ""),
        db=p.get("db", ""),
        reason=p.get("reason", ""),
    )


def render_with_icon(event: Event, lang: str, zone: ZoneInfo) -> str:
    return f"{SEVERITY_ICONS.get(event.severity, '')} {render(event, lang, zone)}".strip()

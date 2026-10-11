"""Turns an alert event into a message in the recipient's language."""

from datetime import datetime
from zoneinfo import ZoneInfo

from mbp.bots.texts import digits, format_duration, format_size, format_time, t
from mbp.notifications.events import Event

SEVERITY_ICONS = {"info": "ℹ️", "warning": "⚠️", "error": "🚨"}


def _time(value: str | None, lang: str, zone: ZoneInfo) -> str:
    return format_time(datetime.fromisoformat(value) if value else None, lang, zone)


def render(event: Event, lang: str, zone: ZoneInfo) -> str:
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

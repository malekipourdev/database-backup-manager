from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from mbp.bots.texts import (
    TEXTS,
    format_duration,
    format_size,
    format_time,
    gregorian_to_jalali,
    t,
)
from mbp.notifications.events import EVENTS, Event
from mbp.notifications.render import render


def test_languages_have_the_same_keys():
    assert set(TEXTS["fa"]) == set(TEXTS["en"])
    assert all(TEXTS["fa"].values()) and all(TEXTS["en"].values())


@pytest.mark.parametrize(
    ("gregorian", "jalali"),
    [
        ((2026, 10, 11), (1405, 7, 19)),
        ((2025, 3, 21), (1404, 1, 1)),
        ((2024, 3, 20), (1403, 1, 1)),
        ((2024, 12, 31), (1403, 10, 11)),
        ((2000, 2, 29), (1378, 12, 10)),
    ],
)
def test_jalali(gregorian, jalali):
    assert gregorian_to_jalali(*gregorian) == jalali


def test_formatting():
    when = datetime(2026, 10, 11, 10, 30, tzinfo=UTC)
    assert format_time(when, "fa", ZoneInfo("Asia/Tehran")) == "۱۴۰۵/۰۷/۱۹ ۱۴:۰۰"
    assert format_time(when, "en", ZoneInfo("UTC")) == "2026-10-11 10:30"
    assert format_size(1536, "en") == "1.5 KB"
    assert format_size(5 * 1024**3, "fa") == "۵.۰ GB"
    assert format_duration(500, "en") == "< 1s"
    assert format_duration(3_725_000, "en") == "1h 2m"
    assert t("fa", "status_instances", n=12) == "🗄 پایگاه‌های داده: ۱۲"


@pytest.mark.parametrize("event", sorted(EVENTS) + ["test"])
@pytest.mark.parametrize("lang", ["fa", "en"])
def test_every_event_renders(event, lang):
    params = {
        "instance": "prod",
        "db": "shop",
        "reason": "boom",
        "size": 1024,
        "duration_ms": 2000,
        "remote": True,
        "hours": 26,
        "last_success": "2026-10-10T08:00:00+00:00",
        "free_percent": 4.2,
        "free": 10,
        "total": 100,
        "threshold": 10,
        "kind": "stale_backup",
        "name": "nightly",
        "result": "no_databases_selected",
        "ok": 3,
        "failed": 1,
        "failed_list": ["prod/shop"],
        "remote_enabled": True,
        "uploaded": 3,
        "upload_failed": 0,
        "stale": 0,
        "disk_free": 10,
        "disk_total": 100,
    }
    text = render(Event(event, "s", params), lang, ZoneInfo("UTC"))
    assert text and "{" not in text

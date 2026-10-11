from datetime import UTC, datetime

import pytest

from mbp.backups.naming import render, sanitize_segment, validate_pattern, validate_storage_dir

NOW = datetime(2026, 10, 11, 13, 8, 20, tzinfo=UTC)


@pytest.mark.parametrize(
    ("pattern", "error"),
    [
        ("{instance}/{database}_{date}_{time}", None),
        ("{database}_{datetime}", None),
        ("backups/{server_type}/{database}-{date}", None),
        ("{instance}_{date}", "missing_database"),
        ("{database}", "missing_datetime"),
        ("{database}_{date}_{foo}", "unknown_placeholder"),
        ("{database}_{date}_{", "unknown_placeholder"),
        ("/abs/{database}_{date}", "absolute_path"),
        ("../{database}_{date}", "parent_segment"),
        ("a//{database}_{date}", "empty_segment"),
        ("", "required"),
        ("{database}_{date}" + "x" * 250, "too_long"),
    ],
)
def test_validate_pattern(pattern, error):
    assert validate_pattern(pattern) == error


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ("", None),
        ("daily", None),
        ("team/a", None),
        ("/etc", "absolute_path"),
        ("a/../b", "parent_segment"),
        ("..", "parent_segment"),
        ("a//b", "empty_segment"),
        ("a/", "empty_segment"),
        ("a\\b", "invalid_character"),
    ],
)
def test_validate_storage_dir(value, error):
    assert validate_storage_dir(value) == error


def test_render_default_pattern_uses_utc_and_extension():
    path = render(
        "{instance}/{database}_{date}_{time}",
        instance="prod",
        database="shop",
        server_type="mysql",
        now=NOW,
        compression="gzip",
    )
    assert str(path) == "prod/shop_2026-10-11_130820.sql.gz"


@pytest.mark.parametrize(("compression", "ext"), [("bzip2", ".sql.bz2"), ("none", ".sql")])
def test_render_extensions(compression, ext):
    path = render(
        "{database}_{datetime}",
        instance="i",
        database="d",
        server_type=None,
        now=NOW,
        compression=compression,
    )
    assert str(path) == f"d_2026-10-11_130820{ext}"


def test_slash_in_names_never_creates_directories():
    path = render(
        "{instance}/{database}_{date}",
        instance="a/../b",
        database="x/y",
        server_type="mysql",
        now=NOW,
        compression="none",
    )
    assert path.parts == ("a_.._b", "x_y_2026-10-11.sql")


def test_persian_names_kept():
    path = render(
        "{instance}/{database}_{date}",
        instance="سرور اصلی",
        database="فروشگاه",
        server_type="mysql",
        now=NOW,
        compression="gzip",
    )
    assert str(path) == "سرور_اصلی/فروشگاه_2026-10-11.sql.gz"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("a:b*c?", "a_b_c_"), (".hidden", "_hidden"), ("tab\there", "tab_here"), ("", "_")],
)
def test_sanitize_segment(raw, expected):
    assert sanitize_segment(raw) == expected


def test_sanitize_truncates_on_utf8_boundary():
    result = sanitize_segment("ب" * 100)  # 200 bytes
    assert len(result.encode("utf-8")) <= 120
    assert result == "ب" * 60

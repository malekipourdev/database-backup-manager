import pytest

from mbp.api.errors import ApiError
from mbp.services.mysql_probe import ListResult
from mbp.services.selection_service import build_listing, validate_selection

LIVE = ListResult(
    ok=True,
    names=["information_schema", "mysql", "performance_schema", "shop", "sys", "blog"],
)
DOWN = ListResult(ok=False, error_code="timeout")


def by_name(listing):
    return {entry.name: entry for entry in listing.databases}


def test_listing_flags_system_schemas():
    entries = by_name(build_listing([], LIVE))
    for name in ("information_schema", "performance_schema", "mysql", "sys"):
        assert entries[name].is_system
    assert not entries["shop"].is_system
    assert not entries["information_schema"].selectable
    assert not entries["performance_schema"].selectable
    assert not entries["sys"].selectable
    assert entries["mysql"].selectable


def test_listing_sorted_and_marks_selected():
    listing = build_listing(["shop"], LIVE)
    names = [e.name for e in listing.databases]
    assert names == sorted(names)
    assert by_name(listing)["shop"].selected
    assert not by_name(listing)["blog"].selected


def test_selected_but_absent_is_missing():
    entries = by_name(build_listing(["shop", "gone"], LIVE))
    assert entries["gone"].selected and entries["gone"].missing
    assert not entries["shop"].missing


def test_unreachable_lists_only_stored_selection():
    listing = build_listing(["shop", "gone"], DOWN)
    assert not listing.reachable
    assert listing.error_code == "timeout"
    assert [(e.name, e.selected, e.missing) for e in listing.databases] == [
        ("gone", True, False),
        ("shop", True, False),
    ]


@pytest.mark.parametrize("name", ["information_schema", "performance_schema", "sys"])
def test_non_selectable_rejected(name):
    with pytest.raises(ApiError) as info:
        validate_selection([name], [], LIVE)
    assert info.value.code == "not_selectable"


def test_mysql_schema_selectable():
    validate_selection(["mysql"], [], LIVE)


def test_unknown_database_rejected():
    with pytest.raises(ApiError) as info:
        validate_selection(["nope"], [], LIVE)
    assert info.value.code == "unknown_database"
    assert info.value.detail == "nope"


def test_missing_but_stored_is_accepted():
    validate_selection(["gone"], ["gone"], LIVE)


def test_unreachable_accepts_only_removals():
    validate_selection(["shop"], ["shop", "blog"], DOWN)
    validate_selection([], ["shop"], DOWN)
    with pytest.raises(ApiError):
        validate_selection(["shop", "new"], ["shop"], DOWN)

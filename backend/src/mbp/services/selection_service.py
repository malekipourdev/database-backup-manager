from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.api.schemas import DatabaseEntry, DatabaseList
from mbp.repositories.selection_repository import SelectionRepository
from mbp.servers import db_access
from mbp.services.instance_service import InstanceService, conn_params
from mbp.services.mysql_probe import ListResult

SYSTEM_SCHEMAS = frozenset({"information_schema", "performance_schema", "mysql", "sys"})
# `mysql` holds users and grants and may legitimately be backed up; the others are virtual.
NON_SELECTABLE = frozenset({"information_schema", "performance_schema", "sys"})


def build_listing(stored: list[str], live: ListResult) -> DatabaseList:
    """Merge the server's databases with the stored selection."""
    selected = set(stored)
    if not live.ok:
        # Presence on the server is unknown, so nothing is flagged as missing.
        entries = [_entry(name, selected=True, missing=False) for name in sorted(selected)]
        return DatabaseList(
            reachable=False,
            error_code=live.error_code,
            error_detail=live.error_detail,
            databases=entries,
        )
    on_server = set(live.names)
    entries = [
        _entry(name, selected=name in selected, missing=name not in on_server)
        for name in sorted(on_server | selected)
    ]
    return DatabaseList(reachable=True, databases=entries)


def _entry(name: str, *, selected: bool, missing: bool) -> DatabaseEntry:
    return DatabaseEntry(
        name=name,
        is_system=name in SYSTEM_SCHEMAS,
        selectable=name not in NON_SELECTABLE,
        selected=selected,
        missing=selected and missing,
    )


def validate_selection(names: list[str], stored: list[str], live: ListResult) -> None:
    for name in names:
        if name in NON_SELECTABLE:
            raise ApiError(
                422, "not_selectable", detail=name, fields={"databases": "not_selectable"}
            )
    # Unreachable server: only removals and already-selected names are accepted.
    allowed = set(stored) | (set(live.names) if live.ok else set())
    for name in names:
        if name not in allowed:
            raise ApiError(
                422, "unknown_database", detail=name, fields={"databases": "unknown_database"}
            )


class SelectionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.instances = InstanceService(db)
        self.repo = SelectionRepository(db)

    def _load(self, instance_id: int) -> tuple[list[str], ListResult]:
        instance = self.instances.get(instance_id)
        stored = self.repo.list_names(instance_id)
        params, server_id = conn_params(instance), instance.server_id
        self.db.commit()
        return stored, db_access.list_databases(server_id, params)

    def get_listing(self, instance_id: int) -> DatabaseList:
        stored, live = self._load(instance_id)
        return build_listing(stored, live)

    def save(self, instance_id: int, names: list[str]) -> DatabaseList:
        stored, live = self._load(instance_id)
        validate_selection(names, stored, live)
        self.instances.get(instance_id)  # may have been deleted meanwhile
        self.repo.replace(instance_id, sorted(names))
        self.db.commit()
        return build_listing(sorted(names), live)

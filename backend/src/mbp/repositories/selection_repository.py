from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mbp.models import DbSelection


class SelectionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_names(self, instance_id: int) -> list[str]:
        stmt = (
            select(DbSelection.database_name)
            .where(DbSelection.instance_id == instance_id)
            .order_by(DbSelection.database_name)
        )
        return list(self.db.scalars(stmt))

    def replace(self, instance_id: int, names: list[str]) -> None:
        """Replace the full set of selected names; caller commits the transaction."""
        self.db.execute(delete(DbSelection).where(DbSelection.instance_id == instance_id))
        self.db.add_all(DbSelection(instance_id=instance_id, database_name=n) for n in names)
        self.db.flush()

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mbp.models import DbInstance


class InstanceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_ordered_by_name(self, where=None) -> list[DbInstance]:
        stmt = select(DbInstance).order_by(func.lower(DbInstance.name), DbInstance.id)
        if where is not None:
            stmt = stmt.where(where)
        return list(self.db.scalars(stmt))

    def get(self, instance_id: int) -> DbInstance | None:
        return self.db.get(DbInstance, instance_id)

    def get_by_name_normalized(self, name_normalized: str) -> DbInstance | None:
        stmt = select(DbInstance).where(DbInstance.name_normalized == name_normalized)
        return self.db.scalars(stmt).first()

    def add(self, instance: DbInstance) -> DbInstance:
        self.db.add(instance)
        self.db.flush()
        return instance

    def delete(self, instance: DbInstance) -> None:
        self.db.delete(instance)

"""US2-6 / FR-019: runs interrupted by a restart are failed and temp files removed."""

from fastapi.testclient import TestClient

from mbp.db import utcnow
from mbp.models import BackupRun
from tests.conftest import BACKUP_ROOT


def test_startup_recovers_interrupted_runs(app, db):
    for status in ("queued", "running"):
        db.add(
            BackupRun(
                instance_name="prod",
                database_name=f"db_{status}",
                trigger="single",
                status=status,
                active_key=f"0:db_{status}",
                requested_at=utcnow(),
                started_at=utcnow() if status == "running" else None,
                bytes_processed=0,
            )
        )
    db.commit()
    (BACKUP_ROOT / "prod").mkdir(parents=True)
    partial = BACKUP_ROOT / "prod" / ".shop.sql.gz.1.mbp-partial"
    partial.write_bytes(b"half a dump")
    keep = BACKUP_ROOT / "prod" / "shop.sql.gz"
    keep.write_bytes(b"finished")

    with TestClient(app):
        pass

    db.expire_all()
    runs = db.query(BackupRun).all()
    assert {(r.status, r.error_code, r.active_key) for r in runs} == {
        ("failed", "interrupted", None)
    }
    assert all(r.error_message for r in runs)
    assert not partial.exists()
    assert keep.exists()

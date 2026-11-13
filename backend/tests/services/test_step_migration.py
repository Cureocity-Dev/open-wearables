"""Exercise the real migration under a non-UTC PostgreSQL session."""

from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.factories import DataPointSeriesFactory


def test_interval_migration_preserves_timezone(db: Session) -> None:
    path = Path(__file__).parents[2] / "migrations/versions/2026_11_13_1500-a39e12db7801_step_sample_end_time.py"
    spec = spec_from_file_location("step_migration", path)
    assert spec is not None
    assert spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = db.connection()
    migration.op = Operations(MigrationContext.configure(connection))
    sample = DataPointSeriesFactory()
    savepoint = connection.begin_nested()
    try:
        migration.downgrade()
        migration.upgrade()
        db.execute(text("SET LOCAL TIME ZONE 'Asia/Kolkata'"))
        expected = datetime(2026, 11, 13, 12, 10, tzinfo=timezone.utc)
        db.execute(
            text("UPDATE data_point_series SET end_at = :end WHERE id = :id"), {"end": expected, "id": sample.id}
        )
        actual = db.execute(text("SELECT end_at FROM data_point_series WHERE id = :id"), {"id": sample.id}).scalar_one()
        assert actual == expected
        migration.downgrade()
    finally:
        savepoint.rollback()

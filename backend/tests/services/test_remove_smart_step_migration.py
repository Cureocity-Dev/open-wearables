"""Verify the rollback migration without changing application tables."""

import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def test_remove_interval_end_preserves_samples_and_can_restore_column(engine: Engine) -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "migrations/versions/2026_11_16_1300-c8f21d4e9b70_remove_smart_step_end_time.py"
    )
    spec = importlib.util.spec_from_file_location("remove_smart_step_end_time", path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    schema = f"migration_test_{uuid4().hex}"
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(
                text(
                    "CREATE TABLE data_point_series ("
                    "id INTEGER PRIMARY KEY, value NUMERIC(10,3) NOT NULL, "
                    "recorded_at TIMESTAMPTZ NOT NULL, end_at TIMESTAMPTZ)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO data_point_series VALUES (1, 208, '2026-11-16 01:44:59+00', '2026-11-16 01:49:59+00')"
                )
            )
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                columns = {
                    column["name"] for column in inspect(connection).get_columns("data_point_series", schema=schema)
                }
                assert columns == {"id", "value", "recorded_at"}
                assert connection.execute(text("SELECT id, value FROM data_point_series")).one() == (1, 208)

                migration.downgrade()
                columns = {
                    column["name"]: column
                    for column in inspect(connection).get_columns("data_point_series", schema=schema)
                }
                assert columns["end_at"]["nullable"] is True
                assert connection.execute(text("SELECT end_at FROM data_point_series")).scalar_one() is None
                assert connection.execute(text("SELECT value FROM data_point_series")).scalar_one() == 208

                migration.upgrade()
                assert "end_at" not in {
                    column["name"] for column in inspect(connection).get_columns("data_point_series", schema=schema)
                }
        finally:
            transaction.rollback()

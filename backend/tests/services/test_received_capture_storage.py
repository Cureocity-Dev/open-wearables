"""PostgreSQL body persistence without S3 configuration."""

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete

from app.models.received_capture import ReceivedCapture
from app.repositories import received_capture_repository as repository_module
from app.repositories.received_capture_repository import received_capture_repository
from app.services import raw_payload_storage, received_data_service
from app.services.received_capture_storage import received_capture_storage


@pytest.fixture
def body_storage(session_factory: Any, monkeypatch: pytest.MonkeyPatch) -> Generator[Any, None, None]:
    monkeypatch.setattr(repository_module, "SessionLocal", session_factory)
    yield session_factory
    with session_factory.begin() as db:
        db.execute(delete(ReceivedCapture))


def test_immutable_parallel_insert(body_storage: Any) -> None:
    expires = datetime.now(UTC) + timedelta(hours=72)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: received_capture_repository.store("key", b"original", expires), range(20)))
    received_capture_repository.store("key", b"replacement", expires + timedelta(days=1))
    assert received_capture_repository.read("key") == b"original"
    with body_storage() as db:
        assert db.get(ReceivedCapture, "key").expires_at == expires


def test_expired_body_denied_and_cleanup_bounded(body_storage: Any) -> None:
    now = datetime.now(UTC)
    for key in ("expired1", "expired2", "expired3"):
        received_capture_repository.store(key, b"old", now - timedelta(seconds=1))
    received_capture_repository.store("live", b"live", now + timedelta(hours=1))
    with pytest.raises(FileNotFoundError):
        received_capture_repository.read("expired1")
    assert received_capture_repository.cleanup(batch_size=2) == 2
    assert received_capture_repository.cleanup(batch_size=2) == 1
    assert received_capture_repository.cleanup(batch_size=2) == 0
    assert received_capture_repository.read("live") == b"live"


def test_cleanup_skips_rows_locked_by_other_worker(body_storage: Any) -> None:
    now = datetime.now(UTC)
    received_capture_repository.store("locked", b"old", now - timedelta(seconds=1))
    received_capture_repository.store("free", b"old", now - timedelta(seconds=1))
    with body_storage.begin() as db:
        db.get(ReceivedCapture, "locked", with_for_update=True)
        assert received_capture_repository.cleanup(batch_size=10) == 1
    assert received_capture_repository.cleanup(batch_size=10) == 1


def test_default_storage_does_not_require_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(raw_payload_storage, "_storage_backend", "disabled")
    storage, bucket = received_data_service._storage()
    assert storage is received_capture_storage
    assert bucket == "postgresql"


def test_database_capture_failure_does_not_fail_ingestion(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(**kwargs: Any) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(received_capture_storage, "put_object", fail)
    received_data_service.capture(user_id="owner", run_id="run", payload=[1], kind="sdk_batch")
    assert received_data_service.list_artifacts("owner", "run")["capture_status"] == "partial"


def test_capture_preview_without_s3(body_storage: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(raw_payload_storage, "_storage_backend", "disabled")
    received_data_service.capture(user_id="owner", run_id="run", payload=[{"value": 1}], kind="sdk_batch")
    page = received_data_service.list_artifacts("owner", "run")
    assert page["capture_status"] == "available"
    artifact_id = page["artifacts"][0]["artifact_id"]
    assert received_data_service.preview("owner", "run", artifact_id)["preview"]["records"] == [{"value": 1}]


def test_database_failure_does_not_log_payload(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from sqlalchemy.exc import StatementError

    class BrokenSessions:
        def begin(self) -> Any:
            raise StatementError("rejected", "INSERT", {"body": "PRIVATE_HEALTH_MARKER"}, RuntimeError("offline"))

    monkeypatch.setattr(repository_module, "SessionLocal", BrokenSessions())
    received_data_service.capture(user_id="owner", run_id="run", payload=[1], kind="sdk_batch")
    assert "PRIVATE_HEALTH_MARKER" not in caplog.text
    assert "Received-data object write failed" in caplog.text


def test_cleanup_task_registered_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.celery.core import create_celery
    from app.integrations.celery.tasks.received_capture_cleanup_task import cleanup_received_captures

    calls = []

    def cleanup(*, batch_size: int) -> int:
        calls.append(batch_size)
        return batch_size

    monkeypatch.setattr(received_capture_repository, "cleanup", cleanup)
    assert cleanup_received_captures.run() == 10000
    assert calls == [100] * 100
    app = create_celery()
    assert app.conf.beat_schedule["cleanup-received-captures"]["schedule"] == 3600.0

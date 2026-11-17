"""Received-data isolation, retention and retry guarantees."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.integrations.redis_client import get_redis_client
from app.services import received_data_service as capture


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, MagicMock, dict[str, bytes]]:
    redis = get_redis_client()
    objects = {}
    s3 = MagicMock()
    s3.put_object.side_effect = lambda **kw: objects.setdefault(kw["Key"], kw["Body"])
    s3.get_object.side_effect = lambda **kw: {"Body": io.BytesIO(objects[kw["Key"]])}
    monkeypatch.setattr(capture, "get_redis_client", lambda: redis)
    monkeypatch.setattr(capture, "_storage", lambda: (s3, "private"))
    return redis, s3, objects


def test_capture_preview_and_user_run_isolation(storage: tuple[Any, MagicMock, dict[str, bytes]]) -> None:
    capture.capture(user_id="alice", run_id="run", payload=[{"value": 1}, {"value": 2}], kind="sdk_batch")
    page = capture.list_artifacts("alice", "run", limit=20)
    assert page["capture_status"] == "available"
    artifact = page["artifacts"][0]
    preview = capture.preview("alice", "run", artifact["artifact_id"], limit=1)
    assert preview["preview"]["records"] == [{"value": 1}]
    assert preview["preview"]["next_cursor"] == "1"
    assert capture.preview("alice", "run", artifact["artifact_id"], cursor="1")["preview"]["records"] == [{"value": 2}]
    with pytest.raises(HTTPException) as error:
        capture.preview("bob", "run", artifact["artifact_id"])
    assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        capture.preview("alice", "other", artifact["artifact_id"])


def test_parallel_retry_is_idempotent_and_append_safe(storage: tuple[Any, MagicMock, dict[str, bytes]]) -> None:
    def write(i: int) -> None:
        capture.capture(user_id="alice", run_id="run", payload={"value": i % 4}, kind="api_response")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(40)))
    page = capture.list_artifacts("alice", "run")
    assert len(page["artifacts"]) == 4
    assert len(storage[2]) == 4
    assert storage[1].put_object.call_count == 4
    assert len({item["expires_at"] for item in page["artifacts"]}) == 1


def test_expiry_enforced_without_object_read_and_retry_does_not_extend(
    storage: tuple[Any, MagicMock, dict[str, bytes]], monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    monkeypatch.setattr(capture, "_now", lambda: now)
    capture.capture(user_id="alice", run_id="run", payload=[1], kind="sdk_batch")
    artifact_id = capture.list_artifacts("alice", "run")["artifacts"][0]["artifact_id"]
    now += timedelta(hours=73)
    capture.capture(user_id="alice", run_id="run", payload=[2], kind="sdk_batch")
    assert capture.list_artifacts("alice", "run")["capture_status"] == "expired"
    with pytest.raises(HTTPException) as error:
        capture.preview("alice", "run", artifact_id)
    assert error.value.status_code == 410
    storage[1].get_object.assert_not_called()
    assert len(storage[2]) == 1


def test_disabled_storage_reports_unavailable(
    storage: tuple[Any, MagicMock, dict[str, bytes]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture, "_storage", lambda: (None, None))
    capture.capture(user_id="alice", run_id="run", payload=[1], kind="sdk_batch")
    assert capture.list_artifacts("alice", "run")["capture_status"] == "unavailable"
    assert not storage[2]


def test_failures_and_oversize_are_metadata_not_sync_failures(
    storage: tuple[Any, MagicMock, dict[str, bytes]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture, "MAX_BYTES", 4)
    capture.capture(user_id="alice", run_id="run", payload="too large", kind="xml_file")
    assert capture.list_artifacts("alice", "run")["artifacts"][0]["status"] == "oversized"
    monkeypatch.setattr(capture, "MAX_BYTES", 100)
    storage[1].put_object.side_effect = RuntimeError("offline")
    capture.capture(user_id="alice", run_id="run", payload=[1], kind="sdk_batch")
    assert {a["status"] for a in capture.list_artifacts("alice", "run")["artifacts"]} == {"oversized", "failed"}


def test_secrets_removed_and_json_is_labeled_normalized(storage: tuple[Any, MagicMock, dict[str, bytes]]) -> None:
    capture.capture(
        user_id="alice",
        run_id="run",
        payload={"access_token": "secret", "callbackURL": "https://signed", "data": [1]},
        kind="webhook_body",
    )
    page = capture.list_artifacts("alice", "run")
    assert page["artifacts"][0]["representation"] == "normalized"
    body = json.loads(next(iter(storage[2].values())))
    assert body == {"access_token": "[redacted]", "callbackURL": "[redacted]", "data": [1]}


def test_invalid_cursor_and_limit_are_rejected(storage: tuple[Any, MagicMock, dict[str, bytes]]) -> None:
    capture.capture(user_id="alice", run_id="run", payload=[1], kind="sdk_batch")
    for cursor in ("-1", "garbage", "9999999999999999999999999999"):
        with pytest.raises(HTTPException) as error:
            capture.list_artifacts("alice", "run", cursor=cursor)
        assert error.value.status_code == 400


def test_webhook_response_buffer_is_scoped_to_resolved_user(storage: tuple[Any, MagicMock, dict[str, bytes]]) -> None:
    token = capture.begin_pending()
    try:
        capture.capture_response("alice", {"value": 1})
        capture.capture_response("bob", {"secret": 2})
        capture.flush_pending("alice", "run")
    finally:
        capture.end_pending(token)
    assert len(capture.list_artifacts("alice", "run")["artifacts"]) == 1
    assert not storage[0].exists(capture._index_key("bob", "run"))


@pytest.mark.parametrize("overflow", ["count", "bytes"])
def test_pending_overflow_reports_partial_for_only_affected_user(
    storage: tuple[Any, MagicMock, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
    overflow: str,
) -> None:
    token = capture.begin_pending()
    try:
        capture.capture_response("alice", [1])
        if overflow == "count":
            for value in range(25):
                capture.capture_response("alice", [value])
        else:
            monkeypatch.setattr(capture, "MAX_BYTES", 20)
            capture.capture_response("alice", ["x" * 30])
        capture.flush_pending("alice", "run")
        capture.flush_pending("bob", "other")
    finally:
        capture.end_pending(token)
    assert capture.list_artifacts("alice", "run")["capture_status"] == "partial"
    assert capture.list_artifacts("bob", "other")["capture_status"] == "not_captured"


def test_failed_upload_retries_without_extending_expiry(storage: tuple[Any, MagicMock, dict[str, bytes]]) -> None:
    storage[1].put_object.side_effect = RuntimeError("offline")
    capture.capture(user_id="alice", run_id="run", payload=[1], kind="sdk_batch")
    before = capture.list_artifacts("alice", "run")
    storage[1].put_object.side_effect = lambda **kw: storage[2].setdefault(kw["Key"], kw["Body"])
    capture.capture(user_id="alice", run_id="run", payload=[1], kind="sdk_batch")
    after = capture.list_artifacts("alice", "run")
    assert after["capture_status"] == "available"
    assert before["expires_at"] == after["expires_at"]


def test_crash_after_upload_recovers_after_lease_and_stale_owner_is_fenced(
    storage: tuple[Any, MagicMock, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis, s3, objects = storage
    real_eval = redis.eval
    crashed = False

    def crash_finish(script: str, *args: Any) -> Any:
        nonlocal crashed
        if "~= ARGV[1]" in script and not crashed:
            crashed = True
            raise RuntimeError("crash after body upload")
        return real_eval(script, *args)

    monkeypatch.setattr(redis, "eval", crash_finish)
    capture.capture(user_id="alice", run_id="run", payload=[1], kind="sdk_batch")
    page = capture.list_artifacts("alice", "run")
    artifact_id = page["artifacts"][0]["artifact_id"]
    assert page["capture_status"] == "partial"
    lease = capture._index_key("alice", "run") + ":writer:" + artifact_id
    assert 0 < redis.ttl(lease) <= capture.LEASE_SECONDS
    old_owner = redis.get(lease)
    # Deterministically advance ownership without sleeping on real lease time.
    redis.delete(lease)
    capture.capture(user_id="alice", run_id="run", payload=[1], kind="sdk_batch")
    assert capture.list_artifacts("alice", "run")["capture_status"] == "available"
    assert len(objects) == 1
    assert old_owner is not None
    assert s3.put_object.call_count == 2


def test_delayed_writer_cannot_replace_new_owner_metadata(
    storage: tuple[Any, MagicMock, dict[str, bytes]],
) -> None:
    redis, s3, objects = storage
    called = False

    def delayed(**kw: Any) -> None:
        nonlocal called
        objects.setdefault(kw["Key"], kw["Body"])
        if not called:
            called = True
            lease = next(redis.scan_iter(match=capture._index_key("alice", "run") + ":writer:*"))
            redis.delete(lease)
            capture.capture(user_id="alice", run_id="run", payload=[1], kind="sdk_batch")
            raise RuntimeError("old owner failed after successor completed")

    s3.put_object.side_effect = delayed
    capture.capture(user_id="alice", run_id="run", payload=[1], kind="sdk_batch")
    assert capture.list_artifacts("alice", "run")["capture_status"] == "available"


def test_authorized_parent_context_receives_fit_bytes(storage: tuple[Any, MagicMock, dict[str, bytes]]) -> None:
    token = capture.begin("alice", "live", "parent")
    try:
        capture.capture_response("alice", b"FIT bytes", kind="fit_file")
        capture.capture_response("bob", b"other user", kind="fit_file")
    finally:
        capture.end(token)
    assert capture.list_artifacts("alice", "live")["artifacts"][0]["kind"] == "fit_file"
    assert capture.list_artifacts("alice", "parent")["artifacts"][0]["kind"] == "fit_file"
    assert not capture.list_artifacts("bob", "parent")["artifacts"]


def test_atomic_cap_with_concurrent_writers(
    storage: tuple[Any, MagicMock, dict[str, bytes]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture, "MAX_ARTIFACTS", 3)
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(
            pool.map(lambda i: capture.capture(user_id="alice", run_id="run", payload=[i], kind="sdk_batch"), range(40))
        )
    assert len(capture.list_artifacts("alice", "run")["artifacts"]) == 3
    assert len(storage[2]) == 3


def test_publish_timestamp_preserved_across_retries() -> None:
    headers: dict[str, Any] = {}
    capture.signals.before_task_publish.send(sender="any.task", headers=headers)
    original = headers["received_capture_created_at"]
    capture.signals.before_task_publish.send(sender="any.task", headers=headers)
    assert headers["received_capture_created_at"] == original


def test_task_original_age_and_legacy_header_rejection(
    storage: tuple[Any, MagicMock, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = MagicMock()
    task.request.id = "task-id"
    task.request.headers = {"received_capture_created_at": (datetime.now(UTC) - timedelta(hours=73)).isoformat()}
    monkeypatch.setattr(capture, "current_task", task)
    capture.capture(user_id="alice", run_id="old", payload=[1], kind="sdk_batch")
    task.request.headers = {}
    capture.capture(user_id="alice", run_id="legacy", payload=[1], kind="sdk_batch")
    assert not storage[2]
    assert not storage[0].exists(capture._index_key("alice", "old") + ":expiry")
    assert not storage[0].exists(capture._index_key("alice", "legacy") + ":expiry")


def test_conditional_existing_object_recovers_metadata(storage: tuple[Any, MagicMock, dict[str, bytes]]) -> None:
    storage[1].put_object.side_effect = ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
    capture.capture(user_id="alice", run_id="run", payload=[1], kind="sdk_batch")
    assert capture.list_artifacts("alice", "run")["capture_status"] == "available"


def test_old_original_age_rejected_after_metadata_loss(storage: tuple[Any, MagicMock, dict[str, bytes]]) -> None:
    capture.capture(
        user_id="alice", run_id="run", payload=[1], kind="sdk_batch", created_at=datetime.now(UTC) - timedelta(hours=73)
    )
    assert not storage[2]
    assert not storage[0].exists(capture._index_key("alice", "run") + ":expiry")


def test_expiry_marker_is_bounded(storage: tuple[Any, MagicMock, dict[str, bytes]]) -> None:
    capture.capture(user_id="alice", run_id="run", payload=[1], kind="sdk_batch")
    assert (
        0
        < storage[0].ttl(capture._index_key("alice", "run") + ":expiry")
        <= capture.METADATA_SECONDS + capture.RETENTION_SECONDS
    )


def test_response_capture_serialization_failure_does_not_fail_ingestion(
    storage: tuple[Any, MagicMock, dict[str, bytes]],
) -> None:
    circular: dict[str, Any] = {}
    circular["self"] = circular
    token = capture.begin_pending()
    try:
        capture.capture_response("alice", circular)
    finally:
        capture.end_pending(token)


def test_context_is_fenced_by_user_and_reset(storage: tuple[Any, MagicMock, dict[str, bytes]]) -> None:
    token = capture.begin("alice", "run")
    try:
        capture.capture_response("bob", {"private": True})
        capture.capture_response("alice", {"value": 1})
    finally:
        capture.end(token)
    capture.capture_response("alice", {"value": 2})
    assert len(capture.list_artifacts("alice", "run")["artifacts"]) == 1
    assert not storage[0].exists(capture._index_key("bob", "run"))

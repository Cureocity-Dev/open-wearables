"""Tests for the sync status service.

Verifies persistence (Redis history & runs), terminal-event Svix
dispatch, and the SSE replay/streaming generator.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

import app.services.sync_status_service as sync_status_service
from app.integrations.redis_client import get_redis_client
from app.schemas.sync_status import SyncSource, SyncStage, SyncStatus, SyncStatusEvent


@pytest.fixture
def user_id() -> str:
    return str(uuid4())


def _build_event(
    user_id: str,
    *,
    stage: SyncStage = SyncStage.STARTED,
    status: SyncStatus = SyncStatus.IN_PROGRESS,
    run_id: str | None = None,
) -> SyncStatusEvent:
    return SyncStatusEvent(
        run_id=run_id or sync_status_service.new_run_id(),
        user_id=user_id,
        provider="garmin",
        source=SyncSource.PULL,
        stage=stage,
        status=status,
    )


class TestEmitAndPersist:
    def test_emit_persists_event_in_recent_list(self, user_id: str) -> None:
        event = _build_event(user_id)
        sync_status_service.emit(event)

        recent = sync_status_service.get_recent_events(user_id)
        assert len(recent) == 1
        assert recent[0].run_id == event.run_id
        assert recent[0].user_id == event.user_id

    def test_get_recent_events_returns_newest_first(self, user_id: str) -> None:
        first = _build_event(user_id)
        second = _build_event(user_id)
        sync_status_service.emit(first)
        time.sleep(0.005)
        sync_status_service.emit(second)

        recent = sync_status_service.get_recent_events(user_id, limit=10)
        assert [e.run_id for e in recent] == [second.run_id, first.run_id]

    def test_recent_list_is_capped(self, user_id: str) -> None:
        with patch.object(sync_status_service, "MAX_RECENT_EVENTS", 5):
            for _ in range(8):
                sync_status_service.emit(_build_event(user_id))
            recent = sync_status_service.get_recent_events(user_id, limit=20)
            assert len(recent) == 5

    def test_run_summaries_aggregate_per_run(self, user_id: str) -> None:
        run_id = sync_status_service.new_run_id()
        sync_status_service.emit(_build_event(user_id, run_id=run_id, stage=SyncStage.STARTED))
        sync_status_service.emit(
            _build_event(user_id, run_id=run_id, stage=SyncStage.PROCESSING),
        )
        sync_status_service.completed(
            user_id,
            "garmin",
            SyncSource.PULL,
            run_id=run_id,
            status=SyncStatus.SUCCESS,
            items_processed=7,
        )

        summaries = sync_status_service.get_run_summaries(user_id)
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.run_id == run_id
        assert summary.stage == SyncStage.COMPLETED.value
        assert summary.status == SyncStatus.SUCCESS.value
        assert summary.items_processed == 7


class TestRunSummaryBatching:
    def test_admin_batches_reads_across_users_and_bounds_pipeline_size(self) -> None:
        client = get_redis_client()
        user_ids = [str(uuid4()) for _ in range(3)]
        events = []
        for uid in user_ids:
            for _ in range(3):
                event = _build_event(uid)
                events.append(event)
                client.sadd(sync_status_service._user_runs_key(uid), event.run_id)
                client.set(sync_status_service._run_key(event.run_id), event.model_dump_json())
        command_counts = []
        original_pipeline = client.pipeline

        def tracked_pipeline(*args: object, **kwargs: object) -> object:
            pipe = original_pipeline(*args, **kwargs)
            original_execute = pipe.execute

            def execute() -> list[object]:
                command_counts.append(len(pipe.command_stack))
                return original_execute()

            pipe.execute = MagicMock(side_effect=execute)
            return pipe

        with (
            patch.object(sync_status_service, "SUMMARY_READ_BATCH_SIZE", 2, create=True),
            patch.object(client, "scan", return_value=(0, [sync_status_service._user_runs_key(u) for u in user_ids])),
            patch.object(client, "pipeline", side_effect=tracked_pipeline),
            patch.object(client, "smembers", wraps=client.smembers) as smembers,
            patch.object(client, "lrange", wraps=client.lrange) as lrange,
        ):
            summaries = sync_status_service.get_all_run_summaries()

        assert {s.run_id for s in summaries} == {e.run_id for e in events}
        assert len(command_counts) == 7  # Two user batches and five latest-event batches.
        assert max(command_counts) <= 4  # Two metadata commands per user.
        smembers.assert_not_called()
        lrange.assert_not_called()

    def test_admin_keeps_per_user_limit_before_filters(self) -> None:
        client = get_redis_client()
        uid = str(uuid4())
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for index in range(3):
            event = _build_event(uid).model_copy(
                update={
                    "timestamp": start + timedelta(seconds=index),
                    "provider": "fitbit" if index == 0 else "garmin",
                }
            )
            client.sadd(sync_status_service._user_runs_key(uid), event.run_id)
            client.set(sync_status_service._run_key(event.run_id), event.model_dump_json())

        with patch.object(sync_status_service, "MAX_RECENT_EVENTS", 2):
            assert sync_status_service.get_all_run_summaries(user_id_filter=uid, provider_filter="fitbit") == []
            summaries = sync_status_service.get_all_run_summaries(user_id_filter=uid)
        assert len(summaries) == 2
        assert [s.last_update for s in summaries] == [start + timedelta(seconds=2), start + timedelta(seconds=1)]
        assert len(sync_status_service.get_run_summaries(uid)) == 3

    def test_filters_order_recovery_and_invalid_or_expired_events(self) -> None:
        client = get_redis_client()
        uid = str(uuid4())
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        first = _build_event(uid).model_copy(update={"started_at": start})
        newer_start = first.model_copy(update={"started_at": start + timedelta(seconds=1)})
        terminal = first.model_copy(
            update={
                "started_at": None,
                "ended_at": start + timedelta(seconds=10),
                "timestamp": start + timedelta(seconds=10),
                "stage": SyncStage.COMPLETED,
                "status": SyncStatus.SUCCESS,
                "items_processed": 7,
                "message": "Saved",
            }
        )
        other = _build_event(uid).model_copy(update={"timestamp": start + timedelta(seconds=20)})
        for event in (terminal, other):
            client.sadd(sync_status_service._user_runs_key(uid), event.run_id)
            client.set(sync_status_service._run_key(event.run_id), event.model_dump_json())
        client.sadd(sync_status_service._user_runs_key(uid), "expired", "invalid")
        client.set(sync_status_service._run_key("invalid"), "not-json")
        client.rpush(
            sync_status_service._user_recent_key(uid),
            "not-json",
            newer_start.model_dump_json(),
            first.model_dump_json(),
        )

        summaries = sync_status_service.get_run_summaries(uid, limit=1)
        assert [s.run_id for s in summaries] == [other.run_id]
        with patch.object(client, "scan") as scan:
            summaries = sync_status_service.get_all_run_summaries(
                limit=1, user_id_filter=uid, provider_filter="garmin", status_filter="success", source_filter="pull"
            )
        scan.assert_not_called()
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.run_id == terminal.run_id
        assert summary.started_at == newer_start.started_at
        assert summary.ended_at == terminal.ended_at
        assert summary.items_processed == 7
        assert summary.message == "Saved"
        assert sync_status_service.get_all_run_summaries(user_id_filter=uid, provider_filter="fitbit") == []
        assert sync_status_service.get_run_summaries(str(uuid4())) == []


class TestTerminalSvixDispatch:
    @pytest.fixture
    def mock_outgoing(self) -> Generator[dict[str, object], None, None]:
        with (
            patch("app.services.outgoing_webhooks.events.on_sync_started") as started,
            patch("app.services.outgoing_webhooks.events.on_sync_completed") as completed,
            patch("app.services.outgoing_webhooks.events.on_sync_failed") as failed,
        ):
            yield {"started": started, "completed": completed, "failed": failed}

    def test_started_dispatches_outgoing_started(
        self,
        user_id: str,
        mock_outgoing: dict[str, object],
    ) -> None:
        sync_status_service.started(user_id, "garmin", SyncSource.PULL, run_id="run_a")
        mock_outgoing["started"].assert_called_once()

    def test_completed_dispatches_outgoing_completed(
        self,
        user_id: str,
        mock_outgoing: dict[str, object],
    ) -> None:
        sync_status_service.completed(user_id, "garmin", SyncSource.PULL, run_id="run_b")
        mock_outgoing["completed"].assert_called_once()

    def test_failed_dispatches_outgoing_failed(
        self,
        user_id: str,
        mock_outgoing: dict[str, object],
    ) -> None:
        event = sync_status_service.failed(
            user_id,
            "garmin",
            SyncSource.PULL,
            run_id="run_c",
            error="boom",
            items_processed=2,
        )
        assert event.items_processed == 2
        mock_outgoing["failed"].assert_called_once()

    def test_progress_does_not_fire_outgoing_webhook(
        self,
        user_id: str,
        mock_outgoing: dict[str, object],
    ) -> None:
        sync_status_service.progress(user_id, "garmin", SyncSource.PULL, run_id="run_d")
        for mock in mock_outgoing.values():
            mock.assert_not_called()


class TestStreamUserEvents:
    def test_stream_replays_recent_events(self, user_id: str) -> None:
        sync_status_service.emit(_build_event(user_id))
        sync_status_service.emit(_build_event(user_id))

        gen = sync_status_service.stream_user_events(user_id, replay_last=2)
        chunks: list[str] = []
        # First chunk is the connect comment, then two replayed events
        for _ in range(3):
            chunks.append(next(gen))

        assert chunks[0].startswith(":")  # connected comment
        assert "event: sync.status" in chunks[1]
        assert "event: sync.status" in chunks[2]

    def test_stream_forwards_published_events(self, user_id: str) -> None:
        stop = threading.Event()
        gen = sync_status_service.stream_user_events(user_id, replay_last=0, stop_event=stop)
        # Drain initial connect comment
        next(gen)

        # Publish from another "process"
        run_id = sync_status_service.new_run_id()
        sync_status_service.emit(_build_event(user_id, run_id=run_id))

        chunk: str | None = None
        deadline = time.time() + 3.0
        while time.time() < deadline:
            value = next(gen)
            if "event: sync.status" in value:
                chunk = value
                break
        stop.set()

        assert chunk is not None
        # The data line carries JSON
        data_lines = [line[len("data: ") :] for line in chunk.splitlines() if line.startswith("data: ")]
        assert data_lines
        decoded = json.loads(data_lines[0])
        assert decoded["run_id"] == run_id


class TestEmitResilientToRedisFailure:
    def test_emit_swallows_redis_errors(self, user_id: str) -> None:
        with patch.object(sync_status_service, "get_redis_client") as mock:
            mock.side_effect = RuntimeError("redis down")
            # Should not raise
            sync_status_service.emit(_build_event(user_id))


class TestRedisHistoryTtl:
    def test_keys_have_expiry_set(self, user_id: str) -> None:
        sync_status_service.emit(_build_event(user_id))
        client = get_redis_client()
        ttl = client.ttl(f"sync:status:user:{user_id}:recent")
        assert ttl is not None
        assert int(ttl) > 0

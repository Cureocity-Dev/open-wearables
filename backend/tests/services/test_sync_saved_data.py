"""Saved sync data is bounded and scoped to the run owner and provider."""

import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import DataPointSeries, DataSource, EventRecord, UserConnection
from app.schemas.auth import ConnectionStatus
from app.services import sync_status_service
from app.services.sync_saved_data_service import get_saved_data
from tests.factories import UserFactory


def test_saved_data_empty_and_unknown_run(db: Session) -> None:
    user = UserFactory()
    with pytest.raises(HTTPException) as error:
        get_saved_data(db, user.id, "unknown", limit=10)
    assert error.value.status_code == 404
    sync_status_service.started(user_id=user.id, provider="apple", source="sdk", run_id="run")
    result = get_saved_data(db, user.id, "run", limit=10)
    assert result["records"] == []
    assert result["scope"] == "user_provider"
    assert result["next_cursor"] is None


def test_saved_data_owner_provider_and_pagination(db: Session) -> None:
    user = UserFactory()
    other = UserFactory()
    now = datetime.now(UTC)
    for owner, provider, values in [(user, "apple", [1, 2, 3]), (other, "apple", [99]), (user, "samsung", [88])]:
        connection = UserConnection(
            id=uuid4(), user_id=owner.id, provider=provider, status=ConnectionStatus.ACTIVE, updated_at=now
        )
        db.add(connection)
        db.flush()
        source = DataSource(id=uuid4(), user_id=owner.id, provider=provider, user_connection_id=connection.id)
        db.add(source)
        db.flush()
        for value in values:
            db.add(
                DataPointSeries(
                    id=uuid4(),
                    data_source_id=source.id,
                    recorded_at=now + timedelta(seconds=value),
                    value=value,
                    series_type_definition_id=1,
                )
            )
    db.flush()
    sync_status_service.started(user_id=user.id, provider="apple", source="sdk", run_id="run")
    first = get_saved_data(db, user.id, "run", limit=2)
    assert len(first["records"]) == 2
    assert first["next_cursor"]
    second = get_saved_data(db, user.id, "run", limit=2, cursor=first["next_cursor"])
    assert len(second["records"]) == 1
    assert {float(item["value"]) for item in first["records"] + second["records"]} == {1, 2, 3}
    with pytest.raises(HTTPException) as error:
        get_saved_data(db, other.id, "run", limit=2)
    assert error.value.status_code == 404


def test_saved_data_pages_across_measurements_and_events(db: Session) -> None:
    user = UserFactory()
    now = datetime.now(UTC)
    connection = UserConnection(
        id=uuid4(), user_id=user.id, provider="apple", status=ConnectionStatus.ACTIVE, updated_at=now
    )
    db.add(connection)
    db.flush()
    source = DataSource(id=uuid4(), user_id=user.id, provider="apple", user_connection_id=connection.id)
    db.add(source)
    db.flush()
    point_id, event_id = uuid4(), uuid4()
    db.add(
        DataPointSeries(id=point_id, data_source_id=source.id, recorded_at=now, value=1, series_type_definition_id=1)
    )
    db.add(
        EventRecord(
            id=event_id,
            data_source_id=source.id,
            category="sleep",
            source_name="apple",
            start_datetime=now,
            end_datetime=now + timedelta(hours=1),
            duration_seconds=3600,
        )
    )
    db.flush()
    sync_status_service.started(user_id=user.id, provider="apple", source="sdk", run_id="run")
    first = get_saved_data(db, user.id, "run", limit=1)
    assert first["records"][0]["id"] == str(point_id)
    second = get_saved_data(db, user.id, "run", limit=1, cursor=first["next_cursor"])
    assert second["records"][0]["id"] == str(event_id)
    assert second["records"][0]["category"] == "sleep"
    assert second["next_cursor"] is None


def test_saved_data_invalid_cursor(db: Session) -> None:
    user = UserFactory()
    sync_status_service.started(user_id=user.id, provider="apple", source="sdk", run_id="run")
    cursors = ["invalid"] + [
        base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
        for value in (["measurement", 1], ["event", True], ["event", {}], {"kind": "event"}, ["unknown", str(uuid4())])
    ]
    for cursor in cursors:
        with pytest.raises(HTTPException) as error:
            get_saved_data(db, user.id, "run", limit=10, cursor=cursor)
        assert error.value.status_code == 400

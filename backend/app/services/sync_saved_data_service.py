"""Expose existing normalized data without claiming exact run provenance."""

import base64
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.integrations.redis_client import get_redis_client
from app.repositories.sync_saved_data_repository import read_saved_records
from app.schemas.sync_status import SyncStatusEvent


def get_saved_data(
    db: Session, user_id: UUID, run_id: str, *, limit: int = 100, cursor: str | None = None
) -> dict[str, Any]:
    raw = get_redis_client().get(f"sync:status:run:{run_id}")
    if raw is None:
        raise HTTPException(404, "Sync run not found")
    event = SyncStatusEvent.model_validate_json(raw)
    if str(event.user_id) != str(user_id):
        raise HTTPException(404, "Sync run not found")
    after = None
    if cursor:
        try:
            if len(cursor) > 200:
                raise ValueError("Cursor too long")
            decoded = json.loads(base64.urlsafe_b64decode(cursor))
            if not isinstance(decoded, list) or len(decoded) != 2 or not all(isinstance(v, str) for v in decoded):
                raise ValueError("Invalid cursor structure")
            kind, value = decoded
            if kind not in ("measurement", "event"):
                raise ValueError("Unknown record type")
            after = kind, UUID(value)
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(400, "Invalid saved-data cursor") from None
    page_size = max(1, min(limit, 100))
    rows = read_saved_records(db, user_id, str(event.provider), limit=page_size + 1, after=after)
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = base64.urlsafe_b64encode(json.dumps([last["record_type"], str(last["id"])]).encode()).decode()
    return {
        "user_id": str(user_id),
        "run_id": run_id,
        "provider": event.provider,
        "scope": "user_provider",
        "records": jsonable_encoder(rows),
        "next_cursor": next_cursor,
    }

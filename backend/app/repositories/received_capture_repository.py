"""Independent, immutable body transactions for received sync captures."""

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models.received_capture import ReceivedCapture


class ReceivedCaptureRepository:
    def store(self, object_key: str, body: bytes, expires_at: datetime) -> None:
        with SessionLocal.begin() as db:
            db.execute(
                insert(ReceivedCapture)
                .values(object_key=object_key, body=body, expires_at=expires_at)
                .on_conflict_do_nothing(index_elements=[ReceivedCapture.object_key])
            )

    def read(self, object_key: str) -> bytes:
        with SessionLocal() as db:
            body = db.scalar(
                select(ReceivedCapture.body).where(
                    ReceivedCapture.object_key == object_key,
                    ReceivedCapture.expires_at > datetime.now(UTC),
                )
            )
            if body is None:
                raise FileNotFoundError("Capture body missing or expired")
            return body

    def cleanup(self, *, batch_size: int = 100) -> int:
        with SessionLocal.begin() as db:
            expired = (
                select(ReceivedCapture.object_key)
                .where(ReceivedCapture.expires_at <= datetime.now(UTC))
                .order_by(ReceivedCapture.expires_at, ReceivedCapture.object_key)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            result = db.execute(delete(ReceivedCapture).where(ReceivedCapture.object_key.in_(expired)))
            return result.rowcount


received_capture_repository = ReceivedCaptureRepository()

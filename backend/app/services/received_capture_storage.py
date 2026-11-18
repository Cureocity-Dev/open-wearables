"""PostgreSQL adapter for the capture service's internal object interface."""

from datetime import datetime
from io import BytesIO
from typing import Any

from app.repositories.received_capture_repository import received_capture_repository


class ReceivedCaptureStorage:
    def put_object(self, *, Key: str, Body: bytes, Expires: datetime, **kwargs: Any) -> None:  # noqa: N803
        try:
            received_capture_repository.store(Key, Body, Expires)
        except Exception:
            # Database exceptions can contain health data in bound parameters.
            pass
        else:
            return
        raise RuntimeError("Capture body write failed") from None

    def get_object(self, *, Key: str, **kwargs: Any) -> dict[str, BytesIO]:  # noqa: N803
        return {"Body": BytesIO(received_capture_repository.read(Key))}


received_capture_storage = ReceivedCaptureStorage()

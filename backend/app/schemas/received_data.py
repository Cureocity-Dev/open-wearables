"""Bounded received-data API contracts."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class ReceivedArtifact(BaseModel):
    artifact_id: str
    captured_at: datetime
    expires_at: datetime
    representation: Literal["original", "normalized"]
    kind: Literal["sdk_batch", "webhook_body", "api_response", "xml_file", "fit_file"]
    content_type: str
    size_bytes: int
    status: Literal["available", "oversized", "failed", "expired"]
    label: str


class ReceivedDataList(BaseModel):
    run_id: str
    user_id: str
    expires_at: datetime | None
    capture_status: Literal["available", "partial", "not_captured", "expired", "unavailable"]
    artifacts: list[ReceivedArtifact]
    next_cursor: str | None


class ReceivedPreview(BaseModel):
    format: Literal["json_records", "text", "binary"]
    records: list[Any] | None
    text: str | None
    truncated: bool
    next_cursor: str | None


class ReceivedArtifactPreview(BaseModel):
    artifact_id: str
    representation: Literal["original", "normalized"]
    content_type: str
    size_bytes: int
    preview: ReceivedPreview

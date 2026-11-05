from pydantic import BaseModel, Field


class UploadDataResponse(BaseModel):
    """Response schema for data upload/sync operations.

    Returned when health data is queued for asynchronous processing via Celery.
    The actual import happens in the background - this response indicates the task was queued successfully.
    """

    status_code: int = Field(..., description="HTTP status code (typically 202 for async operations)")
    response: str = Field(..., description="Human-readable response message")
    user_id: str | None = Field(None, description="User ID associated with the import operation")
    incoming_records: int | None = Field(None, ge=0, description="Time-series records received")
    incoming_workouts: int | None = Field(None, ge=0, description="Workout records received")
    incoming_sleep: int | None = Field(None, ge=0, description="Sleep stages received")
    records_saved: int | None = Field(None, ge=0, description="Time-series records written")
    workouts_saved: int | None = Field(None, ge=0, description="Workout records written")
    sleep_saved: int | None = Field(None, ge=0, description="Sleep stages processed")

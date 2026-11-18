"""Delete expired capture bodies in bounded, independently committed batches."""

from celery import shared_task

from app.repositories.received_capture_repository import received_capture_repository


@shared_task(
    name="app.integrations.celery.tasks.received_capture_cleanup_task.cleanup_received_captures",
    acks_late=True,
    soft_time_limit=120,
    time_limit=150,
)
def cleanup_received_captures() -> int:
    deleted = 0
    for _ in range(100):
        count = received_capture_repository.cleanup(batch_size=100)
        deleted += count
        if count < 100:
            break
    return deleted

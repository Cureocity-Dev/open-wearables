"""Read-time step merging; no materialized totals or stale background writes."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_

from app.database import DbSession
from app.models import DataPointSeries, DataSource, ProviderPriority
from app.repositories.device_type_priority_repository import DeviceTypePriorityRepository
from app.repositories.provider_priority_repository import ProviderPriorityRepository
from app.schemas.enums import SeriesType, get_series_type_id, infer_device_type_from_model
from app.services.step_merge import StepInterval, merge_steps


def get_smart_steps(db: DbSession, user_id: UUID, start: datetime, end: datetime) -> dict[date, tuple[int, dict]]:
    provider_order = ProviderPriorityRepository(ProviderPriority).get_priority_order(db)
    device_order = DeviceTypePriorityRepository().get_priority_order(db)
    rows = (
        db.query(DataPointSeries, DataSource)
        .join(DataSource, DataPointSeries.data_source_id == DataSource.id)
        .filter(
            DataSource.user_id == user_id,
            DataPointSeries.series_type_definition_id == get_series_type_id(SeriesType.steps),
            or_(
                DataPointSeries.recorded_at >= start - timedelta(days=1),
                DataPointSeries.end_at > start - timedelta(days=1),
            ),
            DataPointSeries.recorded_at < end + timedelta(days=1),
        )
        .all()
    )
    by_day: dict[date, list[StepInterval]] = {}
    split_days: set[date] = set()
    for sample, source in rows:
        offset = sample.zone_offset or "+00:00"
        sign = -1 if offset.startswith("-") else 1
        hours, minutes = map(int, offset[1:].split(":"))
        tz = timezone(sign * timedelta(hours=hours, minutes=minutes))
        begin = sample.recorded_at.replace(tzinfo=sample.recorded_at.tzinfo or timezone.utc)
        finish = sample.end_at
        if finish is not None:
            finish = finish.replace(tzinfo=finish.tzinfo or timezone.utc)
        device = infer_device_type_from_model(source.device_model)
        rank = (provider_order.get(source.provider, 99), device_order.get(device, 99), str(source.id))
        cursor = begin
        while True:
            day = cursor.astimezone(tz).date()
            midnight = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=tz)
            segment_end = min(finish, midnight) if finish is not None and finish > begin else finish
            value = sample.value
            if finish is not None and finish > begin and (cursor != begin or segment_end != finish):
                value *= Decimal(str((segment_end - cursor).total_seconds())) / Decimal(
                    str((finish - begin).total_seconds())
                )
                split_days.add(day)
            if start.date() <= day < end.date():
                by_day.setdefault(day, []).append(
                    StepInterval(str(source.id), cursor, segment_end, value, rank, device.value)
                )
            if (
                finish is None
                or finish <= begin
                or segment_end == finish
                or midnight.date() > end.date() + timedelta(days=1)
            ):
                break
            cursor = midnight
    results = {}
    for day, samples in by_day.items():
        merged = merge_steps(samples)
        results[day] = (
            merged.steps,
            {
                "requested": "smart_merge",
                "applied": "smart_merge",
                "is_estimated": merged.is_estimated or day in split_days,
                "is_partial": merged.is_partial,
                "contributing_device_types": list(merged.contributing_device_types),
            },
        )
    return results

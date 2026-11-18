"""Indexed, bounded keyset reads of normalized records for one user/provider."""

from typing import Any
from uuid import UUID

from sqlalchemy import literal, select, true
from sqlalchemy.orm import Session

from app.models import DataPointSeries, DataSource, EventRecord


def read_saved_records(
    db: Session, user_id: UUID, provider: str, *, limit: int, after: tuple[str, UUID] | None = None
) -> list[dict[str, Any]]:
    sources = select(DataSource.id).where(DataSource.user_id == user_id, DataSource.provider == provider).subquery()
    rows: list[dict[str, Any]] = []
    for kind, model in (("measurement", DataPointSeries), ("event", EventRecord)):
        if after is not None and after[0] == "event" and kind == "measurement":
            continue
        remaining = limit - len(rows)
        if remaining == 0:
            break
        if kind == "measurement":
            fields = [
                model.id.label("id"),
                DataPointSeries.recorded_at.label("recorded_at"),
                DataPointSeries.value.label("value"),
                DataPointSeries.series_type_definition_id.label("series_type_id"),
                literal(None).label("category"),
                literal(None).label("end_datetime"),
                literal(None).label("duration_seconds"),
            ]
        else:
            fields = [
                model.id.label("id"),
                EventRecord.start_datetime.label("recorded_at"),
                literal(None).label("value"),
                literal(None).label("series_type_id"),
                EventRecord.category.label("category"),
                EventRecord.end_datetime.label("end_datetime"),
                EventRecord.duration_seconds.label("duration_seconds"),
            ]
        page = select(*fields).where(model.data_source_id == sources.c.id)
        if after is not None and after[0] == kind:
            page = page.where(model.id > after[1])
        # Each source uses (data_source_id, id); only bounded pages enter the merge.
        page = page.order_by(model.id).limit(remaining).lateral()
        query = (
            select(literal(kind).label("record_type"), *page.c)
            .select_from(sources.join(page, true()))
            .order_by(page.c.id)
            .limit(remaining)
        )
        rows.extend(dict(row) for row in db.execute(query).mappings())
    return rows

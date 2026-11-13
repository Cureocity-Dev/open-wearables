"""Interval-aware steps preserve phone-only coverage."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.services.step_merge import StepInterval, merge_steps

BASE = datetime(2026, 11, 13, tzinfo=timezone.utc)


def sample(source: str, start: int, end: int | None, value: int, rank: int) -> StepInterval:
    return StepInterval(
        source,
        BASE + timedelta(minutes=start),
        BASE + timedelta(minutes=end) if end is not None else None,
        Decimal(value),
        (rank, source),
        "watch" if rank == 1 else "phone",
    )


def test_phone_then_watch() -> None:
    result = merge_steps([sample("phone", 0, 10, 356, 4), sample("watch", 10, 11, 30, 1)])
    assert result.steps == 386
    assert not result.is_estimated


def test_overlap_prefers_watch_and_prorates_phone() -> None:
    samples = [sample("phone", 0, 10, 100, 4), sample("watch", 5, 10, 30, 1)]
    result = merge_steps(samples)
    assert result.steps == 80
    assert result.is_estimated
    assert merge_steps(list(reversed(samples))) == result


def test_full_overlap_not_double_counted() -> None:
    assert merge_steps([sample("phone", 0, 10, 100, 4), sample("watch", 0, 10, 30, 1)]).steps == 30


def test_unknown_duration_is_disclosed() -> None:
    result = merge_steps([sample("phone", 0, None, 356, 4)])
    assert result.steps == 356
    assert result.is_partial
    assert result.is_estimated


def test_zero_watch_does_not_suppress_phone() -> None:
    assert merge_steps([sample("phone", 0, 10, 100, 4), sample("watch", 0, 10, 0, 1)]).steps == 100

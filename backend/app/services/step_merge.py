"""Deterministic overlap resolution; partial intervals assume uniform density."""

import heapq
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class StepInterval:
    source_id: str
    start: datetime
    end: datetime | None
    value: Decimal
    rank: tuple
    device_type: str


@dataclass(frozen=True)
class MergedSteps:
    steps: int
    is_estimated: bool
    is_partial: bool
    contributing_device_types: tuple[str, ...]


def merge_steps(samples: list[StepInterval]) -> MergedSteps:
    """Sweep interval boundaries, selecting one ranked source per segment.

    Samples within a source remain additive. Timestamp-only observations cannot
    establish coverage and are always reported as estimated/partial.
    """
    intervals = [s for s in samples if s.value > 0 and s.end is not None and s.end > s.start]
    points = [s for s in samples if s.value > 0 and (s.end is None or s.end <= s.start)]
    events: dict[datetime, list[tuple[int, int]]] = defaultdict(list)
    for i, sample in enumerate(intervals):
        assert sample.end is not None  # Guaranteed by interval filtering above.
        events[sample.start].append((i, 1))
        events[sample.end].append((i, -1))
    point_groups: dict[datetime, list[StepInterval]] = defaultdict(list)
    for sample in points:
        point_groups[sample.start].append(sample)
        events[sample.start]
    active: dict[str, dict[int, Decimal]] = defaultdict(dict)
    rates: dict[str, Decimal] = defaultdict(Decimal)
    ranks = {s.source_id: s.rank for s in samples}
    devices = {s.source_id: s.device_type for s in samples}
    heap: list[tuple[tuple, str]] = []
    total = Decimal(0)
    retained: dict[int, float] = defaultdict(float)
    contributors: set[str] = set()
    boundaries = sorted(events)
    for pos, boundary in enumerate(boundaries):
        for i, direction in events[boundary]:
            sample = intervals[i]
            assert sample.end is not None
            rate = sample.value / Decimal(str((sample.end - sample.start).total_seconds()))
            if direction == 1:
                if not active[sample.source_id]:
                    heapq.heappush(heap, (ranks[sample.source_id], sample.source_id))
                active[sample.source_id][i] = rate
                rates[sample.source_id] += rate
            else:
                active[sample.source_id].pop(i)
                rates[sample.source_id] -= rate
        while heap and not active[heap[0][1]]:
            heapq.heappop(heap)
        point_samples = point_groups.get(boundary, [])
        candidates = [(s.rank, s.source_id) for s in point_samples]
        if heap:
            candidates.append(heap[0])
        if candidates:
            winner = min(candidates)[1]
            for sample in point_samples:
                if sample.source_id == winner:
                    total += sample.value
                    contributors.add(sample.device_type)
        if pos + 1 == len(boundaries) or not heap:
            continue
        winner = heap[0][1]
        seconds = (boundaries[pos + 1] - boundary).total_seconds()
        total += rates[winner] * Decimal(str(seconds))
        contributors.add(devices[winner])
        for i in active[winner]:
            retained[i] += seconds
    estimated = any(
        s.end is not None and 0 < retained[i] < (s.end - s.start).total_seconds() for i, s in enumerate(intervals)
    )
    return MergedSteps(
        int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP)),
        estimated or bool(points),
        bool(points),
        tuple(sorted(contributors)),
    )

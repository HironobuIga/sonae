"""Scenario replay engine.

Sonae's watch loop consumes `FeedEvent`s. In live mode they come from JMA
feeds; in replay mode they come from a scenario file that reconstructs a
real disaster's official information timeline (with sources), so the full
agent pipeline can be demonstrated end-to-end — deterministically, offline,
and honestly labeled as a replay.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sonae.schemas import FeedEvent, FeedEventKind, Source


@dataclass
class Scenario:
    scenario_id: str
    title: str
    disclaimer: str
    sources: list[Source]
    events: list[FeedEvent]
    map_markers: list[dict]  # e.g. historical breach points, revealed by alert level


def load_scenario(path: Path | str) -> Scenario:
    data = json.loads(Path(path).read_text())
    base_sources = [Source(**s) for s in data.get("sources", [])]
    events: list[FeedEvent] = []
    for raw in data["events"]:
        source = Source(**raw["source"]) if "source" in raw else base_sources[0]
        events.append(
            FeedEvent(
                ts=datetime.fromisoformat(raw["ts"]),
                kind=FeedEventKind(raw["kind"]),
                area_code=raw.get("area_code"),
                area_name=raw.get("area_name"),
                title=raw["title"],
                body=raw["body"],
                source=source,
            )
        )
    events.sort(key=lambda e: e.ts)
    return Scenario(
        scenario_id=data["scenario_id"],
        title=data["title"],
        disclaimer=data["disclaimer"],
        sources=base_sources,
        events=events,
        map_markers=data.get("map_markers", []),
    )


class ReplayClock:
    """Steps through a scenario, releasing events in timestamp order.

    The CLI/web UI calls `advance()` to move simulated time forward and
    collect every event that has 'happened' since the last call.
    """

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self._cursor = 0

    @property
    def exhausted(self) -> bool:
        return self._cursor >= len(self.scenario.events)

    @property
    def now(self) -> datetime | None:
        """Timestamp of the most recently released event."""
        if self._cursor == 0:
            return None
        return self.scenario.events[self._cursor - 1].ts

    def peek_next(self) -> FeedEvent | None:
        if self.exhausted:
            return None
        return self.scenario.events[self._cursor]

    def advance(self, until: datetime | None = None) -> list[FeedEvent]:
        """Release the next event batch.

        With `until`, releases all events up to that simulated time. Without,
        releases events sharing the next pending timestamp (one 'moment').
        """
        if self.exhausted:
            return []
        events = self.scenario.events
        start = self._cursor
        if until is None:
            moment = events[start].ts
            end = start
            while end < len(events) and events[end].ts == moment:
                end += 1
        else:
            end = start
            while end < len(events) and events[end].ts <= until:
                end += 1
            if end == start:
                return []
        self._cursor = end
        return events[start:end]

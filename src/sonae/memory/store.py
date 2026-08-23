"""Household state persistence.

Local JSON files by default (demo/dev). The same interface is implemented by
the AgentCore Memory adapter (deploy/agentcore) so the agents never care
where state lives. One directory per household:

    store/<household_id>/household.json     — who we protect
    store/<household_id>/hazard_profile.json
    store/<household_id>/plan.json          — the family-approved timeline
    store/<household_id>/watch.json         — activated level, seen events
    store/<household_id>/checkins.json      — safety check-in board
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from sonae.config import settings
from sonae.schemas import CheckIn, HazardProfile, Household, TimelinePlan

T = TypeVar("T", bound=BaseModel)


class WatchState(BaseModel):
    activated_level: int = 0  # highest timeline step activated so far (0 = calm)
    seen_event_keys: list[str] = []
    last_checked: datetime | None = None
    history: list[dict] = []  # chronological log of decisions/notifications for the family journal


class HouseholdStore:
    def __init__(self, household_id: str, root: Path | None = None):
        self.household_id = household_id
        self.dir = (root or settings.store_dir) / household_id
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- generic helpers ---------------------------------------------------
    def _save(self, name: str, model: BaseModel) -> None:
        path = self.dir / f"{name}.json"
        path.write_text(model.model_dump_json(indent=2))

    def _load(self, name: str, cls: type[T]) -> T | None:
        path = self.dir / f"{name}.json"
        if not path.exists():
            return None
        return cls.model_validate_json(path.read_text())

    # -- typed accessors ---------------------------------------------------
    def save_household(self, h: Household) -> None:
        self._save("household", h)

    def load_household(self) -> Household | None:
        return self._load("household", Household)

    def save_hazard_profile(self, p: HazardProfile) -> None:
        self._save("hazard_profile", p)

    def load_hazard_profile(self) -> HazardProfile | None:
        return self._load("hazard_profile", HazardProfile)

    def save_plan(self, p: TimelinePlan) -> None:
        self._save("plan", p)

    def load_plan(self) -> TimelinePlan | None:
        return self._load("plan", TimelinePlan)

    def load_watch(self) -> WatchState:
        return self._load("watch", WatchState) or WatchState()

    def save_watch(self, w: WatchState) -> None:
        self._save("watch", w)

    def log_event(self, kind: str, detail: dict) -> None:
        w = self.load_watch()
        w.history.append({"ts": datetime.now(UTC).isoformat(), "kind": kind, **detail})
        self.save_watch(w)

    # -- check-ins ---------------------------------------------------------
    def load_checkins(self) -> list[CheckIn]:
        path = self.dir / "checkins.json"
        if not path.exists():
            return []
        return [CheckIn.model_validate(c) for c in json.loads(path.read_text())]

    def save_checkins(self, checkins: list[CheckIn]) -> None:
        path = self.dir / "checkins.json"
        path.write_text(json.dumps([c.model_dump(mode="json") for c in checkins], indent=2))

    @classmethod
    def list_households(cls, root: Path | None = None) -> list[str]:
        base = root or settings.store_dir
        if not base.exists():
            return []
        return sorted(p.name for p in base.iterdir() if (p / "household.json").exists())

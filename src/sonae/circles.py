"""Neighborhood circle mode (自主防災会 / neighborhood association).

After an earthquake or flood, Japanese neighborhood associations confirm
member safety with paper name lists carried door to door. A circle groups
Sonae households; the aggregation below is deterministic, and a Coordinator
agent turns the board into an actionable report for the 会長.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sonae.agents import factory
from sonae.agents.jsonio import parse_as
from sonae.config import settings
from sonae.memory.store import HouseholdStore
from sonae.schemas import CheckIn, CheckInStatus, Circle, CircleReport


def _circles_dir():
    path = settings.store_dir / "_circles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_circle(circle: Circle) -> None:
    (_circles_dir() / f"{circle.circle_id}.json").write_text(circle.model_dump_json(indent=2))


def load_circle(circle_id: str) -> Circle | None:
    path = _circles_dir() / f"{circle_id}.json"
    if not path.exists():
        return None
    return Circle.model_validate_json(path.read_text())


def list_circles() -> list[str]:
    return sorted(p.stem for p in _circles_dir().glob("*.json"))


def circle_board(circle: Circle) -> list[dict]:
    """Aggregate every member household's check-in board (deterministic)."""
    board: list[dict] = []
    for hid in circle.household_ids:
        store = HouseholdStore(hid)
        household = store.load_household()
        checkins = store.load_checkins()
        watch = store.load_watch()
        roster = {m.name: m for m in (household.members if household else [])}
        members = [json.loads(c.model_dump_json()) for c in checkins] or [
            {"member": m.name, "status": "pending", "note": None, "updated_at": None} for m in roster.values()
        ]
        for m in members:
            person = roster.get(m["member"])
            if person:
                m["age"] = person.age
                m["needs"] = person.needs
        board.append(
            {
                "household_id": hid,
                "address": household.address if household else "(unknown)",
                "activated_level": watch.activated_level,
                "members": members,
            }
        )
    return board


def board_counts(board: list[dict]) -> dict[str, int]:
    counts = {s.value: 0 for s in CheckInStatus}
    for row in board:
        for m in row["members"]:
            counts[m["status"]] = counts.get(m["status"], 0) + 1
    counts["total"] = sum(counts.values())
    return counts


def compose_report(circle: Circle) -> CircleReport:
    """Have the Coordinator agent turn the board into an actionable report."""
    board = circle_board(circle)
    counts = board_counts(board)
    agent = factory.make_coordinator()
    prompt = (
        f"Circle: {circle.name} (coordinator: {circle.coordinator})\n"
        f"Exact counts (computed, trust these): {json.dumps(counts)}\n\n"
        f"Check-in board:\n{json.dumps(board, ensure_ascii=False, indent=1)}"
    )
    return parse_as(CircleReport, str(agent(prompt)))


def record_checkin(household_id: str, member: str, status: str, note: str | None = None) -> list[CheckIn]:
    store = HouseholdStore(household_id)
    checkins = store.load_checkins()
    if not any(c.member == member for c in checkins):
        checkins.append(CheckIn(member=member))
    for c in checkins:
        if c.member == member:
            c.status = CheckInStatus(status)
            c.note = note
            c.updated_at = datetime.now(UTC)
    store.save_checkins(checkins)
    store.log_event("checkin", {"member": member, "status": status, "note": note or ""})
    return checkins

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
from sonae.memory.store import HouseholdStore, atomic_write_text
from sonae.schemas import CheckIn, CheckInStatus, Circle, CircleReport


def _circles_dir():
    path = settings.store_dir / "_circles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_circle(circle: Circle) -> None:
    atomic_write_text(_circles_dir() / f"{circle.circle_id}.json", circle.model_dump_json(indent=2))


def report_path(circle_id: str):
    return _circles_dir() / f"{circle_id}.report.json"


def save_report(circle_id: str, report: CircleReport) -> None:
    """Persist the coordinator's report — the dashboard reads this file.

    Both the CLI and the web app compose reports; if only one of them saved,
    the committed demo would show a report from a different run than the
    check-ins beside it.
    """
    atomic_write_text(
        report_path(circle_id),
        json.dumps(
            {"composed_at": datetime.now(UTC).isoformat(), **json.loads(report.model_dump_json())},
            ensure_ascii=False,
            indent=1,
        ),
    )


def load_circle(circle_id: str) -> Circle | None:
    path = _circles_dir() / f"{circle_id}.json"
    if not path.exists():
        return None
    try:
        return Circle.model_validate_json(path.read_text())
    except Exception:
        return None  # not a circle definition (e.g. a stored report)


def list_circles() -> list[str]:
    # Circle definitions are '<id>.json'; sidecars ('<id>.report.json',
    # '<id>.journal.json') live beside them and are not circles.
    return sorted(p.stem for p in _circles_dir().glob("*.json") if p.name.count(".") == 1)


def log_circle_event(circle_id: str, kind: str, detail: dict) -> None:
    """Append to the circle's journal — the coordinator-side flight recorder.

    Households have one (watch.history); circle-level work had none, so a
    failed coordinator report left no trace anywhere.
    """
    path = _circles_dir() / f"{circle_id}.journal.json"
    entries: list[dict] = []
    if path.exists():
        try:
            entries = json.loads(path.read_text())
        except json.JSONDecodeError:
            entries = []
    entries.append({"ts": datetime.now(UTC).isoformat(), "kind": kind, **detail})
    atomic_write_text(path, json.dumps(entries[-200:], ensure_ascii=False, indent=1))


def circle_journal(circle_id: str) -> list[dict]:
    path = _circles_dir() / f"{circle_id}.journal.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return []


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
            # Unknown people are assumed to live here: the safe default is a
            # wasted knock, not a skipped one.
            m["lives_at_home"] = person.lives_at_home if person else True
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


def _at_home(member: dict) -> bool:
    return bool(member.get("lives_at_home", True))


def board_counts(board: list[dict]) -> dict[str, int]:
    """Status counts for the door-knock population: members who live at the address.

    A neighbor walking the name list in the rain can only confirm people who
    are actually there. Remote members (the son in Tokyo who watches over the
    house) are counted separately as `remote` — counting them here is how the
    coordinator ends up being told to knock on a door 200 km away.
    """
    counts = {s.value: 0 for s in CheckInStatus}
    remote = 0
    for row in board:
        for m in row["members"]:
            if not _at_home(m):
                remote += 1
                continue
            counts[m["status"]] = counts.get(m["status"], 0) + 1
    counts["total"] = sum(counts.values())
    counts["remote"] = remote
    return counts


def phone_followups(board: list[dict]) -> list[str]:
    """Unconfirmed members who live elsewhere — phone calls, never door knocks."""
    unconfirmed = (CheckInStatus.pending.value, CheckInStatus.no_response.value)
    return [
        f"{row['household_id']}/{m['member']}"
        for row in board
        for m in row["members"]
        if not _at_home(m) and m["status"] in unconfirmed
    ]


def compose_report(circle: Circle) -> CircleReport:
    """Have the Coordinator agent turn the board into an actionable report."""
    board = circle_board(circle)
    counts = board_counts(board)
    phone = phone_followups(board)
    agent = factory.make_coordinator()
    prompt = (
        f"Circle: {circle.name} (coordinator: {circle.coordinator})\n"
        f"Exact counts for the door-knock population — members with "
        f"lives_at_home=true (computed, trust these): {json.dumps(counts)}\n"
        f"Members with lives_at_home=false live in another town. NEVER send a "
        f"neighbor to their door and never list them under visits. Unconfirmed "
        f"remote members are phone follow-ups: {json.dumps(phone, ensure_ascii=False)}\n\n"
        f"Check-in board (each member carries lives_at_home):\n"
        f"{json.dumps(board, ensure_ascii=False, indent=1)}"
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

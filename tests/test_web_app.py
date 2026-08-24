"""Dashboard endpoint tests for the two ways a replay step used to lose events:
a check-then-set busy guard, and a cursor advanced before the worker ran.
"""

import threading
import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from sonae.agents.watch import WatchOutcome
from sonae.memory.store import HouseholdStore
from sonae.schemas import (
    FamilyMember,
    HazardType,
    Household,
    TimelineAction,
    TimelinePlan,
    TimelineStep,
)

HID = "web1"


@pytest.fixture()
def client(tmp_store):
    from sonae.web import app as webapp

    store = HouseholdStore(HID)
    store.save_household(
        Household(
            household_id=HID,
            address="長野県長野市穂保",
            lat=36.68,
            lon=138.27,
            muni_code="20201",
            muni_name="長野市",
            pref_name="長野県",
            jma_office_code="200000",
            members=[FamilyMember(name="Yoshiko", age=78)],
        )
    )
    store.save_plan(
        TimelinePlan(
            household_id=HID,
            hazard_focus=[HazardType.flood],
            steps=[
                TimelineStep(
                    alert_level=3,
                    trigger="trigger",
                    headline="step",
                    actions=[TimelineAction(member="Yoshiko", description="act")],
                )
            ],
            created_at=datetime.now(UTC),
            family_approved=True,
        )
    )
    with TestClient(webapp.app) as c:
        yield c
    webapp._replay_clocks.pop(HID, None)
    webapp._busy.pop(HID, None)


def _wait_idle(client, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if client.get("/api/state", params={"household": HID}).json()["busy"] is None:
            return
        time.sleep(0.02)
    raise AssertionError("worker never finished")


def _replay(client) -> dict:
    return client.get("/api/state", params={"household": HID}).json()["replay"]


def test_failed_step_holds_the_replay_cursor(client, monkeypatch):
    client.post("/api/replay/load", json={"household": HID})
    pending = _replay(client)["next"]["ts"]

    monkeypatch.setattr(
        "sonae.agents.watch.process_events",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("watch cycle failed")),
    )
    assert client.post("/api/replay/step", json={"household": HID}).json()["stepped"] is True
    _wait_idle(client)

    replay = _replay(client)
    assert replay["now"] is None, "a failed cycle must not consume the moment"
    assert replay["next"]["ts"] == pending

    # retry: same moment, this time it succeeds and the cursor moves
    monkeypatch.setattr(
        "sonae.agents.watch.process_events",
        lambda *a, **k: WatchOutcome(processed_events=1, dispatched=1, note="ok"),
    )
    assert client.post("/api/replay/step", json={"household": HID}).json()["sim_time"] == pending
    _wait_idle(client)
    assert _replay(client)["now"] == pending


def test_second_step_while_busy_is_rejected(client, monkeypatch):
    client.post("/api/replay/load", json={"household": HID})
    gate = threading.Event()

    def slow(*a, **k):
        gate.wait(5)
        return WatchOutcome(processed_events=1, dispatched=1, note="ok")

    monkeypatch.setattr("sonae.agents.watch.process_events", slow)
    assert client.post("/api/replay/step", json={"household": HID}).status_code == 200
    # the busy flag is claimed by the request, not by the worker thread
    assert client.post("/api/replay/step", json={"household": HID}).status_code == 409
    gate.set()
    _wait_idle(client)
    assert client.post("/api/replay/step", json={"household": HID}).status_code == 200
    gate.set()
    _wait_idle(client)

"""Watch-pipeline logic tests with the agent layer faked out.

`_invoke_json` is the single seam every model call flows through; faking it
lets us test triggering, suppression, check-in opening, and the fallback
relay deterministically — no model, no network.
"""

from datetime import UTC, datetime

import pytest

from sonae.agents import watch
from sonae.memory.store import HouseholdStore
from sonae.schemas import (
    CheckInStatus,
    FamilyMember,
    FeedEvent,
    FeedEventKind,
    HazardType,
    Household,
    Notification,
    NotificationBatch,
    SentinelDecision,
    Source,
    TimelineAction,
    TimelinePlan,
    TimelineStep,
    VerificationReport,
)

SRC = Source(name="JMA warning feed", url="https://www.jma.go.jp/bosai/")


def _household() -> Household:
    return Household(
        household_id="t1",
        address="長野県長野市穂保",
        lat=36.68,
        lon=138.27,
        muni_code="20201",
        muni_name="長野市",
        pref_name="長野県",
        jma_office_code="200000",
        members=[FamilyMember(name="Yoshiko", age=78), FamilyMember(name="Kenji", lives_at_home=False)],
    )


def _plan(approved: bool = True) -> TimelinePlan:
    return TimelinePlan(
        household_id="t1",
        hazard_focus=[HazardType.flood],
        steps=[
            TimelineStep(alert_level=lvl, trigger=f"trigger L{lvl}", headline=f"step L{lvl}",
                         actions=[TimelineAction(member="Yoshiko", description="act")])
            for lvl in (2, 3, 4)
        ],
        created_at=datetime.now(UTC),
        family_approved=approved,
    )


def _event(title: str = "大雨警報") -> FeedEvent:
    return FeedEvent(
        ts=datetime(2019, 10, 12, 8, 30, tzinfo=UTC),
        kind=FeedEventKind.jma_warning,
        area_code="2020111",
        title=title,
        body="body",
        source=SRC,
    )


class CaptureChannel:
    def __init__(self):
        self.sent: list[Notification] = []

    def send(self, notification, household):
        self.sent.append(notification)


def _batch(urgent: bool = True) -> NotificationBatch:
    return NotificationBatch(
        household_id="t1",
        notifications=[Notification(to_member="Yoshiko", subject="s", body="b", urgent=urgent)],
    )


@pytest.fixture()
def fake_agents(monkeypatch):
    """Patch the agent seam; per-test behavior via the returned dict."""
    behavior = {
        "decision": SentinelDecision(triggered=False, reasoning="quiet"),
        "batch": _batch(),
        "reports": [VerificationReport(approved=True, checks=[])],
    }
    state = {"report_i": 0}

    def fake_invoke(agent, prompt, model_cls, retries=1):
        if model_cls is SentinelDecision:
            return behavior["decision"]
        if model_cls is NotificationBatch:
            return behavior["batch"]
        if model_cls is VerificationReport:
            i = min(state["report_i"], len(behavior["reports"]) - 1)
            state["report_i"] += 1
            return behavior["reports"][i]
        raise AssertionError(f"unexpected model {model_cls}")

    monkeypatch.setattr(watch, "_invoke_json", fake_invoke)
    for name in ("make_sentinel", "make_messenger", "make_verifier"):
        monkeypatch.setattr(watch.factory, name, lambda *a, **k: object())
    return behavior


def _setup(tmp_store, approved=True) -> HouseholdStore:
    store = HouseholdStore("t1")
    store.save_household(_household())
    store.save_plan(_plan(approved))
    return store


def test_refuses_without_approval(tmp_store, fake_agents):
    store = _setup(tmp_store, approved=False)
    out = watch.process_events(store, [_event()], CaptureChannel())
    assert out.dispatched == 0
    assert "not acting" in out.note


def test_trigger_dispatches_and_updates_level(tmp_store, fake_agents):
    store = _setup(tmp_store)
    fake_agents["decision"] = SentinelDecision(triggered=True, alert_level=3, reasoning="river warning")
    channel = CaptureChannel()
    out = watch.process_events(store, [_event()], channel)
    assert out.dispatched == 1 and not out.fallback_relay
    assert store.load_watch().activated_level == 3
    assert store.load_checkins() == []  # below L4: no check-in board


def test_checkins_open_at_level_four(tmp_store, fake_agents):
    store = _setup(tmp_store)
    fake_agents["decision"] = SentinelDecision(triggered=True, alert_level=4, reasoning="evac order")
    watch.process_events(store, [_event()], CaptureChannel())
    checkins = store.load_checkins()
    assert {c.member for c in checkins} == {"Yoshiko", "Kenji"}
    assert all(c.status == CheckInStatus.pending for c in checkins)


def test_dedup_and_no_downgrade(tmp_store, fake_agents):
    store = _setup(tmp_store)
    fake_agents["decision"] = SentinelDecision(triggered=True, alert_level=3, reasoning="warning")
    watch.process_events(store, [_event()], CaptureChannel())
    # same event again: deduped before any agent runs
    out = watch.process_events(store, [_event()], CaptureChannel())
    assert out.processed_events == 0 and "no new events" in out.note
    # new event, but sentinel proposes a level not above current: no dispatch
    fake_agents["decision"] = SentinelDecision(triggered=True, alert_level=2, reasoning="advisory")
    out = watch.process_events(store, [_event("洪水注意報")], CaptureChannel())
    assert out.dispatched == 0
    assert store.load_watch().activated_level == 3


def test_fallback_relay_when_verification_fails_twice(tmp_store, fake_agents):
    store = _setup(tmp_store)
    fake_agents["decision"] = SentinelDecision(triggered=True, alert_level=4, reasoning="evac order")
    fake_agents["reports"] = [
        VerificationReport(approved=False, checks=[], revision_request="fix X"),
        VerificationReport(approved=False, checks=[], revision_request="still wrong"),
    ]
    channel = CaptureChannel()
    out = watch.process_events(store, [_event("避難指示")], channel)
    assert out.fallback_relay is True
    assert out.dispatched == len(_household().members)
    assert all("OFFICIAL INFORMATION RELAY" in n.body for n in channel.sent)
    assert all(n.urgent for n in channel.sent)
    # the signal still went through — level advanced despite failed composition
    assert store.load_watch().activated_level == 4

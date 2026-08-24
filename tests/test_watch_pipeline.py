"""Watch-pipeline logic tests with the agent layer faked out.

`_invoke_json` is the single seam every model call flows through; faking it
lets us test triggering, suppression, check-in opening, and the fallback
relay deterministically — no model, no network.
"""

import json
from datetime import UTC, datetime

import pytest

from sonae.agents import onboarding, watch
from sonae.memory.store import HouseholdStore
from sonae.schemas import (
    CheckInStatus,
    ClaimCheck,
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


class ExplodingChannel:
    """A channel that dies mid-dispatch (disk full, network gone)."""

    def send(self, notification, household):
        raise RuntimeError("channel unavailable")


def _batch(urgent: bool = True) -> NotificationBatch:
    return NotificationBatch(
        household_id="t1",
        notifications=[Notification(to_member="Yoshiko", subject="s", body="b", urgent=urgent)],
    )


def _report(verdict: str = "supported", revision: str | None = None) -> VerificationReport:
    """A report with a real check — approval must survive the checks."""
    return VerificationReport(
        approved=True,
        checks=[ClaimCheck(claim="Level 3 warning issued for this area", source_quote="大雨警報", verdict=verdict)],
        revision_request=revision,
    )


@pytest.fixture()
def fake_agents(monkeypatch):
    """Patch the agent seam; per-test behavior via the returned dict.

    Any configured value may be an Exception instance, which the seam raises —
    that is how a model error / unparseable output is simulated.
    """
    behavior = {
        "decision": SentinelDecision(triggered=False, reasoning="quiet"),
        "batch": _batch(),
        "reports": [_report()],
    }
    state = {"report_i": 0}

    def _result(value):
        if isinstance(value, Exception):
            raise value
        return value

    def fake_invoke(agent, prompt, model_cls, retries=1):
        if model_cls is SentinelDecision:
            return _result(behavior["decision"])
        if model_cls is NotificationBatch:
            return _result(behavior["batch"])
        if model_cls is VerificationReport:
            i = min(state["report_i"], len(behavior["reports"]) - 1)
            state["report_i"] += 1
            return _result(behavior["reports"][i])
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
        _report("unsupported", revision="fix X"),
        _report("unsupported", revision="still wrong"),
    ]
    channel = CaptureChannel()
    out = watch.process_events(store, [_event("避難指示")], channel)
    assert out.fallback_relay is True
    assert out.dispatched == len(_household().members)
    assert all("OFFICIAL INFORMATION RELAY" in n.body for n in channel.sent)
    assert all(n.urgent for n in channel.sent)
    # the signal still went through — level advanced despite failed composition
    assert store.load_watch().activated_level == 4


def test_messenger_crash_still_relays_official_text(tmp_store, fake_agents):
    """A Level 3+ event must reach the family even when the AI layer throws."""
    store = _setup(tmp_store)
    fake_agents["decision"] = SentinelDecision(triggered=True, alert_level=4, reasoning="evac order")
    fake_agents["batch"] = RuntimeError("model endpoint unavailable")
    channel = CaptureChannel()
    out = watch.process_events(store, [_event("避難指示")], channel)
    assert out.fallback_relay is True
    assert out.dispatched == len(_household().members)
    assert all("OFFICIAL INFORMATION RELAY" in n.body for n in channel.sent)
    history = store.load_watch().history
    assert any(h["kind"] == "error" and h.get("op") == "compose_verify" for h in history), "failure must be journaled"
    # delivered, so the event is correctly consumed
    assert store.load_watch().seen_event_keys


def test_composition_failure_below_level_three_is_retried(tmp_store, fake_agents):
    """Nothing was sent, so nothing may be deduped: the next cycle tries again."""
    store = _setup(tmp_store)
    fake_agents["decision"] = SentinelDecision(triggered=True, alert_level=2, reasoning="advisory")
    fake_agents["batch"] = RuntimeError("model endpoint unavailable")
    channel = CaptureChannel()
    out = watch.process_events(store, [_event()], channel)
    assert out.dispatched == 0 and channel.sent == []
    assert store.load_watch().seen_event_keys == []
    assert any(h["kind"] == "error" for h in store.load_watch().history)

    # same event next cycle, model back up: it still gets through
    fake_agents["batch"] = _batch()
    out = watch.process_events(store, [_event()], channel)
    assert out.processed_events == 1 and out.dispatched == 1
    assert store.load_watch().seen_event_keys


def test_channel_failure_leaves_event_unseen(tmp_store, fake_agents):
    store = _setup(tmp_store)
    fake_agents["decision"] = SentinelDecision(triggered=True, alert_level=3, reasoning="warning")
    with pytest.raises(RuntimeError):
        watch.process_events(store, [_event()], ExplodingChannel())
    state = store.load_watch()
    assert state.seen_event_keys == [], "an undelivered event must not be deduped away"
    assert state.activated_level == 0
    assert any(h["kind"] == "error" and h.get("op") == "dispatch" for h in state.history)

    # next cycle with a working channel: the warning still reaches the family
    channel = CaptureChannel()
    out = watch.process_events(store, [_event()], channel)
    assert out.processed_events == 1 and out.dispatched == 1
    assert store.load_watch().activated_level == 3


def test_standby_events_are_recorded_seen(tmp_store, fake_agents):
    """A journaled 'no notification needed' decision is the one safe dedupe."""
    store = _setup(tmp_store)
    fake_agents["decision"] = SentinelDecision(triggered=False, reasoning="different basin")
    out = watch.process_events(store, [_event()], CaptureChannel())
    assert out.dispatched == 0
    assert store.load_watch().seen_event_keys
    out = watch.process_events(store, [_event()], CaptureChannel())
    assert out.processed_events == 0


def test_verification_approval_is_derived_from_checks():
    # a model asserting approval with nothing checked no longer waves itself through
    assert VerificationReport(approved=True, checks=[]).approved is False
    assert VerificationReport(approved=True, checks=[ClaimCheck(claim="c", verdict="unsupported")]).approved is False
    assert VerificationReport(approved=True, checks=[ClaimCheck(claim="c", verdict="supported")]).approved is True
    # …and the derivation only ever withholds approval, never grants it
    assert VerificationReport(approved=False, checks=[ClaimCheck(claim="c", verdict="supported")]).approved is False
    assert VerificationReport(checks=[ClaimCheck(claim="c", verdict="supported")]).approved is False
    # free-text verdicts normalize, and never upward into 'supported'
    assert ClaimCheck(claim="c", verdict="Supported").verdict == "supported"
    assert ClaimCheck(claim="c", verdict="probably fine").verdict == "uncertain"
    assert ClaimCheck(claim="c", verdict="contradicted").verdict == "unsupported"


def test_planner_cannot_self_approve_its_plan(tmp_store, fake_agents, monkeypatch):
    """A Planner emitting family_approved=true must not bypass the human gate."""

    class _Node:
        def __init__(self, node_id: str):
            self.node_id = node_id

    class _GraphResult:
        def __init__(self, results: dict):
            self.results = results
            self.execution_order = [_Node(k) for k in results]

    plan_json = _plan(approved=True).model_dump_json()
    assert '"family_approved":true' in plan_json.replace(" ", "")
    profile_json = json.dumps(
        {
            "household_id": "t1",
            "assessments": [],
            "nearest_shelters": [],
            "summary": "flood risk",
            "assessed_at": datetime.now(UTC).isoformat(),
        }
    )
    report_json = json.dumps(
        {"approved": True, "checks": [{"claim": "shelter distance", "verdict": "supported"}]}
    )
    monkeypatch.setattr(
        onboarding,
        "build_onboarding_graph",
        lambda store: (
            lambda task: _GraphResult(
                {"cartographer": profile_json, "planner": plan_json, "verifier": report_json}
            )
        ),
    )

    store = HouseholdStore("t1")
    result = onboarding.run_onboarding(_household(), store)
    assert result.plan.family_approved is False
    assert store.load_plan().family_approved is False
    assert any(h["kind"] == "planner_self_approval_ignored" for h in store.load_watch().history)

    # …and the watch pipeline stays silent until a human approves
    fake_agents["decision"] = SentinelDecision(triggered=True, alert_level=4, reasoning="evac order")
    channel = CaptureChannel()
    out = watch.process_events(store, [_event("避難指示")], channel)
    assert out.dispatched == 0 and channel.sent == []
    assert "not acting" in out.note

    onboarding.approve_plan(store)
    out = watch.process_events(store, [_event("避難指示")], channel)
    assert out.dispatched == 1 and channel.sent

"""The watch pipeline: official feed events in, verified family action out.

    events ──▶ Sentinel ──(triggered)──▶ Messenger ──▶ Verifier ──▶ dispatch
                  │                                        │
                  └── not our signal: log & stand by       └─ rejected: revise once,
                                                              then FALLBACK TO RAW RELAY

Safety posture:
- The Sentinel can only bind official signals to a plan the family approved
  in advance (`family_approved`); Sonae never invents evacuation judgments.
- AI-composed prose fails CLOSED (unverified text is never sent), but the
  signal itself fails OPEN: if composition can't be verified in time during
  a Level 3+ event, Sonae relays the official text verbatim with citations
  instead of staying silent. Silence is the one unacceptable failure mode.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from sonae.agents import factory
from sonae.agents.audit import AuditHook
from sonae.agents.jsonio import AgentOutputError, parse_as
from sonae.channels.base import Channel
from sonae.memory.store import HouseholdStore
from sonae.schemas import (
    FeedEvent,
    Notification,
    NotificationBatch,
    SentinelDecision,
    VerificationReport,
)


class WatchOutcome(BaseModel):
    processed_events: int
    decision: SentinelDecision | None = None
    batch: NotificationBatch | None = None
    report: VerificationReport | None = None
    dispatched: int = 0
    fallback_relay: bool = False
    note: str = ""


def _event_key(e: FeedEvent) -> str:
    return f"{e.ts.isoformat()}|{e.title}"


def _invoke_json(agent, prompt: str, model_cls, retries: int = 1):
    """Invoke an agent and validate its JSON output, retrying with the
    validation error appended so the model can self-correct."""
    attempt_prompt = prompt
    last_error: AgentOutputError | None = None
    for _ in range(retries + 1):
        result = agent(attempt_prompt)
        try:
            return parse_as(model_cls, str(result))
        except AgentOutputError as exc:
            last_error = exc
            attempt_prompt = (
                f"{prompt}\n\nYour previous output failed validation:\n{exc}\n"
                f"Re-emit ONLY the corrected JSON object."
            )
    raise last_error  # type: ignore[misc]


def _events_block(events: list[FeedEvent]) -> str:
    return "\n".join(
        f"- [{e.ts.isoformat()}] ({e.kind.value}) {e.title}\n"
        f"  area: {e.area_name or e.area_code or 'n/a'}\n"
        f"  body: {e.body}\n"
        f"  source: {e.source.name} <{e.source.url}>"
        for e in events
    )


def _fallback_notifications(events: list[FeedEvent], store: HouseholdStore) -> NotificationBatch:
    """Raw relay of official text — used only when verified composition fails."""
    household = store.load_household()
    members = household.members if household else []
    body = "OFFICIAL INFORMATION RELAY (automatic, unedited):\n" + "\n".join(
        f"• {e.ts.strftime('%H:%M')} {e.title} — {e.source.name}" for e in events
    )
    return NotificationBatch(
        household_id=store.household_id,
        notifications=[
            Notification(
                to_member=m.name,
                subject="[Sonae] Official alert relay",
                body=body,
                citations=[e.source for e in events],
                urgent=True,
            )
            for m in members
        ],
        composed_at=datetime.now(timezone.utc),
    )


def process_events(store: HouseholdStore, events: list[FeedEvent], channel: Channel) -> WatchOutcome:
    """Run one watch cycle over a batch of feed events."""
    plan = store.load_plan()
    household = store.load_household()
    if plan is None or household is None:
        return WatchOutcome(processed_events=0, note="no household/plan; run onboarding first")
    if not plan.family_approved:
        return WatchOutcome(processed_events=0, note="plan not yet approved by the family; not acting")

    watch = store.load_watch()
    fresh = [e for e in events if _event_key(e) not in watch.seen_event_keys]
    if not fresh:
        watch.last_checked = datetime.now(timezone.utc)
        store.save_watch(watch)
        return WatchOutcome(processed_events=0, note="no new events")

    audit = AuditHook(store)
    sentinel = factory.make_sentinel(audit)
    decision = _invoke_json(
        sentinel,
        (
            "New official events arrived. Decide whether they activate the plan "
            f"beyond the current level.\n\nCurrent activated level: {watch.activated_level}\n\n"
            f"Family plan JSON:\n{plan.model_dump_json(indent=1)}\n\n"
            f"New events:\n{_events_block(fresh)}"
        ),
        SentinelDecision,
    )

    watch.seen_event_keys.extend(_event_key(e) for e in fresh)
    watch.last_checked = datetime.now(timezone.utc)
    store.save_watch(watch)
    store.log_event(
        "sentinel_decision",
        {
            "triggered": decision.triggered,
            "level": decision.alert_level,
            "reasoning": decision.reasoning,
            "events": [e.title for e in fresh],
        },
    )

    if not decision.triggered or (decision.alert_level or 0) <= watch.activated_level:
        return WatchOutcome(
            processed_events=len(fresh),
            decision=decision,
            note="stand by — no step activation beyond current level",
        )

    messenger = factory.make_messenger(audit)
    compose_prompt = (
        "Compose the family notifications for this activation.\n\n"
        f"Decision JSON:\n{decision.model_dump_json(indent=1)}\n\n"
        f"Household JSON:\n{household.model_dump_json(indent=1)}\n\n"
        f"Family plan JSON:\n{plan.model_dump_json(indent=1)}\n\n"
        f"Triggering events:\n{_events_block(fresh)}"
    )
    batch = _invoke_json(messenger, compose_prompt, NotificationBatch)
    batch.composed_at = datetime.now(timezone.utc)
    batch.alert_level = decision.alert_level

    verifier = factory.make_verifier(audit, with_tools=False)
    evidence = (
        f"EVIDENCE — official events:\n{_events_block(fresh)}\n\n"
        f"EVIDENCE — family plan (approved):\n{plan.model_dump_json(indent=1)}\n\n"
        f"EVIDENCE — sentinel decision:\n{decision.model_dump_json(indent=1)}"
    )
    report = _invoke_json(
        verifier,
        f"Audit this notification batch before it is sent.\n\nDRAFT:\n{batch.model_dump_json(indent=1)}\n\n{evidence}",
        VerificationReport,
    )

    fallback = False
    if not report.approved:
        # One revision pass, then relay official text rather than send unverified prose.
        batch = _invoke_json(
            messenger,
            f"{compose_prompt}\n\nA verifier rejected your draft: {report.revision_request}\n"
            "Fix exactly that and re-emit the JSON.",
            NotificationBatch,
        )
        batch.composed_at = datetime.now(timezone.utc)
        batch.alert_level = decision.alert_level
        report = _invoke_json(
            verifier,
            f"Audit this revised notification batch.\n\nDRAFT:\n{batch.model_dump_json(indent=1)}\n\n{evidence}",
            VerificationReport,
        )
        if not report.approved:
            batch = _fallback_notifications(fresh, store)
            fallback = True

    dispatched = 0
    for notification in batch.notifications:
        channel.send(notification, household)
        dispatched += 1

    watch = store.load_watch()
    watch.activated_level = max(watch.activated_level, decision.alert_level or 0)
    store.save_watch(watch)
    store.log_event(
        "notifications_sent",
        {
            "level": decision.alert_level,
            "count": dispatched,
            "verified": not fallback,
            "fallback_relay": fallback,
        },
    )
    return WatchOutcome(
        processed_events=len(fresh),
        decision=decision,
        batch=batch,
        report=report,
        dispatched=dispatched,
        fallback_relay=fallback,
        note=f"activated level {decision.alert_level}",
    )

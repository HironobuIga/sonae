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
  a Level 3+ event — rejected twice, or crashed outright — Sonae relays the
  official text verbatim with citations instead of staying silent. Silence
  is the one unacceptable failure mode.
- An event is recorded as seen only AFTER its notifications were dispatched,
  or after a journaled decision that it needs none. Anything that fails in
  between is retried on the next cycle instead of being deduped into silence.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from sonae.agents import factory
from sonae.agents.audit import AuditHook
from sonae.agents.jsonio import AgentOutputError, parse_as
from sonae.alert_levels import max_supported_level
from sonae.channels.base import Channel
from sonae.memory.store import HouseholdStore
from sonae.schemas import (
    CheckIn,
    FeedEvent,
    Household,
    Notification,
    NotificationBatch,
    SentinelDecision,
    TimelinePlan,
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


def _log_verification(store: HouseholdStore, report: VerificationReport, attempt: int) -> None:
    # Kept apart on purpose: only `unsupported` blocks a dispatch, and this
    # journal is quoted in the docs. Lumping the two together would attribute
    # rejections to claims the verifier merely could not confirm either way.
    store.log_event(
        "verification",
        {
            "attempt": attempt,
            "approved": report.approved,
            "checks": len(report.checks),
            "unsupported": [c.claim[:120] for c in report.checks if c.verdict == "unsupported"],
            "uncertain": [c.claim[:120] for c in report.checks if c.verdict == "uncertain"],
            "revision_request": (report.revision_request or "")[:300],
        },
    )


def _events_block(events: list[FeedEvent]) -> str:
    return "\n".join(
        f"- [{e.ts.isoformat()}] ({e.kind.value}) {e.title}\n"
        f"  area: {e.area_name or e.area_code or 'n/a'}\n"
        f"  body: {e.body}\n"
        f"  source: {e.source.name} <{e.source.url}>"
        for e in events
    )


def _record_seen(store: HouseholdStore, events: list[FeedEvent]) -> None:
    """Mark events as handled — the deduplication memory for the next cycle.

    Called ONLY after notifications have actually been dispatched, or after a
    journaled decision that this batch warrants none. Recording an event as
    seen any earlier turns every downstream failure into permanent silence:
    the next cycle would dedupe away the very warning that never got through.
    """
    watch = store.load_watch()
    watch.seen_event_keys.extend(_event_key(e) for e in events)
    watch.last_checked = datetime.now(UTC)
    store.save_watch(watch)


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
        composed_at=datetime.now(UTC),
    )


def _compose_and_verify(
    store: HouseholdStore,
    audit: AuditHook,
    decision: SentinelDecision,
    household: Household,
    plan: TimelinePlan,
    fresh: list[FeedEvent],
) -> tuple[NotificationBatch, VerificationReport | None, bool]:
    """Compose the family's notifications and put them through the Verifier.

    Returns (batch, report, fallback_relay). Prose fails CLOSED: after a second
    rejection the batch handed back is the verbatim official relay, never
    unverified text.
    """
    messenger = factory.make_messenger(audit)
    compose_prompt = (
        "Compose the family notifications for this activation.\n\n"
        f"Decision JSON:\n{decision.model_dump_json(indent=1)}\n\n"
        f"Household JSON:\n{household.model_dump_json(indent=1)}\n\n"
        f"Family plan JSON:\n{plan.model_dump_json(indent=1)}\n\n"
        f"Triggering events:\n{_events_block(fresh)}"
    )
    batch = _invoke_json(messenger, compose_prompt, NotificationBatch)
    batch.composed_at = datetime.now(UTC)
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
    _log_verification(store, report, attempt=1)
    if report.approved:
        return batch, report, False

    # One revision pass, then relay official text rather than send unverified prose.
    batch = _invoke_json(
        messenger,
        f"{compose_prompt}\n\nA verifier rejected your draft: {report.revision_request}\n"
        "Fix exactly that and re-emit the JSON.",
        NotificationBatch,
    )
    batch.composed_at = datetime.now(UTC)
    batch.alert_level = decision.alert_level
    report = _invoke_json(
        verifier,
        f"Audit this revised notification batch.\n\nDRAFT:\n{batch.model_dump_json(indent=1)}\n\n{evidence}",
        VerificationReport,
    )
    _log_verification(store, report, attempt=2)
    if report.approved:
        return batch, report, False
    return _fallback_notifications(fresh, store), report, True


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
        watch.last_checked = datetime.now(UTC)
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

    store.log_event(
        "sentinel_decision",
        {
            "triggered": decision.triggered,
            "level": decision.alert_level,
            "reasoning": decision.reasoning,
            "events": [e.title for e in fresh],
        },
    )

    # The Sentinel is a model, and a model can write 5 in a field while its own
    # reasoning says "no Level 5 signal is present" — that exact slip is in this
    # repo's flight recorder. Clamp the activation to what the official wording
    # positively supports. Only ever downward, and only when we recognise a
    # signal: an unfamiliar wording must not be able to silence a real alert.
    supported = max_supported_level([f"{e.title}\n{e.body}" for e in fresh])
    if decision.triggered and supported is not None and (decision.alert_level or 0) > supported:
        store.log_event(
            "level_clamped",
            {
                "sentinel_level": decision.alert_level,
                "supported_level": supported,
                "events": [e.title for e in fresh],
            },
        )
        decision.alert_level = supported

    if not decision.triggered or (decision.alert_level or 0) <= watch.activated_level:
        # A deliberate, journaled decision NOT to notify — the one case where
        # dedupe is safe without a dispatch.
        _record_seen(store, fresh)
        return WatchOutcome(
            processed_events=len(fresh),
            decision=decision,
            note="stand by — no step activation beyond current level",
        )

    try:
        batch, report, fallback = _compose_and_verify(store, audit, decision, household, plan, fresh)
    except Exception as exc:  # model error, unparseable JSON, schema drift…
        store.log_event(
            "error",
            {"op": "compose_verify", "level": decision.alert_level, "error": str(exc)[:400]},
        )
        if (decision.alert_level or 0) < 3:
            # Below the evacuation levels, leave the events unseen so the next
            # cycle retries them instead of dropping the signal for good.
            return WatchOutcome(
                processed_events=len(fresh),
                decision=decision,
                note=f"composition failed; events left unseen for retry: {exc}",
            )
        # Level 3+: the AI layer is down but the family must still hear the
        # official text — take the same raw-relay exit as a double rejection.
        batch, report, fallback = _fallback_notifications(fresh, store), None, True

    dispatched = 0
    try:
        for notification in batch.notifications:
            channel.send(notification, household)
            dispatched += 1
    except Exception as exc:
        # Events stay unseen: a channel that died mid-batch must be retried next
        # cycle. A duplicate notification is a nuisance; a missed one is the
        # failure mode this whole system exists to prevent.
        store.log_event(
            "error",
            {
                "op": "dispatch",
                "level": decision.alert_level,
                "dispatched": dispatched,
                "error": str(exc)[:400],
            },
        )
        raise

    _record_seen(store, fresh)

    # At Level 4+ the question changes from "did they get the message" to
    # "is everyone accounted for" — open a safety check-in board (deterministic,
    # no model involved; members respond via UI/CLI).
    if (decision.alert_level or 0) >= 4 and not store.load_checkins():
        store.save_checkins([CheckIn(member=m.name) for m in household.members])
        store.log_event("checkins_opened", {"level": decision.alert_level, "members": len(household.members)})

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

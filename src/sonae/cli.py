"""Sonae command-line interface.

    sonae onboard examples/aoki_family.json --approve
    sonae status aoki
    sonae replay aoki scenarios/hagibis_2019_nagano.json --pause
    sonae watch aoki --interval 300
    sonae journal aoki
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from sonae.channels.console import ConsoleChannel
from sonae.datasources import gsi_geocode, jma, jma_area
from sonae.datasources.replay import ReplayClock, load_scenario
from sonae.memory.store import HouseholdStore
from sonae.schemas import FamilyMember, Household


def build_household(raw: dict) -> Household:
    """Resolve the geo/JMA fields of a household intake JSON deterministically."""
    g = gsi_geocode.geocode(raw["address"])
    pref, muni = jma_area.muni_name(g.muni_code)
    area = jma_area.resolve(g.muni_code)
    return Household(
        household_id=raw["household_id"],
        address=raw["address"],
        lat=g.lat,
        lon=g.lon,
        muni_code=g.muni_code,
        muni_name=muni,
        pref_name=pref,
        jma_office_code=area.office_code,
        jma_class20_code=area.class20_code,
        members=[FamilyMember(**m) for m in raw.get("members", [])],
        home_floors=raw.get("home_floors"),
        has_car=raw.get("has_car", True),
        pets=raw.get("pets", []),
        notes=raw.get("notes"),
    )


def cmd_onboard(args: argparse.Namespace) -> int:
    from sonae.agents.onboarding import approve_plan, run_onboarding, summarize_result

    raw = json.loads(Path(args.profile).read_text())
    household = build_household(raw)
    store = HouseholdStore(household.household_id)
    print(f"Onboarding household '{household.household_id}' at {household.address} …")
    print(f"  → {household.pref_name}{household.muni_name} (muni {household.muni_code}, "
          f"JMA {household.jma_office_code}/{household.jma_class20_code})")
    result = run_onboarding(household, store)
    print(summarize_result(result))
    if args.approve:
        approve_plan(store)
        print("Plan APPROVED by family — the Sentinel is authorized to act on it.")
    else:
        print("Review the plan, then run:  sonae approve", household.household_id)
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    from sonae.agents.onboarding import approve_plan

    approve_plan(HouseholdStore(args.household))
    print("Plan approved.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = HouseholdStore(args.household)
    household = store.load_household()
    if household is None:
        print("unknown household; run onboarding first", file=sys.stderr)
        return 1
    plan = store.load_plan()
    watch = store.load_watch()
    print(f"Household: {household.household_id} — {household.address}")
    print(f"Members: {', '.join(m.name + (' (home)' if m.lives_at_home else ' (remote)') for m in household.members)}")
    if plan:
        print(f"Plan: {len(plan.steps)} steps, approved={plan.family_approved}")
        if plan.primary_shelter:
            print(f"Primary evacuation site: {plan.primary_shelter.name} ({plan.primary_shelter.distance_km} km)")
    print(f"Watch: activated level {watch.activated_level}, last checked {watch.last_checked}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    from sonae.agents.watch import process_events

    store = HouseholdStore(args.household)
    scenario = load_scenario(args.scenario)
    channel = ConsoleChannel()
    print("=" * 72)
    print(f"REPLAY: {scenario.title}")
    print(scenario.disclaimer)
    print("=" * 72)
    clock = ReplayClock(scenario)
    while not clock.exhausted:
        batch = clock.advance()
        moment = batch[0].ts.strftime("%Y-%m-%d %H:%M JST")
        print(f"\n⏱  {moment} — {len(batch)} event(s)")
        for e in batch:
            print(f"   • {e.title}")
        outcome = process_events(store, batch, channel)
        if outcome.decision and outcome.decision.triggered and outcome.dispatched:
            print(f"   → plan activated at level {outcome.decision.alert_level}; "
                  f"{outcome.dispatched} notification(s) sent"
                  + (" [FALLBACK RELAY]" if outcome.fallback_relay else " [verified]"))
        elif outcome.decision:
            print(f"   → sentinel: stand by ({outcome.decision.reasoning[:120]})")
        if args.pause and not clock.exhausted:
            input("   [Enter for next moment] ")
    print("\nReplay complete. Journal: sonae journal", args.household)
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    from sonae.agents.watch import process_events

    store = HouseholdStore(args.household)
    household = store.load_household()
    if household is None:
        print("unknown household; run onboarding first", file=sys.stderr)
        return 1
    channel = ConsoleChannel()
    print(f"Watching JMA feeds for {household.pref_name}{household.muni_name} "
          f"(office {household.jma_office_code}) every {args.interval}s. Ctrl-C to stop.")
    while True:
        events = jma.fetch_active_warnings(household.jma_office_code, household.jma_class20_code)
        outcome = process_events(store, events, channel)
        stamp = time.strftime("%H:%M:%S")
        print(f"[{stamp}] {len(events)} active signal(s); {outcome.note}")
        if args.once:
            return 0
        time.sleep(args.interval)


def cmd_checkin(args: argparse.Namespace) -> int:
    from sonae import circles

    board = circles.record_checkin(args.household, args.member, args.status, args.note)
    for c in board:
        print(f"  {c.member}: {c.status.value}" + (f" — {c.note}" if c.note else ""))
    return 0


def cmd_circle_report(args: argparse.Namespace) -> int:
    from sonae import circles

    circle = circles.load_circle(args.circle_id)
    if circle is None:
        print("unknown circle", file=sys.stderr)
        return 1
    report = circles.compose_report(circle)
    print(f"# {report.headline}\n\n{report.summary}")
    if report.needs_help:
        print("\nNEEDS HELP:")
        for x in report.needs_help:
            print(f"  ⚠ {x}")
    if report.unresponsive:
        print("\nVISIT / CALL:")
        for x in report.unresponsive:
            print(f"  👣 {x}")
    if report.next_actions:
        print("\nNEXT ACTIONS:")
        for i, x in enumerate(report.next_actions, 1):
            print(f"  {i}. {x}")
    return 0


def cmd_journal(args: argparse.Namespace) -> int:
    store = HouseholdStore(args.household)
    watch = store.load_watch()
    for entry in watch.history:
        print(json.dumps(entry, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sonae", description="Sonae — disaster-readiness agents for families")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("onboard", help="build and verify a family's hazard profile and timeline plan")
    p.add_argument("profile", help="household intake JSON (see examples/)")
    p.add_argument("--approve", action="store_true", help="record family approval immediately")
    p.set_defaults(func=cmd_onboard)

    p = sub.add_parser("approve", help="record the family's approval of the current plan")
    p.add_argument("household")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("status", help="show household, plan, and watch state")
    p.add_argument("household")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("replay", help="drive the watch pipeline with a historical scenario")
    p.add_argument("household")
    p.add_argument("scenario")
    p.add_argument("--pause", action="store_true", help="wait for Enter between moments (demo pacing)")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("watch", help="watch live JMA feeds for this household")
    p.add_argument("household")
    p.add_argument("--interval", type=int, default=300)
    p.add_argument("--once", action="store_true")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("checkin", help="record a family member's safety check-in")
    p.add_argument("household")
    p.add_argument("member")
    p.add_argument("status", choices=["safe", "needs_help", "no_response"])
    p.add_argument("--note")
    p.set_defaults(func=cmd_checkin)

    p = sub.add_parser("circle-report", help="compose the neighborhood coordinator's safety report")
    p.add_argument("circle_id")
    p.set_defaults(func=cmd_circle_report)

    p = sub.add_parser("journal", help="print the household's agent flight-recorder journal")
    p.add_argument("household")
    p.set_defaults(func=cmd_journal)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

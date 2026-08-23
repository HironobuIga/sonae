"""Seed demo fixtures for UI development and the neighborhood-circle demo.

SAFETY: this script NEVER overwrites a real (agent-generated) plan unless
--force is passed. With a real plan present, only the additive parts run
(neighborhood circle fixtures).

    uv run python scripts/seed_demo.py [--mid-storm] [--circle] [--force]

--mid-storm  set watch to Level 3 with sample notifications (UI design work;
             requires no real plan, or --force)
--circle     create the Naganuma neighborhood circle: 5 fixture neighbor
             households with mixed check-in states (additive; the Coordinator
             agent composes its report from this board — board data is demo
             input, the report is real agent output)
--force      allow overwriting a real plan with fixtures
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

sys.path.insert(0, "src")

from sonae.cli import build_household  # noqa: E402
from sonae.datasources import gsi_hazard, gsi_shelters  # noqa: E402
from sonae.memory.store import HouseholdStore  # noqa: E402
from sonae.schemas import (  # noqa: E402
    CheckIn,
    CheckInStatus,
    Circle,
    FamilyMember,
    HazardAssessment,
    HazardProfile,
    HazardType,
    Household,
    Notification,
    Source,
    TimelineAction,
    TimelinePlan,
    TimelineStep,
)


def seed_fixture_plan(store: HouseholdStore, household: Household) -> None:
    """Fixture hazard profile + plan (real data facts, handcrafted plan text)."""
    depth = gsi_hazard.lookup_depth(HazardType.flood, household.lat, household.lon)
    landslide = gsi_hazard.lookup_landslide(household.lat, household.lon)
    muni = household.pref_name + household.muni_name
    flood_sites = gsi_shelters.nearest_shelters(
        household.lat, household.lon, muni, hazard=HazardType.flood, limit=5
    )
    quake_sites = gsi_shelters.nearest_shelters(
        household.lat, household.lon, muni, hazard=HazardType.earthquake, limit=3
    )
    hazard_src = gsi_hazard.hazard_source()
    profile = HazardProfile(
        household_id=household.household_id,
        assessments=[
            HazardAssessment(
                hazard=HazardType.flood,
                at_risk=depth is not None,
                severity=f"expected flood depth {depth.label_en} ({depth.label_ja})" if depth else None,
                sources=[hazard_src],
            ),
            HazardAssessment(
                hazard=HazardType.landslide,
                at_risk=bool(landslide),
                severity="; ".join(landslide) if landslide else None,
                sources=[hazard_src],
            ),
            HazardAssessment(
                hazard=HazardType.earthquake,
                at_risk=True,
                severity="baseline seismic risk; earthquake-suitable sites differ from flood sites",
                sources=[Source(name="GSI designated evacuation site data", url="https://hinanmap.gsi.go.jp/")],
            ),
        ],
        nearest_shelters=flood_sites
        + [s for s in quake_sites if s.name not in {x.name for x in flood_sites}],
        river_names=["千曲川 (Chikuma River)"],
        summary=(
            "FIXTURE (UI preview): home in the Chikuma River inundation zone, expected depth "
            f"{depth.label_en if depth else 'n/a'}. Horizontal evacuation only; nearest flood-safe site "
            f"{flood_sites[0].name} ({flood_sites[0].distance_km} km)."
        ),
        assessed_at=datetime.now(UTC),
        caveats=[gsi_shelters.DATA_CAVEAT],
    )
    store.save_hazard_profile(profile)
    plan = TimelinePlan(
        household_id=household.household_id,
        hazard_focus=[HazardType.flood],
        steps=[
            TimelineStep(
                alert_level=level,
                trigger=trigger,
                headline=headline,
                actions=[TimelineAction(member=m, description=d, estimated_minutes=e) for m, d, e in actions],
            )
            for level, trigger, headline, actions in [
                (1, "早期注意情報 issued", "Get ready while the sky is clear",
                 [("Yoshiko", "Charge phone; put medication in the go-bag", 15),
                  ("Kenji", "Call Mom, confirm the go-bag is by the door", 10)]),
                (2, "大雨・洪水注意報 / 氾濫注意情報", "Prepare to move early",
                 [("Yoshiko", "Valuables upstairs; shoes and raincoat at the entrance", 20),
                  ("Mika", "Check transport options to the evacuation site", 15)]),
                (3, "氾濫警戒情報 / 高齢者等避難", "Yoshiko starts evacuating NOW",
                 [("Yoshiko", "Leave for 北部スポーツ・レクリエーションパーク (allow 45 min)", 45),
                  ("Kenji", "Call Mom, stay on the line until she is out the door", 20)]),
                (4, "避難指示 / 氾濫危険情報", "Everyone confirms Yoshiko is OUT",
                 [("Kenji", "Verify Mom is at the site; else call the city disaster line", 10)]),
                (5, "氾濫発生情報 / 特別警報", "Life-saving action only",
                 [("Yoshiko", "If not evacuated: highest nearby building immediately", 5)]),
            ]
        ],
        primary_shelter=flood_sites[0],
        backup_shelter=flood_sites[1] if len(flood_sites) > 1 else None,
        vertical_evacuation_ok=False,
        supply_checklist=["Water 3 days", "Medication", "Charger", "Cash", "Flashlight"],
        sources=[hazard_src],
        created_at=datetime.now(UTC),
        family_approved=True,
    )
    store.save_plan(plan)
    print(f"fixture plan: {len(plan.steps)} steps, primary={plan.primary_shelter.name}")


def seed_mid_storm(store: HouseholdStore, household: Household) -> None:
    from sonae.channels.inbox import InboxChannel

    inbox = InboxChannel(store)
    inbox.clear()
    watch = store.load_watch()
    watch.activated_level = 3
    store.save_watch(watch)
    src = Source(name="千曲川洪水予報第3号 (JMA/MLIT)", url="https://www.jma.go.jp/bosai/")
    inbox.send(Notification(
        to_member="Yoshiko",
        subject="【そなえ】警戒レベル3・そろそろ避難を始めましょう",
        body=(
            "よしこさん、千曲川に氾濫警戒情報が出ました。\n\n1. 玄関のリュックを持つ\n"
            "2. 北部スポーツ・レクリエーションパークへ出発\n3. 着いたら賢治さんに電話\n\n"
            "まだ明るいうちに、ゆっくりで大丈夫です。"
        ),
        citations=[src], urgent=True), household)
    inbox.send(Notification(
        to_member="Kenji",
        subject="[Sonae] L3 activated — call your mother now",
        body=(
            "17:30 JST: Flood WARNING issued for the Chikuma River.\n"
            "• Call Mom now, stay on the line\n• Report back when she is en route"
        ),
        citations=[src], urgent=True), household)
    print("mid-storm fixture state: L3 + notifications")


def seed_circle(store: HouseholdStore, household: Household) -> None:
    from sonae.circles import save_circle

    neighbors = [
        ("sato", "佐藤", [("Hiroshi", 81, "safe", None), ("Fumiko", 79, "safe", None)]),
        ("tanaka", "田中", [("Kazuo", 74, "needs_help", "knee injury, cannot walk to shelter")]),
        ("suzuki", "鈴木", [("Megumi", 45, "safe", None), ("Ren", 12, "safe", None)]),
        ("takahashi", "高橋", [("Isamu", 88, "pending", None)]),
        ("watanabe", "渡辺", [("Sachi", 70, "no_response", None), ("Goro", 72, "no_response", None)]),
    ]
    ids = [household.household_id]
    for i, (hid, name_ja, members) in enumerate(neighbors):
        n_store = HouseholdStore(hid)
        n_store.save_household(Household(
            household_id=hid,
            address=f"長野県長野市穂保 {name_ja}宅",
            lat=household.lat + (i - 2) * 0.0016,
            lon=household.lon + (i - 2) * 0.0011,
            muni_code=household.muni_code, muni_name=household.muni_name,
            pref_name=household.pref_name, jma_office_code=household.jma_office_code,
            jma_class20_code=household.jma_class20_code,
            members=[FamilyMember(name=n, age=a, needs=(["mobility-limited"] if a >= 80 else []))
                     for n, a, _, _ in members],
        ))
        n_store.save_checkins([
            CheckIn(member=n, status=CheckInStatus(s), note=note, updated_at=datetime.now(UTC))
            for n, _, s, note in members
        ])
        w = n_store.load_watch()
        w.activated_level = 4
        n_store.save_watch(w)
        ids.append(hid)
    save_circle(Circle(
        circle_id="naganuma",
        name="長沼地区自主防災会 (Naganuma District Disaster-Prevention Circle)",
        coordinator="田村会長 (Chairman Tamura)",
        household_ids=ids,
    ))
    print(f"circle 'naganuma' seeded with {len(ids)} households")


def main() -> None:
    raw = json.loads(open("examples/aoki_family.json").read())
    household = build_household(raw)
    store = HouseholdStore(household.household_id)

    profile = store.load_hazard_profile()
    real_plan_present = store.load_plan() is not None and "FIXTURE" not in ((profile.summary if profile else "") or "")
    allow_fixtures = "--force" in sys.argv or not real_plan_present

    if store.load_household() is None:
        store.save_household(household)
        print(f"household: {household.address} -> {household.lat},{household.lon}")

    if allow_fixtures:
        seed_fixture_plan(store, household)
        if "--mid-storm" in sys.argv:
            seed_mid_storm(store, household)
    else:
        print("REAL plan present for 'aoki' — fixture/mid-storm sections SKIPPED (use --force to overwrite).")

    if "--circle" in sys.argv:
        seed_circle(store, household)

    print("done.")


if __name__ == "__main__":
    main()

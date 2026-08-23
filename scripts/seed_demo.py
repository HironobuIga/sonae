"""Seed a realistic household store for UI development and screenshots.

Uses the real data layer (geocoding, hazard tiles, shelter data) for every
fact; the plan/notification texts are handcrafted fixtures standing in for
agent output until a model provider is configured. Clearly labeled — the
live pipeline overwrites all of this.

    uv run python scripts/seed_demo.py [--mid-storm]

--mid-storm additionally sets the watch to Level 3 with notifications in
each phone, replicating the state mid-replay (for design work).
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
    HazardAssessment,
    HazardProfile,
    HazardType,
    Notification,
    Source,
    TimelineAction,
    TimelinePlan,
    TimelineStep,
)

MID_STORM = "--mid-storm" in sys.argv

raw = json.loads(open("examples/aoki_family.json").read())
household = build_household(raw)
store = HouseholdStore(household.household_id)
store.save_household(household)
print(f"household: {household.address} -> {household.lat},{household.lon}")

# --- hazard profile from the real data layer --------------------------------
depth = gsi_hazard.lookup_depth(HazardType.flood, household.lat, household.lon)
landslide = gsi_hazard.lookup_landslide(household.lat, household.lon)
muni = household.pref_name + household.muni_name
flood_sites = gsi_shelters.nearest_shelters(household.lat, household.lon, muni, hazard=HazardType.flood, limit=5)
quake_sites = gsi_shelters.nearest_shelters(household.lat, household.lon, muni, hazard=HazardType.earthquake, limit=3)

hazard_src = gsi_hazard.hazard_source()
assessments = [
    HazardAssessment(
        hazard=HazardType.flood,
        at_risk=depth is not None,
        severity=f"expected flood depth {depth.label_en} ({depth.label_ja})" if depth else None,
        detail="Largest-scale statutory inundation scenario for the Chikuma River system.",
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
        severity="baseline seismic risk; earthquake-suitable evacuation sites differ from flood sites",
        sources=[Source(name="GSI designated evacuation site data", url="https://hinanmap.gsi.go.jp/")],
    ),
]

profile = HazardProfile(
    household_id=household.household_id,
    assessments=assessments,
    nearest_shelters=flood_sites + [s for s in quake_sites if s.name not in {x.name for x in flood_sites}],
    river_names=["千曲川 (Chikuma River)"],
    summary=(
        "This home sits in the Chikuma River inundation zone with an expected flood depth of "
        f"{depth.label_en if depth else 'n/a'} — deeper than a two-story house. Upper floors are NOT a refuge here; "
        "horizontal evacuation before roads flood is the only safe plan. Nearest flood-safe site: "
        f"{flood_sites[0].name} ({flood_sites[0].distance_km} km)."
    ),
    assessed_at=datetime.now(UTC),
    caveats=[gsi_shelters.DATA_CAVEAT],
)
store.save_hazard_profile(profile)
print(f"profile: flood={profile.assessments[0].severity}, {len(profile.nearest_shelters)} shelters")

# --- fixture plan (stands in for Planner output until a model is wired) ------
jma_src = Source(name="JMA warning feed", url="https://www.jma.go.jp/bosai/")
plan = TimelinePlan(
    household_id=household.household_id,
    hazard_focus=[HazardType.flood],
    steps=[
        TimelineStep(
            alert_level=1, trigger="Typhoon/heavy-rain outlook announced for Nagano (早期注意情報)",
            headline="Get ready while the sky is clear",
            actions=[
                TimelineAction(member="Yoshiko", description="Charge phone; put medication and insurance card in the go-bag", estimated_minutes=15),
                TimelineAction(member="Kenji", description="Call Mom, confirm the go-bag is packed and by the door", estimated_minutes=10),
            ],
        ),
        TimelineStep(
            alert_level=2, trigger="Heavy rain / flood advisory for Nagano City (大雨・洪水注意報)",
            headline="Prepare to move early",
            actions=[
                TimelineAction(member="Yoshiko", description="Put valuables upstairs; set shoes and raincoat at the entrance", estimated_minutes=20),
                TimelineAction(member="Mika", description="Check bus/taxi options to the evacuation site; brief the neighbor", estimated_minutes=15),
            ],
        ),
        TimelineStep(
            alert_level=3, trigger="氾濫警戒情報 for the Chikuma River OR 高齢者等避難 for Nagano City",
            headline="Yoshiko starts evacuating NOW — this level exists for her",
            actions=[
                TimelineAction(member="Yoshiko", description="Leave for 北部スポーツ・レクリエーションパーク with the go-bag (allow 45 min for the walk — knees)", estimated_minutes=45),
                TimelineAction(member="Kenji", description="Call Mom and stay on the line until she is out the door; arrange the neighbor's car if it is raining hard", estimated_minutes=20),
                TimelineAction(member="Mika", description="Confirm arrival at the site; report status in the family chat", estimated_minutes=10),
            ],
        ),
        TimelineStep(
            alert_level=4, trigger="避難指示 for Naganuma/Hoyasu OR 氾濫危険情報 (Tategahana gauge)",
            headline="Everyone confirms Yoshiko is OUT — no one enters the zone",
            actions=[
                TimelineAction(member="Kenji", description="Verify Mom is at the evacuation site; if not, call 026-xxx and the neighbor immediately", estimated_minutes=10),
                TimelineAction(member="Mika", description="Stop any plan to drive toward Naganuma; monitor official updates only", estimated_minutes=5),
            ],
        ),
        TimelineStep(
            alert_level=5, trigger="氾濫発生情報 / 大雨特別警報 (life-threatening situation)",
            headline="Life-saving action only",
            actions=[
                TimelineAction(member="Yoshiko", description="If NOT yet evacuated: do not travel far — go to the highest nearby building immediately", estimated_minutes=5),
                TimelineAction(member="Kenji", description="Call 119 only for life-threatening emergency; keep the line free otherwise", estimated_minutes=5),
            ],
        ),
    ],
    primary_shelter=flood_sites[0],
    backup_shelter=flood_sites[1] if len(flood_sites) > 1 else None,
    vertical_evacuation_ok=False,
    supply_checklist=[
        "Drinking water 3 days (9 L)", "Yoshiko's knee & blood-pressure medication (1 week)",
        "Phone charger + battery", "Cash (small bills)", "Insurance/ID copies in waterproof bag",
        "Flashlight + spare batteries", "Warm layer and rain poncho",
    ],
    sources=[hazard_src, jma_src, Source(name="Cabinet Office: My-Timeline guidance", url="https://www.bousai.go.jp/")],
    created_at=datetime.now(UTC),
    family_approved=True,
)
store.save_plan(plan)
print(f"plan: {len(plan.steps)} steps, primary={plan.primary_shelter.name}")

# --- journal + optional mid-storm state --------------------------------------
store.log_event("onboarding_complete", {"nodes_executed": ["cartographer", "planner", "verifier"], "hazards_at_risk": ["flood"], "checks": 9})
store.log_event("plan_approved", {"by": "family"})

if MID_STORM:
    from sonae.channels.inbox import InboxChannel
    from sonae.schemas import Household  # noqa: F401

    inbox = InboxChannel(store)
    inbox.clear()
    watch = store.load_watch()
    watch.activated_level = 3
    store.save_watch(watch)
    store.log_event("replay_moment", {"sim_time": "2019-10-12T17:30:00+09:00", "events": ["Chikuma River flood forecast #3: flood WARNING (氾濫警戒情報)"]})
    store.log_event("sentinel_decision", {"triggered": True, "level": 3, "reasoning": "氾濫警戒情報 for the Kuisege gauge is a Level-3-equivalent signal for the Chikuma riverside; the plan's L3 step names this exact trigger for Yoshiko's early evacuation.", "events": ["Chikuma River flood forecast #3"]})
    inbox.send(Notification(
        to_member="Yoshiko",
        subject="【そなえ】警戒レベル3・そろそろ避難を始めましょう",
        body="よしこさん、千曲川に氾濫警戒情報が出ました。\n\n1. 玄関のリュックを持つ\n2. 北部スポーツ・レクリエーションパークへ出発(歩いて45分)\n3. 着いたら賢治さんに電話\n\nまだ明るいうちに、ゆっくりで大丈夫です。",
        citations=[Source(name="千曲川洪水予報第3号 (JMA/MLIT)", url="https://www.jma.go.jp/bosai/")], urgent=True), household)
    inbox.send(Notification(
        to_member="Kenji",
        subject="[Sonae] L3 activated — call your mother now",
        body="17:30 JST: Flood WARNING (氾濫警戒情報) issued for the Chikuma River — the Kuisege gauge is forecast to reach danger level around 19:00.\n\nYour tasks:\n• Call Mom now, stay on the line until she leaves\n• If rain is heavy, call the Satos about their car\n• Report back when she is en route",
        citations=[Source(name="Chikuma River flood forecast #3 (JMA/MLIT)", url="https://www.jma.go.jp/bosai/")], urgent=True), household)
    inbox.send(Notification(
        to_member="Mika",
        subject="[Sonae] L3 activated — confirm arrival",
        body="Yoshiko is starting her evacuation to 北部スポーツ・レクリエーションパーク (2.6 km). Confirm her arrival by phone and post status in the family chat. Do not travel toward Naganuma tonight.",
        citations=[Source(name="Chikuma River flood forecast #3 (JMA/MLIT)", url="https://www.jma.go.jp/bosai/")], urgent=False), household)
    store.log_event("notifications_sent", {"level": 3, "count": 3, "verified": True, "fallback_relay": False})
    print("mid-storm state: L3 + 3 notifications")

print("seeded. Run: uv run uvicorn sonae.web.app:app --port 8000")

"""Domain models shared by every Sonae agent.

These schemas are the contract between the deterministic data layer
(datasources/*), the LLM agents (agents/*), and the delivery channels.
Structured output from agents is validated against these models, so a
hallucinated field name fails loudly instead of reaching a family's phone.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class HazardType(str, Enum):
    """Hazard categories used by GSI shelter data and hazard-map layers."""

    flood = "flood"  # 洪水 (river flooding)
    landslide = "landslide"  # 崖崩れ・土石流・地滑り
    storm_surge = "storm_surge"  # 高潮
    earthquake = "earthquake"  # 地震
    tsunami = "tsunami"  # 津波
    large_fire = "large_fire"  # 大規模な火事
    inland_flood = "inland_flood"  # 内水氾濫
    volcano = "volcano"  # 火山現象


class Source(BaseModel):
    """A citation to an official document or dataset.

    Every user-facing claim Sonae makes must carry at least one Source.
    """

    name: str = Field(description="Human-readable source name, e.g. 'JMA warning feed'")
    url: str = Field(description="URL of the official source")
    note: str | None = Field(default=None, description="Page, section, or retrieval detail")
    retrieved_at: datetime | None = None


# ---------------------------------------------------------------------------
# Household
# ---------------------------------------------------------------------------


class FamilyMember(BaseModel):
    name: str
    age: int | None = None
    lives_at_home: bool = Field(
        default=True, description="False for remote family members who watch over the household"
    )
    needs: list[str] = Field(
        default_factory=list,
        description="Mobility / medical / language needs, e.g. 'bad knees, walking takes 3x longer'",
    )
    preferred_language: str = Field(default="ja", description="Language for notifications: 'ja' or 'en'")
    phone_available: bool = True


class Household(BaseModel):
    """One watched home. The unit Sonae protects."""

    household_id: str
    address: str
    lat: float
    lon: float
    muni_code: str = Field(description="5-digit municipality code, e.g. '20201' for Nagano City")
    muni_name: str
    pref_name: str
    jma_office_code: str = Field(description="JMA office area code, e.g. '200000' for Nagano Pref.")
    jma_class20_code: str | None = Field(
        default=None, description="JMA class20 (municipality-level) area code, e.g. '2020100'"
    )
    members: list[FamilyMember] = Field(default_factory=list)
    home_floors: int | None = Field(default=None, description="Number of floors, for vertical evacuation")
    has_car: bool = True
    pets: list[str] = Field(default_factory=list)
    notes: str | None = None


# ---------------------------------------------------------------------------
# Hazard profile (Cartographer output)
# ---------------------------------------------------------------------------


class HazardAssessment(BaseModel):
    hazard: HazardType
    at_risk: bool
    severity: str | None = Field(
        default=None,
        description="Severity read from official hazard maps, e.g. 'expected flood depth 3–5 m'",
    )
    detail: str | None = None
    sources: list[Source] = Field(default_factory=list)


class Shelter(BaseModel):
    name: str
    address: str
    lat: float
    lon: float
    distance_km: float
    suitable_for: list[HazardType] = Field(
        description="Hazard types this designated emergency evacuation site covers"
    )
    is_designated_shelter: bool = Field(
        default=False, description="True if also a 指定避難所 (mid-term shelter), not only an evacuation site"
    )
    source: Source | None = None


class HazardProfile(BaseModel):
    household_id: str
    assessments: list[HazardAssessment]
    nearest_shelters: list[Shelter]
    river_names: list[str] = Field(
        default_factory=list, description="Flood-forecast rivers relevant to this home, e.g. '千曲川 (Chikuma River)'"
    )
    summary: str = Field(description="Plain-language summary of what this home should worry about")
    assessed_at: datetime
    caveats: list[str] = Field(
        default_factory=list,
        description="Mandatory data caveats, e.g. 'shelter data may lag municipal updates'",
    )


# ---------------------------------------------------------------------------
# The plan (Planner output) — a My-Timeline the family approves in advance
# ---------------------------------------------------------------------------


class TimelineAction(BaseModel):
    member: str = Field(description="Family member responsible")
    description: str
    estimated_minutes: int | None = None


class TimelineStep(BaseModel):
    alert_level: int = Field(ge=1, le=5, description="JMA/Cabinet Office alert level (警戒レベル) 1–5")
    trigger: str = Field(description="Official signal that activates this step, e.g. 'Level 3 高齢者等避難 issued'")
    headline: str
    actions: list[TimelineAction]


class TimelinePlan(BaseModel):
    household_id: str
    hazard_focus: list[HazardType]
    steps: list[TimelineStep]
    primary_shelter: Shelter | None = None
    backup_shelter: Shelter | None = None
    vertical_evacuation_ok: bool = Field(
        default=False,
        description="Whether staying on an upper floor is an acceptable fallback for this home",
    )
    supply_checklist: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    created_at: datetime
    family_approved: bool = False


# ---------------------------------------------------------------------------
# Watch phase (Sentinel input/output)
# ---------------------------------------------------------------------------


class FeedEventKind(str, Enum):
    jma_warning = "jma_warning"
    jma_forecast = "jma_forecast"
    river_flood_forecast = "river_flood_forecast"
    evacuation_info = "evacuation_info"  # municipal 避難情報 (Level 3/4/5)
    earthquake = "earthquake"


class FeedEvent(BaseModel):
    ts: datetime
    kind: FeedEventKind
    area_code: str | None = None
    area_name: str | None = None
    title: str
    body: str
    source: Source


class SentinelDecision(BaseModel):
    """Structured verdict of the Sentinel agent for a batch of feed events."""

    triggered: bool = Field(description="Whether the family's timeline should advance")
    alert_level: int | None = Field(default=None, ge=1, le=5)
    matched_step_headline: str | None = None
    reasoning: str
    citations: list[Source] = Field(default_factory=list)


class Notification(BaseModel):
    to_member: str
    subject: str
    body: str
    citations: list[Source] = Field(default_factory=list)
    urgent: bool = False


class NotificationBatch(BaseModel):
    household_id: str
    alert_level: int | None = None
    notifications: list[Notification]
    composed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Verification gate (Verifier output)
# ---------------------------------------------------------------------------


class ClaimCheck(BaseModel):
    claim: str
    source_quote: str | None = Field(
        default=None, description="Verbatim text from the official source backing the claim"
    )
    verdict: str = Field(description="'supported' | 'unsupported' | 'uncertain'")


class VerificationReport(BaseModel):
    approved: bool
    checks: list[ClaimCheck]
    revision_request: str | None = Field(
        default=None, description="If not approved: what must be fixed before sending"
    )


# ---------------------------------------------------------------------------
# Safety check-in (post-event)
# ---------------------------------------------------------------------------


class CheckInStatus(str, Enum):
    safe = "safe"
    needs_help = "needs_help"
    no_response = "no_response"
    pending = "pending"


class CheckIn(BaseModel):
    member: str
    status: CheckInStatus = CheckInStatus.pending
    note: str | None = None
    updated_at: datetime | None = None

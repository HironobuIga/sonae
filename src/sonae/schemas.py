"""Domain models shared by every Sonae agent.

These schemas are the contract between the deterministic data layer
(datasources/*), the LLM agents (agents/*), and the delivery channels.
Structured output from agents is validated against these models, so a
hallucinated field name fails loudly instead of reaching a family's phone.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
    jma_class20_candidates: list[str] = Field(
        default_factory=list,
        description=(
            "Every class20 area that could cover this home. Populated only when the "
            "municipality splits into several JMA areas and the home could not be "
            "pinned to one of them — all of them are then watched."
        ),
    )
    members: list[FamilyMember] = Field(default_factory=list)
    home_floors: int | None = Field(default=None, description="Number of floors, for vertical evacuation")
    has_car: bool = True
    pets: list[str] = Field(default_factory=list)
    notes: str | None = None

    @property
    def watch_area_codes(self) -> list[str]:
        """Class20 areas whose warnings apply to this home.

        Every candidate when area resolution was ambiguous — watching one area
        too many costs a redundant alert; watching one too few costs silence.
        """
        if self.jma_class20_candidates:
            return list(self.jma_class20_candidates)
        return [self.jma_class20_code] if self.jma_class20_code else []


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
    family_approved: bool = Field(
        default=False,
        description=(
            "Human-in-the-loop sign-off. Set ONLY by agents.onboarding.approve_plan(); "
            "it is never part of what the Planner is asked to produce, and any value a "
            "model emits for it is discarded before the plan is stored."
        ),
    )


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


Verdict = Literal["supported", "unsupported", "uncertain"]


class ClaimCheck(BaseModel):
    claim: str
    source_quote: str | None = Field(
        default=None, description="Verbatim text from the official source backing the claim"
    )
    verdict: Verdict = Field(description="'supported' | 'unsupported' | 'uncertain'")

    @field_validator("verdict", mode="before")
    @classmethod
    def _normalize_verdict(cls, value: object) -> object:
        """Map free-text verdicts (older stored reports, creative models) onto the
        three allowed values. Anything unrecognized becomes 'uncertain' — never
        'supported', so a fuzzy word can't smuggle a claim past the gate."""
        if not isinstance(value, str):
            return value
        v = value.strip().lower()
        if v in ("supported", "unsupported", "uncertain"):
            return v
        if v.startswith("unsupport") or v in ("contradicted", "false", "fail", "failed", "rejected"):
            return "unsupported"
        if v.startswith("support") or v in ("ok", "pass", "passed", "true", "verified"):
            return "supported"
        return "uncertain"


class VerificationReport(BaseModel):
    """A verifier's audit of a draft. Approval is checked against the evidence.

    `approved` used to be whatever boolean the model felt like emitting, while
    both pipelines gated dispatch on it alone — an empty `checks` list with
    `"approved": true` waved a draft straight through. Approval is now
    recomputed on every validation (including reports read back from disk) and
    the recomputation can only ever WITHHOLD it: a report stands approved only
    if the verifier said so AND something was actually checked AND nothing came
    back unsupported. Anything else fails closed.
    """

    approved: bool = False
    checks: list[ClaimCheck]
    revision_request: str | None = Field(
        default=None, description="If not approved: what must be fixed before sending"
    )

    @model_validator(mode="after")
    def _derive_approval(self) -> VerificationReport:
        self.approved = (
            self.approved and bool(self.checks) and all(c.verdict != "unsupported" for c in self.checks)
        )
        return self


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


# ---------------------------------------------------------------------------
# Neighborhood circle (自主防災会 / neighborhood association mode)
# ---------------------------------------------------------------------------


class Circle(BaseModel):
    """A neighborhood disaster-prevention circle: households watched together."""

    circle_id: str
    name: str
    coordinator: str = Field(description="Name of the coordinator (会長/班長)")
    household_ids: list[str]


class CircleReport(BaseModel):
    """Coordinator agent's consolidated safety report for the circle."""

    headline: str = Field(description="One-line status, e.g. '14 of 17 confirmed safe'")
    summary: str = Field(description="3–6 plain sentences for the coordinator")
    needs_help: list[str] = Field(default_factory=list, description="'household/member — note' entries")
    unresponsive: list[str] = Field(default_factory=list, description="'household/member' entries to visit/call")
    next_actions: list[str] = Field(default_factory=list, description="Concrete ordered actions for the coordinator")

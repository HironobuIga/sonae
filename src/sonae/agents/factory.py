"""Construction of Sonae's agent team.

Each factory returns a fresh `strands.Agent`. The JSON schema each agent
must emit is appended to its system prompt at build time, so the Graph can
pass plain text between nodes while downstream code validates with Pydantic.
"""

from __future__ import annotations

from strands import Agent

from sonae.agents import prompts
from sonae.agents.audit import AuditHook
from sonae.agents.jsonio import schema_block
from sonae.config import make_model
from sonae.schemas import (
    CircleReport,
    HazardProfile,
    NotificationBatch,
    SentinelDecision,
    TimelinePlan,
    VerificationReport,
)
from sonae.tools.gov_data_tools import (
    assess_hazards_at_point,
    find_evacuation_sites,
    geocode_address,
)

_GOV_TOOLS = [geocode_address, assess_hazards_at_point, find_evacuation_sites]


def _with_schema(prompt: str, model_cls) -> str:
    return f"{prompt}\nThe JSON schema of your required output ({model_cls.__name__}):\n{schema_block(model_cls)}"


def make_cartographer(audit: AuditHook | None = None) -> Agent:
    return Agent(
        name="cartographer",
        description="Builds a home's hazard profile from statutory hazard maps and shelter data",
        model=make_model(),
        system_prompt=_with_schema(prompts.CARTOGRAPHER, HazardProfile),
        tools=list(_GOV_TOOLS),
        hooks=[audit] if audit else None,
        callback_handler=None,
    )


def make_planner(audit: AuditHook | None = None) -> Agent:
    return Agent(
        name="planner",
        description="Designs the family's My-Timeline evacuation plan",
        model=make_model(),
        system_prompt=_with_schema(prompts.PLANNER, TimelinePlan),
        hooks=[audit] if audit else None,
        callback_handler=None,
    )


def make_verifier(audit: AuditHook | None = None, *, with_tools: bool = True) -> Agent:
    """Verifier for onboarding re-derives facts with the same official-data tools.

    For the watch pipeline (with_tools=False) evidence is passed in the prompt
    (the feed events themselves) and no tools are needed.
    """
    return Agent(
        name="verifier",
        description="Adversarial fact-checker; audits drafts against official data before anything ships",
        model=make_model(),
        system_prompt=_with_schema(prompts.VERIFIER, VerificationReport),
        tools=list(_GOV_TOOLS) if with_tools else None,
        hooks=[audit] if audit else None,
        callback_handler=None,
    )


def make_sentinel(audit: AuditHook | None = None) -> Agent:
    return Agent(
        name="sentinel",
        description="Watch officer; decides if official feed events activate the family plan",
        model=make_model(),
        system_prompt=_with_schema(prompts.SENTINEL, SentinelDecision),
        hooks=[audit] if audit else None,
        callback_handler=None,
    )


def make_coordinator(audit: AuditHook | None = None) -> Agent:
    return Agent(
        name="coordinator",
        description="Consolidates neighborhood safety check-ins into an actionable coordinator report",
        model=make_model(),
        system_prompt=_with_schema(prompts.COORDINATOR, CircleReport),
        hooks=[audit] if audit else None,
        callback_handler=None,
    )


def make_messenger(audit: AuditHook | None = None) -> Agent:
    return Agent(
        name="messenger",
        description="Composes per-member family notifications in each member's language",
        model=make_model(),
        system_prompt=_with_schema(prompts.MESSENGER, NotificationBatch),
        hooks=[audit] if audit else None,
        callback_handler=None,
    )

"""Onboarding pipeline: address in, verified family evacuation plan out.

Wired as a Strands Graph with a self-correcting verification loop:

    cartographer ──▶ planner ──▶ verifier
                       ▲             │
                       └──(rejected)─┘

- Cartographer reads statutory hazard maps + shelter data (tools).
- Planner turns the hazard profile into a My-Timeline for THIS family.
- Verifier re-derives every factual claim with the same official-data tools
  and rejects the plan back to the Planner until claims are supported.

The graph terminates when the Verifier approves (its outbound edge condition
becomes false) or when the node-execution cap is hit.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from strands.multiagent.graph import GraphState

from sonae.agents import factory
from sonae.agents.audit import AuditHook
from sonae.agents.jsonio import AgentOutputError, parse_as
from sonae.memory.store import HouseholdStore
from sonae.schemas import HazardProfile, Household, TimelinePlan, VerificationReport

MAX_NODE_EXECUTIONS = 8


def _needs_revision(state: GraphState) -> bool:
    """Edge condition: route verifier -> planner only when the report rejects."""
    node_result = state.results.get("verifier")
    if node_result is None:
        return False
    try:
        report = parse_as(VerificationReport, str(node_result))
    except AgentOutputError:
        return True  # unparseable verification = not approved
    return not report.approved


def build_onboarding_graph(store: HouseholdStore):
    from strands.multiagent.graph import GraphBuilder

    audit = AuditHook(store)
    builder = GraphBuilder()
    builder.add_node(factory.make_cartographer(audit), "cartographer")
    builder.add_node(factory.make_planner(audit), "planner")
    builder.add_node(factory.make_verifier(audit, with_tools=True), "verifier")
    builder.add_edge("cartographer", "planner")
    builder.add_edge("planner", "verifier")
    builder.add_edge("verifier", "planner", condition=_needs_revision)
    builder.set_entry_point("cartographer")
    builder.reset_on_revisit(True)
    builder.set_max_node_executions(MAX_NODE_EXECUTIONS)
    return builder.build()


def _task(household: Household) -> str:
    return (
        "Build this household's hazard profile and family evacuation timeline.\n"
        "Cartographer: assess the home below. Planner: design the My-Timeline "
        "(if a verification report with a revision_request is present in your "
        "input, apply it). Verifier: audit the plan against official data.\n\n"
        f"Household JSON:\n{household.model_dump_json(indent=1)}\n\n"
        f"Current date: {datetime.now(timezone.utc).date().isoformat()}"
    )


class OnboardingResult:
    def __init__(
        self,
        profile: HazardProfile,
        plan: TimelinePlan,
        report: VerificationReport,
        node_history: list[str],
    ):
        self.profile = profile
        self.plan = plan
        self.report = report
        self.node_history = node_history


def run_onboarding(household: Household, store: HouseholdStore) -> OnboardingResult:
    """Run the full onboarding graph and persist the verified results."""
    store.save_household(household)
    graph = build_onboarding_graph(store)
    result = graph(_task(household))

    node_history = [n.node_id for n in result.execution_order]
    profile = parse_as(HazardProfile, str(result.results["cartographer"]))
    plan = parse_as(TimelinePlan, str(result.results["planner"]))
    report = parse_as(VerificationReport, str(result.results["verifier"]))

    # Belt and braces: even under the execution cap, never persist a plan the
    # verifier did not approve.
    if not report.approved:
        raise RuntimeError(
            "verification did not converge; last revision request: "
            f"{report.revision_request or 'n/a'}"
        )

    store.save_hazard_profile(profile)
    store.save_plan(plan)
    store.log_event(
        "onboarding_complete",
        {
            "nodes_executed": node_history,
            "hazards_at_risk": [a.hazard.value for a in profile.assessments if a.at_risk],
            "checks": len(report.checks),
        },
    )
    return OnboardingResult(profile, plan, report, node_history)


def approve_plan(store: HouseholdStore) -> TimelinePlan:
    """Record the family's sign-off — the human-in-the-loop moment that
    authorizes the Sentinel to act on this plan without further confirmation."""
    plan = store.load_plan()
    if plan is None:
        raise RuntimeError("no plan to approve; run onboarding first")
    plan.family_approved = True
    store.save_plan(plan)
    store.log_event("plan_approved", {"by": "family"})
    return plan


def summarize_result(result: OnboardingResult) -> str:
    """Console-friendly onboarding summary (used by the CLI)."""
    lines: list[str] = []
    at_risk = [a for a in result.profile.assessments if a.at_risk]
    lines.append(f"Hazards at this home: {', '.join(a.hazard.value for a in at_risk) or 'none mapped'}")
    for a in at_risk:
        sev = f" — {a.severity}" if a.severity else ""
        lines.append(f"  • {a.hazard.value}{sev}")
    lines.append(f"Summary: {result.profile.summary}")
    if result.plan.primary_shelter:
        s = result.plan.primary_shelter
        lines.append(f"Primary evacuation site: {s.name} ({s.distance_km} km)")
    if result.plan.backup_shelter:
        s = result.plan.backup_shelter
        lines.append(f"Backup evacuation site: {s.name} ({s.distance_km} km)")
    lines.append(f"Timeline steps: {len(result.plan.steps)}")
    for step in result.plan.steps:
        lines.append(f"  [L{step.alert_level}] {step.headline} — trigger: {step.trigger}")
        for action in step.actions:
            eta = f" (~{action.estimated_minutes} min)" if action.estimated_minutes else ""
            lines.append(f"      - {action.member}: {action.description}{eta}")
    lines.append(
        f"Verification: {'APPROVED' if result.report.approved else 'REJECTED'} "
        f"({len(result.report.checks)} claims checked; agent path: {' → '.join(result.node_history)})"
    )
    lines.append(json.dumps([c.model_dump() for c in result.report.checks[:3]], ensure_ascii=False, indent=1))
    return "\n".join(lines)

"""Amazon Bedrock AgentCore Runtime entrypoint for Sonae.

AgentCore Runtime invokes this app with a JSON payload; one deployment serves
all of Sonae's operations, selected by `action`:

    {"action": "onboard", "profile": {...intake JSON...}, "approve": true}
    {"action": "watch_cycle", "household": "aoki"}                 # poll live JMA feeds once
    {"action": "replay_step", "household": "aoki",
     "scenario": "scenarios/hagibis_2019_nagano.json"}             # advance one replay moment
    {"action": "status", "household": "aoki"}

Continuous watch in the cloud = an EventBridge Scheduler rule invoking
`watch_cycle` every N minutes (see deploy/agentcore/README.md). Household
state lives under SONAE_STORE_DIR; point it at a mounted volume or swap the
store for the AgentCore Memory adapter.
"""

from __future__ import annotations

import json
from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from sonae.channels.inbox import InboxChannel
from sonae.config import REPO_ROOT
from sonae.datasources import jma
from sonae.datasources.replay import ReplayClock, load_scenario
from sonae.memory.store import HouseholdStore

app = BedrockAgentCoreApp()

_replay_clocks: dict[str, ReplayClock] = {}


@app.entrypoint
def invoke(payload: dict) -> dict:
    action = payload.get("action", "status")

    if action == "onboard":
        from sonae.agents.onboarding import approve_plan, run_onboarding
        from sonae.cli import build_household

        household = build_household(payload["profile"])
        store = HouseholdStore(household.household_id)
        result = run_onboarding(household, store)
        if payload.get("approve"):
            approve_plan(store)
        return {
            "household": household.household_id,
            "hazards_at_risk": [a.hazard.value for a in result.profile.assessments if a.at_risk],
            "steps": len(result.plan.steps),
            "verified": result.report.approved,
            "agent_path": result.node_history,
        }

    if action == "watch_cycle":
        from sonae.agents.watch import process_events

        store = HouseholdStore(payload["household"])
        household = store.load_household()
        if household is None:
            return {"error": "unknown household"}
        events = jma.fetch_active_warnings(household.jma_office_code, household.jma_class20_code)
        outcome = process_events(store, events, InboxChannel(store))
        return json.loads(outcome.model_dump_json())

    if action == "replay_step":
        from sonae.agents.watch import process_events

        hid = payload["household"]
        store = HouseholdStore(hid)
        if hid not in _replay_clocks:
            path = Path(payload.get("scenario", "scenarios/hagibis_2019_nagano.json"))
            _replay_clocks[hid] = ReplayClock(load_scenario(REPO_ROOT / path))
        clock = _replay_clocks[hid]
        if clock.exhausted:
            return {"done": True}
        batch = clock.advance()
        outcome = process_events(store, batch, InboxChannel(store))
        return {"sim_time": batch[0].ts.isoformat(), **json.loads(outcome.model_dump_json())}

    if action == "status":
        store = HouseholdStore(payload["household"])
        watch = store.load_watch()
        plan = store.load_plan()
        return {
            "activated_level": watch.activated_level,
            "plan_approved": bool(plan and plan.family_approved),
            "last_checked": watch.last_checked.isoformat() if watch.last_checked else None,
        }

    return {"error": f"unknown action: {action}"}


if __name__ == "__main__":
    app.run()

"""Sonae web dashboard.

    uv run uvicorn sonae.web.app:app --reload

One FastAPI app serves the dashboard page, a JSON state endpoint the page
polls, and control endpoints for onboarding and scenario replay. Long-running
agent work (onboarding, replay steps) runs in a worker thread; the UI follows
progress live through the household journal that the AuditHook writes.
"""

from __future__ import annotations

import json
import threading
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from sonae.channels.inbox import InboxChannel
from sonae.config import REPO_ROOT
from sonae.datasources.replay import ReplayClock, load_scenario
from sonae.memory.store import HouseholdStore

app = FastAPI(title="Sonae")

_TEMPLATE = Path(__file__).parent / "templates" / "index.html"

# In-memory session state (files remain the source of truth for everything else)
_replay_clocks: dict[str, ReplayClock] = {}
_busy: dict[str, str] = {}  # household_id -> current long-running operation
_lock = threading.Lock()


def _set_busy(household: str, op: str | None) -> None:
    with _lock:
        if op is None:
            _busy.pop(household, None)
        else:
            _busy[household] = op


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _TEMPLATE.read_text()


@app.get("/api/state")
def state(household: str) -> dict:
    store = HouseholdStore(household)
    h = store.load_household()
    plan = store.load_plan()
    profile = store.load_hazard_profile()
    watch = store.load_watch()
    clock = _replay_clocks.get(household)
    return {
        "household": json.loads(h.model_dump_json()) if h else None,
        "profile": json.loads(profile.model_dump_json()) if profile else None,
        "plan": json.loads(plan.model_dump_json()) if plan else None,
        "watch": json.loads(watch.model_dump_json()),
        "inbox": InboxChannel(store).read(),
        "journal": watch.history[-40:],
        "busy": _busy.get(household),
        "replay": {
            "loaded": clock is not None,
            "title": clock.scenario.title if clock else None,
            "disclaimer": clock.scenario.disclaimer if clock else None,
            "now": clock.now.isoformat() if clock and clock.now else None,
            "next": (
                {"ts": clock.peek_next().ts.isoformat(), "title": clock.peek_next().title}
                if clock and clock.peek_next()
                else None
            ),
            "exhausted": clock.exhausted if clock else None,
        },
    }


class OnboardRequest(BaseModel):
    profile_path: str = "examples/aoki_family.json"
    approve: bool = True


@app.post("/api/onboard")
def onboard(req: OnboardRequest) -> dict:
    from sonae.agents.onboarding import approve_plan, run_onboarding
    from sonae.cli import build_household

    raw = json.loads((REPO_ROOT / req.profile_path).read_text())
    household = build_household(raw)
    hid = household.household_id
    if _busy.get(hid):
        raise HTTPException(409, f"busy: {_busy[hid]}")
    store = HouseholdStore(hid)
    store.log_event("onboarding_started", {"address": household.address})

    def work() -> None:
        _set_busy(hid, "onboarding")
        try:
            run_onboarding(household, store)
            if req.approve:
                approve_plan(store)
        except Exception as exc:  # surfaced via journal; demo must never die silently
            store.log_event("error", {"op": "onboarding", "error": str(exc), "trace": traceback.format_exc()[-800:]})
        finally:
            _set_busy(hid, None)

    threading.Thread(target=work, daemon=True).start()
    return {"started": True, "household": hid}


class ReplayLoadRequest(BaseModel):
    household: str
    scenario_path: str = "scenarios/hagibis_2019_nagano.json"
    reset_watch: bool = True


@app.post("/api/replay/load")
def replay_load(req: ReplayLoadRequest) -> dict:
    store = HouseholdStore(req.household)
    if store.load_household() is None:
        raise HTTPException(404, "unknown household; onboard first")
    scenario = load_scenario(REPO_ROOT / req.scenario_path)
    _replay_clocks[req.household] = ReplayClock(scenario)
    if req.reset_watch:
        watch = store.load_watch()
        watch.activated_level = 0
        watch.seen_event_keys = []
        store.save_watch(watch)
        InboxChannel(store).clear()
    return {"loaded": scenario.scenario_id, "events": len(scenario.events)}


class ReplayStepRequest(BaseModel):
    household: str


@app.post("/api/replay/step")
def replay_step(req: ReplayStepRequest) -> dict:
    from sonae.agents.watch import process_events

    hid = req.household
    clock = _replay_clocks.get(hid)
    if clock is None:
        raise HTTPException(400, "no scenario loaded")
    if clock.exhausted:
        return {"done": True}
    if _busy.get(hid):
        raise HTTPException(409, f"busy: {_busy[hid]}")

    batch = clock.advance()
    store = HouseholdStore(hid)
    store.log_event(
        "replay_moment",
        {"sim_time": batch[0].ts.isoformat(), "events": [e.title for e in batch]},
    )

    def work() -> None:
        _set_busy(hid, "watch-cycle")
        try:
            household = store.load_household()
            outcome = process_events(store, batch, InboxChannel(store))
            store.log_event(
                "replay_outcome",
                {
                    "sim_time": batch[0].ts.isoformat(),
                    "note": outcome.note,
                    "dispatched": outcome.dispatched,
                    "household": household.household_id if household else None,
                },
            )
        except Exception as exc:
            store.log_event("error", {"op": "replay_step", "error": str(exc), "trace": traceback.format_exc()[-800:]})
        finally:
            _set_busy(hid, None)

    threading.Thread(target=work, daemon=True).start()
    return {"stepped": True, "sim_time": batch[0].ts.isoformat(), "events": [e.title for e in batch]}

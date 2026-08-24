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

from sonae import circles
from sonae.channels.inbox import InboxChannel
from sonae.config import REPO_ROOT
from sonae.datasources.replay import ReplayClock, load_scenario
from sonae.memory.store import HouseholdStore

app = FastAPI(title="Sonae")

_TEMPLATE = Path(__file__).parent / "templates" / "index.html"

# In-memory session state (files remain the source of truth for everything else)
_replay_clocks: dict[str, ReplayClock] = {}
_busy: dict[str, str] = {}  # household_id (or 'circle:<id>') -> current long-running operation
_circle_errors: dict[str, str] = {}  # circle_id -> last coordinator-report failure
_lock = threading.Lock()


def _acquire(key: str, op: str) -> bool:
    """Claim the single worker slot for `key`. Check-and-set under one lock:
    claiming it in the worker thread instead let two requests both pass the
    check and start two agent runs over the same household state."""
    with _lock:
        if key in _busy:
            return False
        _busy[key] = op
        return True


def _release(key: str) -> None:
    with _lock:
        _busy.pop(key, None)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _TEMPLATE.read_text()


@app.get("/api/households")
def households() -> dict:
    """Protected homes (those with a generated plan), for the header switcher."""
    rows = []
    for hid in HouseholdStore.list_households():
        store = HouseholdStore(hid)
        plan = store.load_plan()
        if plan is None:
            continue  # circle-member fixtures without plans are not 'protected homes'
        h = store.load_household()
        rows.append(
            {
                "id": hid,
                "address": h.address if h else hid,
                "approved": plan.family_approved,
                "level": store.load_watch().activated_level,
            }
        )
    return {"households": rows}


def _find_circle(household: str):
    for cid in circles.list_circles():
        c = circles.load_circle(cid)
        if c and household in c.household_ids:
            return c
    return None


@app.get("/api/state")
def state(household: str) -> dict:
    store = HouseholdStore(household)
    h = store.load_household()
    plan = store.load_plan()
    profile = store.load_hazard_profile()
    watch = store.load_watch()
    clock = _replay_clocks.get(household)
    circle = _find_circle(household)
    return {
        "checkins": [json.loads(c.model_dump_json()) for c in store.load_checkins()],
        "circle": circle.circle_id if circle else None,
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
            "map_markers": clock.scenario.map_markers if clock else [],
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
    profile: dict | None = None  # inline household intake (same shape as examples/*.json)
    profile_path: str | None = None
    approve: bool = False


@app.post("/api/onboard")
def onboard(req: OnboardRequest) -> dict:
    from sonae.agents.onboarding import approve_plan, run_onboarding
    from sonae.cli import build_household

    raw = req.profile if req.profile is not None else json.loads(
        (REPO_ROOT / (req.profile_path or "examples/aoki_family.json")).read_text()
    )
    try:
        household = build_household(raw)
    except Exception as exc:
        raise HTTPException(422, f"could not resolve household: {exc}") from exc
    hid = household.household_id
    store = HouseholdStore(hid)
    if not _acquire(hid, "onboarding"):
        raise HTTPException(409, f"busy: {_busy.get(hid)}")

    def work() -> None:
        try:
            run_onboarding(household, store)
            if req.approve:
                approve_plan(store)
        except Exception as exc:  # surfaced via journal; demo must never die silently
            store.log_event("error", {"op": "onboarding", "error": str(exc), "trace": traceback.format_exc()[-800:]})
        finally:
            _release(hid)

    try:
        store.log_event("onboarding_started", {"address": household.address})
        threading.Thread(target=work, daemon=True).start()
    except BaseException:  # never leave the slot claimed by a worker that never ran
        _release(hid)
        raise
    return {"started": True, "household": hid}


class ApproveRequest(BaseModel):
    household: str


@app.post("/api/approve")
def approve(req: ApproveRequest) -> dict:
    from sonae.agents.onboarding import approve_plan

    store = HouseholdStore(req.household)
    if store.load_plan() is None:
        raise HTTPException(404, "no plan to approve")
    plan = approve_plan(store)
    return {"approved": plan.family_approved}


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
    if not _acquire(hid, "watch-cycle"):
        raise HTTPException(409, f"busy: {_busy.get(hid)}")

    # Peek only: the cursor moves after the cycle succeeds, so a failed step
    # leaves the moment pending instead of skipping the events it carried.
    batch = clock.peek_moment()
    if not batch:
        _release(hid)
        return {"done": True}
    store = HouseholdStore(hid)

    def work() -> None:
        try:
            household = store.load_household()
            outcome = process_events(store, batch, InboxChannel(store))
            clock.advance()
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
            store.log_event(
                "error",
                {
                    "op": "replay_step",
                    "error": str(exc),
                    "trace": traceback.format_exc()[-800:],
                    "note": "replay cursor held at this moment; press Advance to retry",
                },
            )
        finally:
            _release(hid)

    try:
        store.log_event(
            "replay_moment",
            {"sim_time": batch[0].ts.isoformat(), "events": [e.title for e in batch]},
        )
        threading.Thread(target=work, daemon=True).start()
    except BaseException:  # never leave the slot claimed by a worker that never ran
        _release(hid)
        raise
    return {"stepped": True, "sim_time": batch[0].ts.isoformat(), "events": [e.title for e in batch]}

# ---------------------------------------------------------------------------
# Safety check-ins & neighborhood circle mode
# ---------------------------------------------------------------------------


class CheckInRequest(BaseModel):
    household: str
    member: str
    status: str  # safe | needs_help
    note: str | None = None


@app.post("/api/checkin")
def checkin(req: CheckInRequest) -> dict:
    board = circles.record_checkin(req.household, req.member, req.status, req.note)
    return {"checkins": [json.loads(c.model_dump_json()) for c in board]}


@app.get("/api/circle/{circle_id}")
def circle_state(circle_id: str) -> dict:
    circle = circles.load_circle(circle_id)
    if circle is None:
        raise HTTPException(404, "unknown circle")
    board = circles.circle_board(circle)
    report_path = circles.report_path(circle_id)
    report = json.loads(report_path.read_text()) if report_path.exists() else None
    return {
        "circle": json.loads(circle.model_dump_json()),
        "board": board,
        "counts": circles.board_counts(board),
        "phone_followups": circles.phone_followups(board),
        "report": report,
        "busy": _busy.get(f"circle:{circle_id}"),
        "error": _circle_errors.get(circle_id),
    }


class CircleReportRequest(BaseModel):
    circle_id: str


@app.post("/api/circle/report")
def circle_report(req: CircleReportRequest) -> dict:
    circle = circles.load_circle(req.circle_id)
    if circle is None:
        raise HTTPException(404, "unknown circle")
    key = f"circle:{req.circle_id}"
    if not _acquire(key, "coordinator-report"):
        raise HTTPException(409, "report already being composed")
    _circle_errors.pop(req.circle_id, None)

    def work() -> None:
        try:
            report = circles.compose_report(circle)
            circles.save_report(req.circle_id, report)
        except Exception as exc:
            # A missing report is indistinguishable from one nobody asked for.
            # Journal the failure and hand it to the UI instead of swallowing it.
            _circle_errors[req.circle_id] = str(exc)[:400]
            circles.log_circle_event(
                req.circle_id,
                "error",
                {"op": "coordinator_report", "error": str(exc), "trace": traceback.format_exc()[-800:]},
            )
        finally:
            _release(key)

    try:
        threading.Thread(target=work, daemon=True).start()
    except BaseException:  # never leave the slot claimed by a worker that never ran
        _release(key)
        raise
    return {"started": True}

"""Flight recorder: a Strands hook that journals every tool call.

Registered on every Sonae agent. After a disaster, families and researchers
can replay exactly which official data each agent consulted, when, and what
it returned — the same discipline Japan's post-event verification reports
apply to municipal decisions, applied to the agents themselves.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from strands.hooks.events import AfterToolCallEvent, BeforeToolCallEvent
from strands.hooks.registry import HookProvider, HookRegistry

from sonae.memory.store import HouseholdStore


def _compact(value: Any, limit: int = 600) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text[:limit] + ("…" if len(text) > limit else "")


class AuditHook(HookProvider):
    """Journals agent tool activity into the household store."""

    def __init__(self, store: HouseholdStore, agent_label: str = ""):
        self.store = store
        self.agent_label = agent_label

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool)
        registry.add_callback(AfterToolCallEvent, self._after_tool)

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        self.store.log_event(
            "tool_call",
            {
                "agent": getattr(event.agent, "name", self.agent_label),
                "tool": event.tool_use.get("name"),
                "input": _compact(event.tool_use.get("input", {})),
                "at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        content = event.result.get("content") if isinstance(event.result, dict) else None
        self.store.log_event(
            "tool_result",
            {
                "agent": getattr(event.agent, "name", self.agent_label),
                "tool": event.tool_use.get("name"),
                "status": event.result.get("status") if isinstance(event.result, dict) else "error",
                "output": _compact(content),
                "duration_s": event.duration,
            },
        )

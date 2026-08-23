"""Delivery channels for family notifications.

The pipeline hands a verified Notification to a Channel; where it goes
(console for demos, LINE for real families, web inbox for the dashboard)
is configuration, not agent logic.
"""

from __future__ import annotations

from typing import Protocol

from sonae.schemas import Household, Notification


class Channel(Protocol):
    def send(self, notification: Notification, household: Household) -> None:  # pragma: no cover
        ...


def render_text(n: Notification) -> str:
    """Plain-text rendering shared by console and web channels."""
    flag = "🚨 URGENT" if n.urgent else "ℹ️"
    lines = [
        f"{flag}  To: {n.to_member}",
        f"Subject: {n.subject}",
        "",
        n.body,
    ]
    if n.citations:
        lines.append("")
        lines.append("Sources:")
        lines.extend(f"  - {c.name} <{c.url}>" for c in n.citations)
    return "\n".join(lines)

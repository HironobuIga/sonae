"""Console channel: prints notifications to the terminal (demo/dev)."""

from __future__ import annotations

from sonae.channels.base import render_text
from sonae.schemas import Household, Notification

_RULE = "─" * 72


class ConsoleChannel:
    def send(self, notification: Notification, household: Household) -> None:
        print(_RULE)
        print(render_text(notification))
        print(_RULE)

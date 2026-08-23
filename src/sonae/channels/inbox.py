"""Inbox channel: persists notifications for the web dashboard's phone views."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sonae.memory.store import HouseholdStore
from sonae.schemas import Household, Notification


class InboxChannel:
    def __init__(self, store: HouseholdStore):
        self.store = store

    def send(self, notification: Notification, household: Household) -> None:
        path = self.store.dir / "inbox.json"
        inbox = json.loads(path.read_text()) if path.exists() else []
        inbox.append(
            {
                "ts": datetime.now(UTC).isoformat(),
                "to_member": notification.to_member,
                "subject": notification.subject,
                "body": notification.body,
                "urgent": notification.urgent,
                "citations": [{"name": c.name, "url": c.url} for c in notification.citations],
            }
        )
        path.write_text(json.dumps(inbox, ensure_ascii=False, indent=1))

    def read(self) -> list[dict]:
        path = self.store.dir / "inbox.json"
        return json.loads(path.read_text()) if path.exists() else []

    def clear(self) -> None:
        path = self.store.dir / "inbox.json"
        if path.exists():
            path.unlink()

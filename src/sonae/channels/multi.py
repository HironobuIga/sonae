"""Fan-out channel: deliver each notification through several channels."""

from __future__ import annotations

from sonae.channels.base import Channel
from sonae.schemas import Household, Notification


class MultiChannel:
    def __init__(self, channels: list[Channel]):
        self.channels = channels

    def send(self, notification: Notification, household: Household) -> None:
        for channel in self.channels:
            channel.send(notification, household)

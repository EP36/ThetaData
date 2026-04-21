"""Internal async pub/sub event bus for the trading engine."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

LOGGER = logging.getLogger("trauto.core.event_bus")

Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


@dataclass
class EventBus:
    """Simple asyncio-based pub/sub.

    Handlers are called sequentially per event to avoid race conditions
    in single-process paper trading. Use asyncio.create_task() inside
    handlers for fire-and-forget work.
    """

    _subscribers: dict[str, list[Handler]] = field(default_factory=dict)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """Register a coroutine handler for an event type."""
        self._subscribers.setdefault(event_type, []).append(handler)
        LOGGER.debug("event_bus_subscribe event=%s handler=%s", event_type, handler.__name__)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        """Remove a previously registered handler."""
        handlers = self._subscribers.get(event_type, [])
        try:
            handlers.remove(handler)
        except ValueError:
            pass

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """Deliver an event to all registered handlers."""
        handlers = self._subscribers.get(event_type, [])
        for handler in handlers:
            try:
                await handler(payload)
            except Exception as exc:
                LOGGER.error(
                    "event_bus_handler_error event=%s handler=%s error=%s",
                    event_type,
                    handler.__name__,
                    exc,
                )

    def clear(self) -> None:
        """Remove all subscriptions."""
        self._subscribers.clear()

"""Generation task manager for stop-generation support.

Tracks active streaming generations so they can be cancelled.
Uses a dict of {session_id: asyncio.Event} to signal cancellation.
"""
import asyncio
from typing import Dict


class GenerationManager:
    """Manages active generation tasks, supporting cancellation."""

    def __init__(self):
        self._stop_events: Dict[int, asyncio.Event] = {}

    def start_generation(self, session_id: int) -> asyncio.Event:
        """Register a new generation and return its stop event."""
        event = asyncio.Event()
        self._stop_events[session_id] = event
        return event

    def stop_generation(self, session_id: int) -> bool:
        """Signal a generation to stop. Returns True if found."""
        event = self._stop_events.get(session_id)
        if event:
            event.set()
            return True
        return False

    def is_stopped(self, session_id: int) -> bool:
        """Check if a generation has been stopped."""
        event = self._stop_events.get(session_id)
        return event.is_set() if event else False

    def end_generation(self, session_id: int):
        """Clean up after a generation ends."""
        self._stop_events.pop(session_id, None)

    def active_count(self) -> int:
        return len(self._stop_events)


generation_manager = GenerationManager()

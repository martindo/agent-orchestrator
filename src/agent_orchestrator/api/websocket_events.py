"""WebSocket event stream — Broadcasts internal events to connected clients.

Provides a WebSocketManager that maintains active connections and broadcasts
serialized events to all connected clients. Integrates with the EventBus
to forward orchestration events in real time.

Thread-safe: Uses set operations for connection management.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and broadcasts events to all clients.

    Usage:
        manager = WebSocketManager()
        await manager.connect(websocket)
        await manager.broadcast("work.completed", {"item_id": "123"})
    """

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection.

        Args:
            websocket: The incoming WebSocket connection.
        """
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(
            "WebSocket client connected. Total: %d",
            len(self.active_connections),
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the active set.

        Args:
            websocket: The disconnected WebSocket.
        """
        self.active_connections.discard(websocket)
        logger.info(
            "WebSocket client disconnected. Total: %d",
            len(self.active_connections),
        )

    async def broadcast(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast an event to all connected WebSocket clients.

        Silently removes connections that fail to send.

        Args:
            event_type: The event type string (e.g. "work.completed").
            data: The event payload dict.
        """
        if not self.active_connections:
            return

        message = json.dumps({"event": event_type, "data": data})
        disconnected: set[WebSocket] = set()

        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.add(connection)

        for conn in disconnected:
            self.active_connections.discard(conn)


ws_manager = WebSocketManager()

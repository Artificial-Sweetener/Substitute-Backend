#    Substitute BackEnd - backend liaison services for SugarSubstitute and ComfyUI
#    Copyright (C) 2026  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""PromptServer websocket publisher for cube-output events."""

from __future__ import annotations

import logging
from typing import Protocol

from substitute_backend.features.cube_outputs.domain import CubeOutputWebsocketEvent

EVENT_TYPE = "substitute_cube_output"


class PromptServerPublisherLike(Protocol):
    """Subset of Comfy PromptServer needed for cube-output publication."""

    client_id: str | None

    def send_sync(self, event: str, data: object, sid: str | None = None) -> None:
        """Queue a websocket event for Comfy clients."""


class PromptServerCubeOutputPublisher:
    """Publish cube-output events through Comfy PromptServer."""

    def __init__(
        self,
        prompt_server: PromptServerPublisherLike | object,
        logger: logging.Logger,
    ) -> None:
        """Initialize publisher with a PromptServer-like object."""

        self._prompt_server = prompt_server
        self._logger = logger

    def publish(self, event: CubeOutputWebsocketEvent) -> None:
        """Publish a cube-output event and swallow PromptServer failures."""

        send_sync = getattr(self._prompt_server, "send_sync", None)
        if not callable(send_sync):
            self._logger.debug("Cube-output event skipped; PromptServer has no send_sync")
            return
        client_id = getattr(self._prompt_server, "client_id", None)
        if client_id is not None and not isinstance(client_id, str):
            client_id = None
        try:
            send_sync(EVENT_TYPE, event.to_payload(), client_id)
        except Exception:
            self._logger.exception(
                "Failed to publish cube-output event",
                extra={
                    "prompt_id": event.prompt_id,
                    "node_id": event.node_id,
                    "cube_id": event.cube_id,
                    "instance_id": event.instance_id,
                },
            )

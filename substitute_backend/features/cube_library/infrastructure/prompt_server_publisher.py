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
"""PromptServer websocket publisher for Cube Library change events."""

from __future__ import annotations

import logging
from typing import Protocol

from substitute_backend.features.cube_library.domain.events import (
    EVENT_TYPE,
    CubeLibraryChangedEvent,
)


class PromptServerPublisherLike(Protocol):
    """Subset of Comfy PromptServer needed for Cube Library publication."""

    client_id: str | None

    def send_sync(self, event: str, data: object, sid: str | None = None) -> None:
        """Queue a websocket event for Comfy clients."""


class PromptServerCubeLibraryPublisher:
    """Publish Cube Library change events through Comfy PromptServer."""

    def __init__(
        self,
        prompt_server: PromptServerPublisherLike | object,
        logger: logging.Logger,
    ) -> None:
        """Initialize publisher with a PromptServer-like object."""

        self._prompt_server = prompt_server
        self._logger = logger

    def publish(self, event: CubeLibraryChangedEvent) -> None:
        """Publish a Cube Library event and swallow PromptServer failures."""

        send_sync = getattr(self._prompt_server, "send_sync", None)
        if not callable(send_sync):
            self._logger.debug("Cube Library event skipped; PromptServer has no send_sync")
            return
        try:
            send_sync(EVENT_TYPE, event.to_payload(), None)
        except Exception:
            self._logger.exception(
                "Failed to publish Cube Library change event",
                extra={
                    "catalog_revision": event.catalog_revision,
                    "previous_catalog_revision": event.previous_catalog_revision,
                },
            )

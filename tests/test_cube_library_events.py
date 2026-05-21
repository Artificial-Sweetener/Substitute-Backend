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
"""Tests for Cube Library websocket event contracts."""

from __future__ import annotations

import logging

import pytest

from substitute_backend.features.cube_library.domain.events import (
    EVENT_TYPE,
    CubeLibraryChangedEvent,
)
from substitute_backend.features.cube_library.infrastructure.prompt_server_publisher import (
    PromptServerCubeLibraryPublisher,
)


class _PromptServer:
    """Collect PromptServer websocket sends."""

    client_id = "client-1"

    def __init__(self) -> None:
        """Initialize an empty send list."""

        self.sent: list[tuple[str, object, str | None]] = []

    def send_sync(self, event: str, data: object, sid: str | None = None) -> None:
        """Collect one sent event."""

        self.sent.append((event, data, sid))


class _FailingPromptServer:
    """Raise from PromptServer sends."""

    client_id = None

    def send_sync(self, _event: str, _data: object, _sid: str | None = None) -> None:
        """Fail one send."""

        raise RuntimeError("send failed")


def test_cube_library_changed_event_payload_matches_public_contract() -> None:
    """Cube Library events should serialize the versioned websocket payload."""

    event = CubeLibraryChangedEvent(
        catalog_revision="sha256:new",
        previous_catalog_revision="sha256:old",
        generated_at="2026-05-15T19:00:00+00:00",
        reason="catalog-revision-changed",
    )

    assert event.to_payload() == {
        "schemaVersion": 1,
        "catalogRevision": "sha256:new",
        "previousCatalogRevision": "sha256:old",
        "generatedAt": "2026-05-15T19:00:00+00:00",
        "reason": "catalog-revision-changed",
    }


def test_prompt_server_cube_library_publisher_broadcasts_event() -> None:
    """Cube Library changes should broadcast because they are global state."""

    prompt_server = _PromptServer()
    publisher = PromptServerCubeLibraryPublisher(
        prompt_server=prompt_server,
        logger=logging.getLogger("test.cube_library.publisher"),
    )
    event = CubeLibraryChangedEvent(
        catalog_revision="rev-2",
        previous_catalog_revision="rev-1",
        generated_at="2026-05-15T19:00:00+00:00",
        reason="catalog-revision-changed",
    )

    publisher.publish(event)

    assert prompt_server.sent == [(EVENT_TYPE, event.to_payload(), None)]


def test_prompt_server_cube_library_publisher_ignores_current_prompt_client() -> None:
    """The active Comfy prompt client must not scope Cube Library notifications."""

    prompt_server = _PromptServer()
    prompt_server.client_id = "browser-client"
    publisher = PromptServerCubeLibraryPublisher(
        prompt_server=prompt_server,
        logger=logging.getLogger("test.cube_library.publisher.broadcast"),
    )
    event = CubeLibraryChangedEvent(
        catalog_revision="rev-3",
        previous_catalog_revision="rev-2",
        generated_at="2026-05-15T19:00:00+00:00",
        reason="catalog-revision-changed",
    )

    publisher.publish(event)

    assert prompt_server.sent == [(EVENT_TYPE, event.to_payload(), None)]


def test_prompt_server_cube_library_publisher_swallows_send_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PromptServer send failures should not raise into Comfy runtime paths."""

    publisher = PromptServerCubeLibraryPublisher(
        prompt_server=_FailingPromptServer(),
        logger=logging.getLogger("test.cube_library.publisher.failure"),
    )

    with caplog.at_level(logging.ERROR):
        publisher.publish(
            CubeLibraryChangedEvent(
                catalog_revision="rev-2",
                previous_catalog_revision="rev-1",
                generated_at="2026-05-15T19:00:00+00:00",
                reason="catalog-revision-changed",
            )
        )

    assert "Failed to publish Cube Library change event" in caplog.text

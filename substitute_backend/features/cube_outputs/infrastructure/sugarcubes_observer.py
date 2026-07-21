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
"""Adapter from SugarCubes cube-output hooks to Substitute websocket events."""

from __future__ import annotations

import logging
from typing import Protocol, cast

from substitute_backend.features.cube_outputs.domain import (
    CubeOutputArtifactEvent,
    CubeOutputWebsocketEvent,
)
from substitute_backend.features.cube_outputs.domain.events import MediaKind
from substitute_backend.features.cube_outputs.infrastructure.prompt_server_publisher import (
    PromptServerCubeOutputPublisher,
)
from substitute_backend.features.prompt_queue.application.run_context_store import (
    SubstituteRunContextStore,
)


class SugarCubesArtifactLike(Protocol):
    """Subset of a SugarCubes cube output artifact used for publication."""

    filename: str
    subfolder: str
    type: str
    media_kind: str
    mime_type: str | None
    width: int | None
    height: int | None
    duration_seconds: float | None


class SugarCubesEventLike(Protocol):
    """Subset of a SugarCubes cube output event used for publication."""

    version: int
    prompt_id: str | None
    node_id: str | None
    list_index: int | None
    cube_id: str
    default_alias: str
    instance_alias: str
    instance_id: str
    media_kind: str
    value_type: str
    artifacts: tuple[SugarCubesArtifactLike, ...]


class SubstituteCubeOutputObserver:
    """Translate SugarCubes output events into Substitute websocket events."""

    def __init__(
        self,
        *,
        publisher: PromptServerCubeOutputPublisher,
        logger: logging.Logger,
        run_context_store: SubstituteRunContextStore | None = None,
    ) -> None:
        """Initialize the observer with its websocket publisher."""

        self._publisher = publisher
        self._logger = logger
        self._run_context_store = run_context_store

    def on_cube_output(self, event: SugarCubesEventLike) -> None:
        """Publish one SugarCubes cube-output event for Substitute."""

        try:
            websocket_event = _map_sugarcubes_event(event)
            if self._run_context_store is not None:
                enriched_event = self._enrich_event(websocket_event)
                if enriched_event is None:
                    self._logger.warning(
                        "Skipping cube-output event without Substitute run context",
                        extra={
                            "prompt_id": getattr(event, "prompt_id", None),
                            "node_id": getattr(event, "node_id", None),
                            "reason": "unknown_prompt_context",
                        },
                    )
                    return
                websocket_event = enriched_event
            self._publisher.publish(websocket_event)
        except Exception:
            self._logger.exception(
                "Failed to handle SugarCubes cube-output event",
                extra={
                    "prompt_id": getattr(event, "prompt_id", None),
                    "node_id": getattr(event, "node_id", None),
                    "cube_id": getattr(event, "cube_id", None),
                },
            )

    def _enrich_event(
        self,
        event: CubeOutputWebsocketEvent,
    ) -> CubeOutputWebsocketEvent | None:
        """Return a v2 identity-bearing event for known prompt context."""

        if self._run_context_store is None:
            return event
        resolved = self._run_context_store.resolve_source(
            prompt_id=event.prompt_id,
            node_id=event.node_id,
        )
        if resolved is None:
            return None
        context, source = resolved
        return CubeOutputWebsocketEvent(
            prompt_id=event.prompt_id,
            node_id=event.node_id,
            list_index=event.list_index,
            cube_id=event.cube_id,
            default_alias=event.default_alias,
            instance_alias=event.instance_alias,
            instance_id=event.instance_id,
            media_kind=event.media_kind,
            value_type=event.value_type,
            artifacts=event.artifacts,
            substitute=context.substitute_payload_for_source(source),
            client_id=context.client_id,
            version=2,
        )


def _map_sugarcubes_event(event: SugarCubesEventLike) -> CubeOutputWebsocketEvent:
    """Map SugarCubes' neutral event object to Substitute's public payload."""

    return CubeOutputWebsocketEvent(
        prompt_id=event.prompt_id,
        node_id=event.node_id,
        list_index=event.list_index,
        cube_id=event.cube_id,
        default_alias=event.default_alias,
        instance_alias=event.instance_alias,
        instance_id=event.instance_id,
        media_kind=_media_kind(event.media_kind),
        value_type=event.value_type,
        artifacts=tuple(_map_artifact(artifact) for artifact in event.artifacts),
        version=1,
    )


def _map_artifact(artifact: SugarCubesArtifactLike) -> CubeOutputArtifactEvent:
    """Map one SugarCubes artifact to the Substitute websocket payload."""

    return CubeOutputArtifactEvent(
        filename=artifact.filename,
        subfolder=artifact.subfolder,
        type=artifact.type,
        media_kind=_media_kind(artifact.media_kind),
        mime_type=artifact.mime_type,
        width=artifact.width,
        height=artifact.height,
        duration_seconds=artifact.duration_seconds,
    )


def _media_kind(value: str) -> MediaKind:
    """Normalize media-kind strings to Substitute's versioned contract."""

    if value in {"image", "audio", "video", "value", "unknown"}:
        return cast(MediaKind, value)
    return "unknown"

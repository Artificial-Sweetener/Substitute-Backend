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
"""Model-loading telemetry publication use cases."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from substitute_backend.features.model_loading.domain.events import (
    ModelLoadPhase,
    ModelLoadProgressEvent,
    ModelLoadState,
)


@dataclass(frozen=True)
class ModelLoadContext:
    """Capture the Comfy execution context associated with telemetry."""

    prompt_id: str | None
    node_id: str | None
    display_node_id: str | None = None


class ModelLoadEventPublisher(Protocol):
    """Publish model-loading events to connected clients."""

    def publish(self, event: ModelLoadProgressEvent) -> None:
        """Publish a model-loading telemetry event."""


class ModelLoadingTelemetryService:
    """Build and publish model-loading telemetry events."""

    def __init__(self, publisher: ModelLoadEventPublisher) -> None:
        """Initialize the service with a failure-safe publisher."""

        self._publisher = publisher

    def emit(
        self,
        *,
        phase: ModelLoadPhase,
        state: ModelLoadState,
        context: ModelLoadContext | None = None,
        percent: float | None = None,
        value: float | None = None,
        maximum: float | None = None,
        unit: str | None = None,
        model_class: str | None = None,
        model_name: str | None = None,
        source_node_id: str | None = None,
        source_input_key: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Publish a telemetry event without requiring all optional metadata."""

        resolved_context = context or ModelLoadContext(prompt_id=None, node_id=None)
        event = ModelLoadProgressEvent(
            phase=phase,
            state=state,
            timestamp=time.monotonic(),
            prompt_id=resolved_context.prompt_id,
            node_id=resolved_context.node_id,
            display_node_id=resolved_context.display_node_id,
            percent=percent,
            value=value,
            maximum=maximum,
            unit=unit,
            model_class=model_class,
            model_name=model_name,
            source_node_id=source_node_id,
            source_input_key=source_input_key,
            detail=detail,
        )
        self._publisher.publish(event)

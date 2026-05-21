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
"""Download telemetry publication use cases."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from substitute_backend.features.downloads.domain import (
    DownloadProgressEvent,
    DownloadProvider,
    DownloadState,
)

_MIN_PERCENT_DELTA = 1.0
_MIN_EMIT_INTERVAL_SECONDS = 0.1


@dataclass(frozen=True)
class DownloadContext:
    """Capture stable metadata for one observed download operation."""

    provider: DownloadProvider
    operation_id: str
    prompt_id: str | None = None
    node_id: str | None = None
    display_node_id: str | None = None
    repo_id: str | None = None
    filename: str | None = None
    url: str | None = None


class DownloadProgressPublisher(Protocol):
    """Publish download telemetry events to connected clients."""

    def publish(self, event: DownloadProgressEvent) -> None:
        """Publish one download telemetry event."""


@dataclass
class _ThrottleState:
    """Track the last emitted running progress for one operation."""

    last_percent: float | None = None
    last_emit: float = 0.0
    emitted_running: bool = False


class DownloadTelemetryService:
    """Build and publish throttled download progress telemetry."""

    def __init__(
        self,
        *,
        publisher: DownloadProgressPublisher,
        logger: logging.Logger,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize service dependencies."""

        self._publisher = publisher
        self._logger = logger
        self._clock = clock
        self._throttle: dict[str, _ThrottleState] = {}

    def emit(
        self,
        *,
        context: DownloadContext,
        state: DownloadState,
        value: float | None = None,
        maximum: float | None = None,
        unit: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Publish one telemetry event without allowing failures into downloads."""

        now = self._clock()
        percent = _progress_percent(value=value, maximum=maximum)
        if state is DownloadState.RUNNING and not self._should_emit_running(
            operation_id=context.operation_id,
            percent=percent,
            now=now,
        ):
            return
        event = DownloadProgressEvent(
            provider=context.provider,
            operation_id=context.operation_id,
            state=state,
            timestamp=now,
            prompt_id=context.prompt_id,
            node_id=context.node_id,
            display_node_id=context.display_node_id,
            repo_id=context.repo_id,
            filename=context.filename,
            url=context.url,
            value=value,
            maximum=maximum,
            percent=percent,
            unit=unit,
            detail=detail,
        )
        try:
            self._publisher.publish(event)
        except Exception:
            self._logger.exception("Download telemetry publication failed")
        if state in {DownloadState.FINISHED, DownloadState.FAILED}:
            self._throttle.pop(context.operation_id, None)

    def _should_emit_running(
        self,
        *,
        operation_id: str,
        percent: float | None,
        now: float,
    ) -> bool:
        """Return whether one running update should pass throttling."""

        state = self._throttle.setdefault(operation_id, _ThrottleState())
        if not state.emitted_running:
            state.emitted_running = True
            state.last_percent = percent
            state.last_emit = now
            return True
        if percent is not None and percent >= 100.0:
            state.last_percent = percent
            state.last_emit = now
            return True
        if (
            percent is not None
            and state.last_percent is not None
            and percent - state.last_percent >= _MIN_PERCENT_DELTA
        ):
            state.last_percent = percent
            state.last_emit = now
            return True
        if now - state.last_emit >= _MIN_EMIT_INTERVAL_SECONDS:
            state.last_percent = percent
            state.last_emit = now
            return True
        return False


def _progress_percent(*, value: float | None, maximum: float | None) -> float | None:
    """Return progress percentage only when a positive maximum is known."""

    if value is None or maximum is None or maximum <= 0:
        return None
    return 100.0 * value / maximum

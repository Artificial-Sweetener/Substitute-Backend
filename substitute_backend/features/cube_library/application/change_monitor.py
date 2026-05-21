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
"""Monitor Cube Library catalog revisions and publish change notifications."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from substitute_backend.features.cube_library.domain.events import CubeLibraryChangedEvent
from substitute_backend.infrastructure.diagnostics import (
    CUBE_LIBRARY_DIAGNOSTICS,
    DiagnosticContext,
    DiagnosticLogger,
)

CATALOG_REVISION_CHANGED_REASON = "catalog-revision-changed"
DEFAULT_POLL_INTERVAL_SECONDS = 30.0
_FAILURE_LOG_REPEAT_INTERVAL = 10


class CubeLibraryChangePublisher(Protocol):
    """Describe the publisher used by the Cube Library change monitor."""

    def publish(self, event: CubeLibraryChangedEvent) -> None:
        """Publish one Cube Library change event."""


class CubeLibraryChangeMonitor:
    """Poll Cube Library revision state outside Comfy request handlers."""

    def __init__(
        self,
        *,
        get_catalog_revision: Callable[[], str],
        publisher: CubeLibraryChangePublisher,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        logger: logging.Logger,
        diagnostics: DiagnosticLogger,
    ) -> None:
        """Initialize the monitor with polling and publication collaborators."""

        self._get_catalog_revision = get_catalog_revision
        self._publisher = publisher
        self._poll_interval_seconds = poll_interval_seconds
        self._logger = logger
        self._diagnostics = diagnostics
        self._diagnostic_context = DiagnosticContext(feature=CUBE_LIBRARY_DIAGNOSTICS)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_catalog_revision = ""
        self._failure_count = 0
        self._lock = threading.Lock()

    @property
    def poll_interval_seconds(self) -> float:
        """Return the configured revision polling interval."""

        return self._poll_interval_seconds

    @property
    def is_running(self) -> bool:
        """Return whether the monitor thread is currently alive."""

        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        """Start the background polling thread once."""

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="SubstituteCubeLibraryChangeMonitor",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Request monitor shutdown and wait briefly for the thread to exit."""

        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=min(1.0, max(0.01, self._poll_interval_seconds)))

    def check_once(self) -> None:
        """Poll one catalog revision and publish when a later revision changes."""

        try:
            catalog_revision = self._get_catalog_revision().strip()
        except Exception as exc:
            self._record_poll_failure(exc)
            return
        self._failure_count = 0
        self._log_diagnostic(
            "backend_change_monitor_poll",
            catalog_revision=catalog_revision,
            previous_catalog_revision=self._last_catalog_revision,
        )
        if not catalog_revision:
            self._logger.debug("Cube Library catalog revision was empty; skipping event")
            return
        previous_catalog_revision = self._last_catalog_revision
        if not previous_catalog_revision:
            self._last_catalog_revision = catalog_revision
            self._logger.debug(
                "Initialized Cube Library catalog revision monitor",
                extra={"catalog_revision": catalog_revision},
            )
            return
        if catalog_revision == previous_catalog_revision:
            return
        self._last_catalog_revision = catalog_revision
        self._logger.info(
            "Cube Library catalog revision changed",
            extra={
                "catalog_revision": catalog_revision,
                "previous_catalog_revision": previous_catalog_revision,
                "reason": CATALOG_REVISION_CHANGED_REASON,
            },
        )
        self._publisher.publish(
            CubeLibraryChangedEvent(
                catalog_revision=catalog_revision,
                previous_catalog_revision=previous_catalog_revision,
                generated_at=datetime.now(UTC).isoformat(),
                reason=CATALOG_REVISION_CHANGED_REASON,
            )
        )

    def publish_immediate_change(self, *, catalog_revision: str, reason: str) -> None:
        """Publish an externally observed Cube Library change immediately."""

        normalized_revision = catalog_revision.strip()
        if not normalized_revision:
            return
        previous_catalog_revision = self._last_catalog_revision
        self._last_catalog_revision = normalized_revision
        self._logger.info(
            "Cube Library catalog revision changed",
            extra={
                "catalog_revision": normalized_revision,
                "previous_catalog_revision": previous_catalog_revision,
                "reason": reason,
            },
        )
        self._publisher.publish(
            CubeLibraryChangedEvent(
                catalog_revision=normalized_revision,
                previous_catalog_revision=previous_catalog_revision,
                generated_at=datetime.now(UTC).isoformat(),
                reason=reason,
            )
        )

    def _run(self) -> None:
        """Run the polling loop until shutdown is requested."""

        while not self._stop_event.is_set():
            self.check_once()
            self._stop_event.wait(self._poll_interval_seconds)

    def _record_poll_failure(self, exc: Exception) -> None:
        """Log recurring poll failures without flooding Comfy logs."""

        self._failure_count += 1
        if self._failure_count == 1 or (self._failure_count % _FAILURE_LOG_REPEAT_INTERVAL == 0):
            self._logger.warning(
                "Failed to poll Cube Library catalog revision",
                extra={"failure_count": self._failure_count, "error": repr(exc)},
            )

    def _log_diagnostic(self, event: str, **fields: object) -> None:
        """Emit one opt-in Cube Library change-monitor diagnostic."""

        self._diagnostics.debug(self._diagnostic_context, event, fields)

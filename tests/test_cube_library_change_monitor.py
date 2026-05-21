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
"""Tests for Cube Library catalog-revision monitoring."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import pytest

from substitute_backend.features.cube_library.application.change_monitor import (
    CATALOG_REVISION_CHANGED_REASON,
    DEFAULT_POLL_INTERVAL_SECONDS,
    CubeLibraryChangeMonitor,
)
from substitute_backend.features.cube_library.domain.events import CubeLibraryChangedEvent
from substitute_backend.infrastructure.diagnostics import (
    CUBE_LIBRARY_DIAGNOSTICS,
    DIAGNOSTICS_ENV_VAR,
    diagnostics_from_environment,
)


class _Publisher:
    """Collect Cube Library change events."""

    def __init__(self) -> None:
        """Initialize an empty event list."""

        self.events: list[CubeLibraryChangedEvent] = []

    def publish(self, event: CubeLibraryChangedEvent) -> None:
        """Collect one published event."""

        self.events.append(event)


def test_first_observed_revision_does_not_publish() -> None:
    """The monitor should establish initial state without notifying clients."""

    publisher = _Publisher()
    monitor = _monitor(lambda: "rev-1", publisher)

    monitor.check_once()

    assert publisher.events == []


def test_changed_revision_publishes_exactly_one_event() -> None:
    """The monitor should publish once when the revision changes."""

    revisions = iter(["rev-1", "rev-2", "rev-2"])
    publisher = _Publisher()
    monitor = _monitor(lambda: next(revisions), publisher)

    monitor.check_once()
    monitor.check_once()
    monitor.check_once()

    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert event.catalog_revision == "rev-2"
    assert event.previous_catalog_revision == "rev-1"
    assert event.reason == CATALOG_REVISION_CHANGED_REASON


def test_same_revision_does_not_publish() -> None:
    """The monitor should ignore unchanged non-empty revisions."""

    publisher = _Publisher()
    monitor = _monitor(lambda: "rev-1", publisher)

    monitor.check_once()
    monitor.check_once()

    assert publisher.events == []


def test_same_revision_does_not_log_poll_at_info_by_default(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unchanged successful polls should not create normal Comfy log noise."""

    monkeypatch.delenv(DIAGNOSTICS_ENV_VAR, raising=False)
    publisher = _Publisher()
    monitor = _monitor(lambda: "rev-1", publisher)

    with caplog.at_level(logging.INFO):
        monitor.check_once()
        monitor.check_once()

    assert publisher.events == []
    assert "backend_change_monitor_poll" not in caplog.text
    assert "Cube Library catalog revision changed" not in caplog.text


def test_changed_revision_logs_state_change(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revision changes should remain visible without diagnostic opt-in."""

    monkeypatch.delenv(DIAGNOSTICS_ENV_VAR, raising=False)
    revisions = iter(["rev-1", "rev-2"])
    publisher = _Publisher()
    monitor = _monitor(lambda: next(revisions), publisher)

    with caplog.at_level(logging.INFO):
        monitor.check_once()
        monitor.check_once()

    assert "Cube Library catalog revision changed" in caplog.text
    record = next(
        record
        for record in caplog.records
        if record.getMessage() == "Cube Library catalog revision changed"
    )
    assert getattr(record, "catalog_revision", "") == "rev-2"
    assert getattr(record, "previous_catalog_revision", "") == "rev-1"
    assert getattr(record, "reason", "") == CATALOG_REVISION_CHANGED_REASON


def test_poll_diagnostics_are_opt_in(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful poll details should emit only through the diagnostic channel."""

    monkeypatch.setenv(DIAGNOSTICS_ENV_VAR, "cube-library")
    publisher = _Publisher()
    monitor = _monitor(lambda: "rev-1", publisher)

    with caplog.at_level(logging.DEBUG):
        monitor.check_once()

    records = [
        record
        for record in caplog.records
        if getattr(record, "diagnostic_feature", "") == CUBE_LIBRARY_DIAGNOSTICS
    ]
    assert [getattr(record, "diagnostic_event", "") for record in records] == [
        "backend_change_monitor_poll"
    ]
    assert getattr(records[0], "catalog_revision", "") == "rev-1"


def test_empty_revision_does_not_publish() -> None:
    """The monitor should ignore empty revisions from unavailable libraries."""

    publisher = _Publisher()
    monitor = _monitor(lambda: "", publisher)

    monitor.check_once()
    monitor.check_once()

    assert publisher.events == []


def test_poll_failures_are_logged_and_do_not_stop_later_polling(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Transient polling errors should not prevent later change events."""

    calls = iter([RuntimeError("boom"), "rev-1", "rev-2"])

    def get_revision() -> str:
        value = next(calls)
        if isinstance(value, RuntimeError):
            raise value
        if isinstance(value, str):
            return value
        raise TypeError(type(value).__name__)

    publisher = _Publisher()
    monitor = _monitor(get_revision, publisher)

    with caplog.at_level(logging.WARNING):
        monitor.check_once()
        monitor.check_once()
        monitor.check_once()

    assert "Failed to poll Cube Library catalog revision" in caplog.text
    assert [event.catalog_revision for event in publisher.events] == ["rev-2"]


def test_monitor_stop_signal_exits_polling_loop_without_waiting_full_interval() -> None:
    """Stop should interrupt the monitor's interval wait."""

    publisher = _Publisher()
    monitor = _monitor(lambda: "rev-1", publisher, poll_interval_seconds=30.0)

    monitor.start()
    time.sleep(0.05)
    started_at = time.perf_counter()
    monitor.stop()
    elapsed_seconds = time.perf_counter() - started_at

    assert elapsed_seconds < 1.0
    assert not monitor.is_running


def test_monitor_default_interval_is_conservative() -> None:
    """The monitor default should avoid aggressive steady disk hashing."""

    publisher = _Publisher()
    monitor = _monitor(lambda: "rev-1", publisher)

    assert monitor.poll_interval_seconds == DEFAULT_POLL_INTERVAL_SECONDS
    assert monitor.poll_interval_seconds == 30.0


def _monitor(
    get_catalog_revision: Callable[[], str],
    publisher: _Publisher,
    *,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> CubeLibraryChangeMonitor:
    """Build a monitor with test logging."""

    return CubeLibraryChangeMonitor(
        get_catalog_revision=get_catalog_revision,
        publisher=publisher,
        poll_interval_seconds=poll_interval_seconds,
        logger=logging.getLogger("test.cube_library.change_monitor"),
        diagnostics=diagnostics_from_environment(
            logging.getLogger("test.cube_library.diagnostics")
        ),
    )

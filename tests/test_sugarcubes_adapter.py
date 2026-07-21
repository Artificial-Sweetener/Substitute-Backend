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
"""SugarCubes adapter service-loading tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from substitute_backend.features.cube_library.infrastructure.sugarcubes_adapter import (
    SugarCubesLibraryAdapter,
)
from substitute_backend.infrastructure.sugarcubes_host_api import (
    SUGARCUBES_HOST_API_MODULE,
)


class _Library:
    """Provide the minimal SugarCubes library surface for adapter tests."""

    def library_status(self) -> dict[str, object]:
        """Return one available status payload."""

        return {
            "schemaVersion": 1,
            "available": True,
            "source": "SugarCubes",
            "catalogRevision": "sha256:active",
            "errors": [],
        }


class _CapabilitiesLibrary:
    """Expose lightweight capability status without catalog status."""

    def library_status(self) -> dict[str, object]:
        """Fail when capabilities uses the expensive status path."""

        pytest.fail("capabilities should use lightweight status")

    def library_capabilities_status(self) -> dict[str, object]:
        """Return lightweight capability facts."""

        return {
            "schemaVersion": 1,
            "available": True,
            "source": "SugarCubes",
            "sugarCubesVersion": "0.9.1",
            "catalogRevision": "",
            "packManagementSupported": True,
            "localAuthoringSupported": True,
            "readinessSupported": True,
            "dependencyReadinessSupported": True,
            "dependencyRepairSupported": True,
            "versionedDependencyReadinessSupported": True,
            "syncDependencyOrchestrationSupported": True,
            "errors": [],
        }


class _SubscribableLibrary(_Library):
    """Provide a SugarCubes library-change subscription surface."""

    def __init__(self) -> None:
        """Initialize the captured listener list."""

        self.listeners: list[object] = []

    def subscribe_library_changed(self, listener: object) -> object:
        """Capture one listener and return an unsubscribe callback."""

        self.listeners.append(listener)

        def unsubscribe() -> None:
            """Remove the captured listener."""

            self.listeners.remove(listener)

        return unsubscribe


def test_adapter_uses_active_sugarcubes_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter should avoid building a duplicate SugarCubes service graph."""

    _publish_host_api(
        monkeypatch,
        services=SimpleNamespace(library=_Library()),
    )
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "substitute-backend",
        custom_nodes_root=_custom_nodes_root(tmp_path),
    )

    status = adapter.status()

    assert status["available"] is True
    assert status["catalogRevision"] == "sha256:active"


def test_adapter_capabilities_use_lightweight_sugarcubes_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capabilities should avoid forcing SugarCubes catalog revision work."""

    _publish_host_api(
        monkeypatch,
        services=SimpleNamespace(library=_CapabilitiesLibrary()),
    )
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "substitute-backend",
        custom_nodes_root=_custom_nodes_root(tmp_path),
    )

    capabilities = adapter.capabilities()

    assert capabilities["available"] is True
    assert capabilities["sugarCubesVersion"] == "0.9.1"


def test_adapter_defers_library_change_subscription_until_services_load(
    tmp_path: Path,
) -> None:
    """Library-change subscriptions should not force startup service discovery."""

    library = _SubscribableLibrary()
    services = SimpleNamespace(library=library)
    loader_calls: list[bool] = []

    def services_loader() -> object:
        """Record service discovery calls."""

        loader_calls.append(True)
        return services

    custom_nodes_root = _custom_nodes_root(tmp_path)
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "substitute-backend",
        custom_nodes_root=custom_nodes_root,
        services_loader=services_loader,
    )
    received_events: list[dict[str, object]] = []

    def record_event(event: object) -> None:
        """Record a received library-change event."""

        if isinstance(event, dict):
            received_events.append(event)

    unsubscribe = adapter.subscribe_library_changes(record_event)

    assert callable(unsubscribe)
    assert loader_calls == []
    assert library.listeners == []

    status = adapter.status()

    assert status["available"] is True
    assert loader_calls == [True]
    assert library.listeners == [record_event]


def test_adapter_pending_library_change_subscription_can_be_cancelled(
    tmp_path: Path,
) -> None:
    """Cancelled deferred subscriptions should not attach after services load."""

    library = _SubscribableLibrary()
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "substitute-backend",
        custom_nodes_root=_custom_nodes_root(tmp_path),
        services_loader=lambda: SimpleNamespace(library=library),
    )

    unsubscribe = adapter.subscribe_library_changes(lambda _event: None)
    assert callable(unsubscribe)
    unsubscribe()

    status = adapter.status()

    assert status["available"] is True
    assert library.listeners == []


def test_adapter_reports_unavailable_when_sugarcubes_root_is_missing(
    tmp_path: Path,
) -> None:
    """Missing SugarCubes should remain a typed unavailable status."""

    custom_nodes_root = tmp_path / "custom_nodes"
    custom_nodes_root.mkdir()
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "substitute-backend",
        custom_nodes_root=custom_nodes_root,
    )

    status = adapter.status()

    assert status["available"] is False
    assert status["errors"] == [
        {
            "code": "sugarcubes-unavailable",
            "message": "SugarCubes has not published its host API yet.",
        }
    ]


def _custom_nodes_root(tmp_path: Path) -> Path:
    """Create a custom_nodes root with a sibling SugarCubes extension."""

    custom_nodes_root = tmp_path / "custom_nodes"
    (custom_nodes_root / "SugarCubes").mkdir(parents=True)
    return custom_nodes_root


def _publish_host_api(
    monkeypatch: pytest.MonkeyPatch,
    *,
    services: object,
) -> None:
    """Publish the minimal SugarCubes API used by the library adapter."""

    module = ModuleType(SUGARCUBES_HOST_API_MODULE)
    module.__dict__["HOST_API_VERSION"] = 1
    module.__dict__["active_backend_services"] = lambda: services
    module.__dict__["register_cube_output_observer"] = lambda _observer: None
    module.__dict__["unregister_cube_output_observer"] = lambda _observer: None
    monkeypatch.setitem(sys.modules, SUGARCUBES_HOST_API_MODULE, module)

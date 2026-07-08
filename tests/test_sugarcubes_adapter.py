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

    active_services = SimpleNamespace(library=_Library())

    def import_module(name: str) -> object:
        """Return a fake SugarCubes backend module."""

        if name != "backend":
            raise ModuleNotFoundError(name)
        return SimpleNamespace(
            active_backend_services=lambda: active_services,
            build_backend_services=lambda _root: pytest.fail(
                "fallback factory should not be called"
            ),
        )

    monkeypatch.setattr(
        "substitute_backend.features.cube_library.infrastructure.sugarcubes_adapter.importlib.import_module",
        import_module,
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

    active_services = SimpleNamespace(library=_CapabilitiesLibrary())

    def import_module(name: str) -> object:
        """Return a fake SugarCubes backend module."""

        if name != "backend":
            raise ModuleNotFoundError(name)
        return SimpleNamespace(
            active_backend_services=lambda: active_services,
            build_backend_services=lambda _root: pytest.fail(
                "fallback factory should not be called"
            ),
        )

    monkeypatch.setattr(
        "substitute_backend.features.cube_library.infrastructure.sugarcubes_adapter.importlib.import_module",
        import_module,
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
    factory_calls: list[Path] = []

    def services_factory(root: Path) -> object:
        """Record service discovery calls."""

        factory_calls.append(root)
        return services

    custom_nodes_root = _custom_nodes_root(tmp_path)
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "substitute-backend",
        custom_nodes_root=custom_nodes_root,
        services_factory=services_factory,
    )
    received_events: list[dict[str, object]] = []

    def record_event(event: object) -> None:
        """Record a received library-change event."""

        if isinstance(event, dict):
            received_events.append(event)

    unsubscribe = adapter.subscribe_library_changes(record_event)

    assert callable(unsubscribe)
    assert factory_calls == []
    assert library.listeners == []

    status = adapter.status()

    assert status["available"] is True
    assert factory_calls == [custom_nodes_root / "SugarCubes"]
    assert library.listeners == [record_event]


def test_adapter_pending_library_change_subscription_can_be_cancelled(
    tmp_path: Path,
) -> None:
    """Cancelled deferred subscriptions should not attach after services load."""

    library = _SubscribableLibrary()
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "substitute-backend",
        custom_nodes_root=_custom_nodes_root(tmp_path),
        services_factory=lambda _root: SimpleNamespace(library=library),
    )

    unsubscribe = adapter.subscribe_library_changes(lambda _event: None)
    assert callable(unsubscribe)
    unsubscribe()

    status = adapter.status()

    assert status["available"] is True
    assert library.listeners == []


def test_adapter_uses_path_named_active_sugarcubes_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ComfyUI path-named imports should still share SugarCubes services."""

    custom_nodes_root = _custom_nodes_root(tmp_path)
    backend_module = ModuleType(f"{custom_nodes_root / 'SugarCubes'}.backend")
    backend_module.__file__ = str(custom_nodes_root / "SugarCubes" / "backend" / "__init__.py")
    active_services = SimpleNamespace(library=_Library())
    backend_module.__dict__["active_backend_services"] = lambda: active_services
    monkeypatch.setitem(sys.modules, backend_module.__name__, backend_module)

    def import_module(name: str) -> object:
        """Fail if the adapter ignores the already-loaded path module."""

        if name == "backend":
            return SimpleNamespace(
                active_backend_services=lambda: None,
                build_backend_services=lambda _root: pytest.fail(
                    "fallback factory should not be called"
                ),
            )
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(
        "substitute_backend.features.cube_library.infrastructure.sugarcubes_adapter.importlib.import_module",
        import_module,
    )
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "substitute-backend",
        custom_nodes_root=custom_nodes_root,
    )

    status = adapter.status()

    assert status["available"] is True
    assert status["catalogRevision"] == "sha256:active"
    assert sys.modules[backend_module.__name__] is backend_module


def test_adapter_uses_active_services_matched_by_extension_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loaded service graphs should be reusable even when module files are opaque."""

    custom_nodes_root = _custom_nodes_root(tmp_path)
    sugar_root = custom_nodes_root / "SugarCubes"
    backend_module = ModuleType("opaque_sugarcubes_backend")
    active_services = SimpleNamespace(
        library=SimpleNamespace(
            extension_root=sugar_root.resolve(),
            library_status=_Library().library_status,
        )
    )
    backend_module.__dict__["active_backend_services"] = lambda: active_services
    monkeypatch.setitem(sys.modules, backend_module.__name__, backend_module)

    def import_module(name: str) -> object:
        """Fail if service-root matching does not find the loaded graph."""

        if name == "backend":
            return SimpleNamespace(
                active_backend_services=lambda: None,
                build_backend_services=lambda _root: pytest.fail(
                    "fallback factory should not be called"
                ),
            )
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(
        "substitute_backend.features.cube_library.infrastructure.sugarcubes_adapter.importlib.import_module",
        import_module,
    )
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "substitute-backend",
        custom_nodes_root=custom_nodes_root,
    )

    status = adapter.status()

    assert status["available"] is True
    assert status["catalogRevision"] == "sha256:active"


def test_adapter_falls_back_when_active_services_are_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Older SugarCubes builds should still work through the factory path."""

    fallback_services = SimpleNamespace(library=_Library())
    calls: list[Path] = []

    def build_backend_services(root: Path) -> object:
        """Record fallback construction and return fake services."""

        calls.append(root)
        return fallback_services

    def import_module(name: str) -> object:
        """Return a fake SugarCubes backend module."""

        if name != "backend":
            raise ModuleNotFoundError(name)
        return SimpleNamespace(
            active_backend_services=lambda: None,
            build_backend_services=build_backend_services,
        )

    monkeypatch.setattr(
        "substitute_backend.features.cube_library.infrastructure.sugarcubes_adapter.importlib.import_module",
        import_module,
    )
    custom_nodes_root = _custom_nodes_root(tmp_path)
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "substitute-backend",
        custom_nodes_root=custom_nodes_root,
    )

    status = adapter.status()

    assert status["available"] is True
    assert calls == [custom_nodes_root / "SugarCubes"]


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
            "message": "SugarCubes is not available on this target.",
        }
    ]


def _custom_nodes_root(tmp_path: Path) -> Path:
    """Create a custom_nodes root with a sibling SugarCubes extension."""

    custom_nodes_root = tmp_path / "custom_nodes"
    (custom_nodes_root / "SugarCubes").mkdir(parents=True)
    return custom_nodes_root

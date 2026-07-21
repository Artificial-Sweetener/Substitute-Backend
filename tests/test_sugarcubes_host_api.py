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
"""Versioned SugarCubes host API resolution tests."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from substitute_backend.infrastructure.sugarcubes_host_api import (
    SUGARCUBES_HOST_API_MODULE,
    SugarCubesHostApiResolutionStatus,
    SugarCubesHostApiResolver,
)


def test_resolver_returns_the_canonical_versioned_host_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consumers should resolve the exact module identity published by SugarCubes."""

    module = _host_api_module(version=1)
    monkeypatch.setitem(sys.modules, SUGARCUBES_HOST_API_MODULE, module)

    resolution = SugarCubesHostApiResolver().resolve()

    assert resolution.status is SugarCubesHostApiResolutionStatus.RESOLVED
    assert resolution.api is module


def test_resolver_rejects_an_unsupported_host_api_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A contract mismatch should fail closed instead of probing internals."""

    monkeypatch.setitem(sys.modules, SUGARCUBES_HOST_API_MODULE, _host_api_module(version=2))

    resolution = SugarCubesHostApiResolver().resolve()

    assert resolution.status is SugarCubesHostApiResolutionStatus.UNAVAILABLE
    assert "expected 1" in resolution.message


def test_resolver_reports_pending_before_sugarcubes_publishes_the_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Load order should remain retryable without importing SugarCubes twice."""

    monkeypatch.delitem(sys.modules, SUGARCUBES_HOST_API_MODULE, raising=False)

    resolution = SugarCubesHostApiResolver().resolve()

    assert resolution.status is SugarCubesHostApiResolutionStatus.PENDING
    assert resolution.api is None


def _host_api_module(*, version: int) -> ModuleType:
    """Return the minimal public API module required by the resolver."""

    module = ModuleType(SUGARCUBES_HOST_API_MODULE)
    module.__dict__["HOST_API_VERSION"] = version
    module.__dict__["active_backend_services"] = lambda: object()
    module.__dict__["register_cube_output_observer"] = lambda _observer: None
    module.__dict__["unregister_cube_output_observer"] = lambda _observer: None
    return module

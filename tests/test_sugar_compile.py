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
"""Tests for backend-owned Sugar compilation."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from aiohttp import web

from substitute_backend.api.errors import BackendHttpError
from substitute_backend.api.serialization import JsonObject
from substitute_backend.features.cube_library.application import (
    CubeLibraryService,
)
from substitute_backend.features.sugar_compile.api import (
    SugarCompileRouteHandlers,
    build_sugar_compile_route_handlers,
)
from substitute_backend.features.sugar_compile.application import (
    SugarCompileService,
    SugarCompileServices,
)
from substitute_backend.features.sugar_compile.domain import (
    SugarCompileError,
    SugarCompileRequest,
    SugarCompileResult,
    SugarCompileUnavailableError,
)
from substitute_backend.features.sugar_compile.infrastructure import (
    BackendCubeArtifactResolver,
)
from substitute_backend.infrastructure.logging import get_logger


class FakeRequest:
    """Minimal aiohttp-like request with injectable JSON body."""

    def __init__(self, body: object) -> None:
        """Store one request body."""

        self._body = body

    async def json(self) -> object:
        """Return the configured JSON body."""

        return self._body


class RecordingCompiler:
    """Record Sugar compile service calls and return deterministic payloads."""

    def __init__(self, *, available: bool = True, failure: Exception | None = None) -> None:
        """Configure availability and optional compile failure."""

        self.calls: list[tuple[str, Path]] = []
        self._available = available
        self._failure = failure

    def is_available(self) -> bool:
        """Return configured availability."""

        return self._available

    def unavailable_reason(self) -> str:
        """Return a deterministic unavailable message."""

        return "Sugar-DSL is not installed in the ComfyUI environment."

    def compile(self, *, script_text: str, output_dir: Path) -> SugarCompileResult:
        """Record the compile request and return a wrapped artifact payload."""

        self.calls.append((script_text, output_dir))
        if self._failure is not None:
            raise self._failure
        return SugarCompileResult(
            prompt={"1": {"class_type": "KSampler"}},
            workflow={"nodes": []},
        )


class RecordingCubeLibraryGateway:
    """Return raw Cube Library artifacts while recording load calls."""

    def __init__(
        self,
        *,
        invalid_cube_id: str = "",
        invalid_version: str = "",
        missing_cube_id: str = "",
    ) -> None:
        """Configure load recording and failure controls."""

        self.latest_loads: list[str] = []
        self.version_loads: list[tuple[str, str]] = []
        self._invalid_cube_id = invalid_cube_id
        self._invalid_version = invalid_version
        self._missing_cube_id = missing_cube_id

    def status(self) -> JsonObject:
        """Return available status."""

        return {"schemaVersion": 1, "available": True}

    def catalog(
        self,
        *,
        include_disabled: bool,
        diagnostic_context: object | None = None,
    ) -> JsonObject:
        """Return an empty catalog."""

        _ = include_disabled, diagnostic_context
        return {"schemaVersion": 1, "cubes": []}

    def load_cube(
        self,
        cube_id: str,
        *,
        diagnostic_context: object | None = None,
    ) -> JsonObject:
        """Return a latest cube artifact."""

        _ = diagnostic_context
        self.latest_loads.append(cube_id)
        return self._artifact(cube_id, "latest")

    def list_cube_versions(self, cube_id: str) -> JsonObject:
        """Return no versions."""

        _ = cube_id
        return {"schemaVersion": 1, "versions": []}

    def load_cube_version(
        self,
        *,
        cube_id: str,
        version: str,
        diagnostic_context: object | None = None,
    ) -> JsonObject:
        """Return a versioned cube artifact."""

        _ = diagnostic_context
        self.version_loads.append((cube_id, version))
        return self._artifact(cube_id, version)

    def prewarm_cube_version(self, *, cube_id: str, version: str) -> JsonObject:
        """Return accepted prewarm status."""

        _ = cube_id, version
        return {"schemaVersion": 1, "accepted": True}

    def icon_asset(self, cube_id: str) -> tuple[bytes, str]:
        """Return icon content."""

        _ = cube_id
        return b"", "image/png"

    def list_packs(self) -> JsonObject:
        """Return no packs."""

        return {"schemaVersion": 1, "packs": []}

    def preflight_pack(self, *, owner: str, repo: str, branch: str) -> JsonObject:
        """Return a no-op preflight payload."""

        _ = owner, repo, branch
        return {"schemaVersion": 1}

    def add_pack(
        self,
        *,
        owner: str,
        repo: str,
        branch: str,
        enabled: bool,
        auto_update: bool,
        sync_immediately: bool,
    ) -> JsonObject:
        """Return a no-op add payload."""

        _ = owner, repo, branch, enabled, auto_update, sync_immediately
        return {"schemaVersion": 1}

    def update_pack(
        self,
        *,
        owner: str,
        repo: str,
        branch: str | None,
        enabled: bool | None,
        auto_update: bool | None,
    ) -> JsonObject:
        """Return a no-op update payload."""

        _ = owner, repo, branch, enabled, auto_update
        return {"schemaVersion": 1}

    def remove_pack(self, *, owner: str, repo: str) -> JsonObject:
        """Return a no-op remove payload."""

        _ = owner, repo
        return {"schemaVersion": 1}

    def sync_pack(self, *, owner: str, repo: str) -> JsonObject:
        """Return a no-op sync payload."""

        _ = owner, repo
        return {"schemaVersion": 1}

    def sync_all_packs(self) -> JsonObject:
        """Return a no-op sync-all payload."""

        return {"schemaVersion": 1}

    def readiness(self) -> JsonObject:
        """Return readiness."""

        return {"schemaVersion": 1, "ready": True}

    def dependency_readiness(self) -> JsonObject:
        """Return dependency readiness."""

        return {"schemaVersion": 1, "ready": True}

    def repair_dependencies(
        self,
        *,
        baseline_only: bool,
        approved_node_ids: tuple[str, ...],
        sync_enabled_repos: bool,
    ) -> JsonObject:
        """Return repair result."""

        _ = baseline_only, approved_node_ids, sync_enabled_repos
        return {"schemaVersion": 1, "restartRequired": False}

    def _artifact(self, cube_id: str, version: str) -> JsonObject:
        """Build a raw Cube Library artifact."""

        if cube_id == self._missing_cube_id:
            raise BackendHttpError(
                message="Missing cube.",
                status=404,
                code="cube-library-not-found",
            )
        declared_cube_id = self._invalid_cube_id or cube_id
        declared_version = self._invalid_version or version
        return {
            "schemaVersion": 1,
            "cubeId": declared_cube_id,
            "version": declared_version,
            "cube": {
                "cube_id": cube_id,
                "version": version,
                "implementation": {
                    "nodes": {
                        "node": {
                            "class_type": "TestNode",
                            "inputs": {"value": 1},
                        }
                    },
                    "inputs": {},
                    "outputs": {},
                    "definitions": {},
                    "subgraphs": [],
                    "layout": {},
                },
                "surface": {
                    "default_flavor_id": "default",
                    "controls": [],
                },
                "flavors": {
                    "authored": [
                        {
                            "id": "default",
                            "name": "Default",
                            "values": {},
                        }
                    ]
                },
            },
        }


def _request(body: object) -> web.Request:
    """Return a typed fake aiohttp request."""

    return cast(web.Request, FakeRequest(body))


def _payload(response: web.StreamResponse) -> dict[str, Any]:
    """Decode one JSON response."""

    text = cast(web.Response, response).text or "{}"
    return cast(dict[str, Any], json.loads(text))


def _handlers(compiler: RecordingCompiler) -> SugarCompileRouteHandlers:
    """Build Sugar compile route handlers with a fake compiler."""

    return build_sugar_compile_route_handlers(
        SugarCompileServices(
            compile=SugarCompileService(
                compiler=compiler,
                logger=get_logger("tests.sugar_compile.service"),
            )
        ),
        logger=get_logger("tests.sugar_compile.routes"),
    )


def test_compile_route_rejects_non_object_json() -> None:
    """Sugar compile route should reject array request bodies."""

    async def run() -> None:
        response = await _handlers(RecordingCompiler()).compile_sugar(_request([]))

        assert response.status == 400
        assert _payload(response)["error"]["code"] == "sugar-compile-invalid-request"

    asyncio.run(run())


def test_compile_route_rejects_missing_script_text() -> None:
    """Sugar compile route should require script text before invoking compiler."""

    async def run() -> None:
        compiler = RecordingCompiler()
        response = await _handlers(compiler).compile_sugar(
            _request(
                {
                    "schemaVersion": 1,
                    "outputDir": "E:\\outputs",
                }
            )
        )

        assert response.status == 400
        assert _payload(response)["error"]["code"] == "sugar-compile-invalid-request"
        assert compiler.calls == []

    asyncio.run(run())


def test_compile_route_returns_wrapped_prompt_and_workflow() -> None:
    """Sugar compile route should return the compiler artifact payload."""

    async def run() -> None:
        compiler = RecordingCompiler()
        response = await _handlers(compiler).compile_sugar(
            _request(
                {
                    "schemaVersion": 1,
                    "sugarScriptText": 'use "Owner/Repo/demo.cube" as demo',
                    "outputDir": "E:\\outputs",
                }
            )
        )

        assert response.status == 200
        assert _payload(response) == {
            "prompt": {"1": {"class_type": "KSampler"}},
            "workflow": {"nodes": []},
        }
        assert compiler.calls == [('use "Owner/Repo/demo.cube" as demo', Path("E:\\outputs"))]

    asyncio.run(run())


def test_compile_service_maps_unavailable_errors() -> None:
    """Sugar compile service should preserve unavailable setup failures."""

    service = SugarCompileService(
        compiler=RecordingCompiler(failure=SugarCompileUnavailableError("Sugar-DSL is missing.")),
        logger=logging.getLogger("tests.sugar_compile.service"),
    )

    request = SugarCompileRequest(
        sugar_script_text='use "Owner/Repo/demo.cube" as demo',
        output_dir=Path("E:\\outputs"),
    )

    with pytest.raises(BackendHttpError) as error_info:
        service.compile(request)

    assert error_info.value.status == 503
    assert error_info.value.code == "sugar-compile-unavailable"


def test_compile_service_maps_expected_compile_failures() -> None:
    """Sugar compile service should preserve structured compile failures."""

    service = SugarCompileService(
        compiler=RecordingCompiler(
            failure=SugarCompileError(
                "Cube invalid.",
                status=502,
                code="sugar-cube-artifact-invalid",
            )
        ),
        logger=logging.getLogger("tests.sugar_compile.service"),
    )

    request = SugarCompileRequest(
        sugar_script_text='use "Owner/Repo/demo.cube" as demo',
        output_dir=Path("E:\\outputs"),
    )

    with pytest.raises(BackendHttpError) as error_info:
        service.compile(request)

    assert error_info.value.status == 502
    assert error_info.value.code == "sugar-cube-artifact-invalid"


def test_cube_artifact_resolver_loads_latest_and_pinned_artifacts_once() -> None:
    """Backend resolver should memoize equivalent cube/version requests."""

    gateway = RecordingCubeLibraryGateway()
    resolver = BackendCubeArtifactResolver(
        cube_library=CubeLibraryService(gateway=gateway),
        logger=get_logger("tests.sugar_compile.resolver"),
    )

    latest_a = resolver.resolve(
        alias="latestA",
        cube_id="Owner/Repo/latest.cube",
        requested_version=None,
    )
    latest_b = resolver.resolve(
        alias="latestB",
        cube_id="Owner/Repo/latest.cube",
        requested_version=None,
    )
    pinned_a = resolver.resolve(
        alias="pinnedA",
        cube_id="Owner/Repo/pinned.cube",
        requested_version="1.0.0",
    )
    pinned_b = resolver.resolve(
        alias="pinnedB",
        cube_id="Owner/Repo/pinned.cube",
        requested_version="1.0.0",
    )

    assert latest_a is latest_b
    assert pinned_a is pinned_b
    assert gateway.latest_loads == ["Owner/Repo/latest.cube"]
    assert gateway.version_loads == [("Owner/Repo/pinned.cube", "1.0.0")]


def test_cube_artifact_resolver_rejects_identity_mismatch() -> None:
    """Backend resolver should reject Cube Library artifact id mismatches."""

    resolver = BackendCubeArtifactResolver(
        cube_library=CubeLibraryService(
            gateway=RecordingCubeLibraryGateway(invalid_cube_id="Other/Repo/demo.cube")
        ),
        logger=get_logger("tests.sugar_compile.resolver"),
    )

    with pytest.raises(SugarCompileError) as error_info:
        resolver.resolve(
            alias="demo",
            cube_id="Owner/Repo/demo.cube",
            requested_version=None,
        )

    assert error_info.value.code == "sugar-cube-artifact-invalid"


def test_cube_artifact_resolver_returns_sugar_resolved_artifact() -> None:
    """Backend resolver should return Sugar-DSL's resolved artifact model."""

    resolver = BackendCubeArtifactResolver(
        cube_library=CubeLibraryService(gateway=RecordingCubeLibraryGateway()),
        logger=get_logger("tests.sugar_compile.resolver"),
    )

    resolved = resolver.resolve(
        alias="demo",
        cube_id="Owner/Repo/demo.cube",
        requested_version="1.2.3",
    )
    identity = cast(Any, resolved).identity
    cube = cast(Mapping[str, object], cast(Any, resolved).cube)

    assert identity.cube_id == "Owner/Repo/demo.cube"
    assert identity.requested_version == "1.2.3"
    assert identity.resolved_version == "1.2.3"
    assert cube["cube_id"] == "Owner/Repo/demo.cube"

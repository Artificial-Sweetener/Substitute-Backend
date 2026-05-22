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
"""Tests for Substitute BackEnd Cube Library route handlers."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any, cast

import pytest
from aiohttp import web

from substitute_backend.api.errors import BackendHttpError
from substitute_backend.api.serialization import JsonObject
from substitute_backend.features.cube_library.api import (
    CubeLibraryRouteHandlers,
    build_cube_library_route_handlers,
)
from substitute_backend.features.cube_library.application import (
    CubeLibraryService,
    CubeLibraryServices,
)
from substitute_backend.infrastructure.diagnostics import (
    CUBE_LIBRARY_DIAGNOSTICS,
    DIAGNOSTICS_ENV_VAR,
    DiagnosticContext,
    diagnostics_from_environment,
)
from substitute_backend.infrastructure.logging import get_logger


class FakeRequest:
    """Minimal aiohttp-like request object for route handler tests."""

    def __init__(
        self,
        *,
        query: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> None:
        """Store query and JSON body test data."""

        self.query = dict(query or {})
        self.headers = dict(headers or {})
        self._body = body or {}

    async def json(self) -> dict[str, object]:
        """Return the configured JSON body."""

        return self._body


def _request(
    *,
    query: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    body: dict[str, object] | None = None,
) -> web.Request:
    """Return a typed fake aiohttp request for route handler tests."""

    return cast(web.Request, FakeRequest(query=query, headers=headers, body=body))


class RecordingGateway:
    """Record Cube Library gateway calls and return deterministic payloads."""

    def __init__(self) -> None:
        """Initialize an empty call list."""

        self.calls: list[tuple[str, dict[str, object]]] = []

    def status(self) -> JsonObject:
        """Return available status."""

        self.calls.append(("status", {}))
        return {"schemaVersion": 1, "available": True}

    def catalog(
        self,
        *,
        include_disabled: bool,
        diagnostic_context: DiagnosticContext | None = None,
    ) -> JsonObject:
        """Return a catalog response."""

        _ = diagnostic_context
        self.calls.append(("catalog", {"include_disabled": include_disabled}))
        return {"schemaVersion": 1, "cubes": []}

    def load_cube(
        self,
        cube_id: str,
        *,
        diagnostic_context: DiagnosticContext | None = None,
    ) -> JsonObject:
        """Return a loaded artifact response."""

        _ = diagnostic_context
        self.calls.append(("load_cube", {"cube_id": cube_id}))
        return {"schemaVersion": 1, "cubeId": cube_id, "cube": {}}

    def list_cube_versions(self, cube_id: str) -> JsonObject:
        """Return version records for one cube."""

        self.calls.append(("list_cube_versions", {"cube_id": cube_id}))
        return {"schemaVersion": 1, "cubeId": cube_id, "versions": []}

    def load_cube_version(
        self,
        *,
        cube_id: str,
        version: str,
        diagnostic_context: DiagnosticContext | None = None,
    ) -> JsonObject:
        """Return a loaded version artifact response."""

        _ = diagnostic_context
        self.calls.append(
            (
                "load_cube_version",
                {
                    "cube_id": cube_id,
                    "version": version,
                },
            )
        )
        return {
            "schemaVersion": 1,
            "cubeId": cube_id,
            "version": version,
            "cube": {},
        }

    def prewarm_cube_version(
        self,
        *,
        cube_id: str,
        version: str,
    ) -> JsonObject:
        """Return accepted prewarm response."""

        self.calls.append(
            (
                "prewarm_cube_version",
                {
                    "cube_id": cube_id,
                    "version": version,
                },
            )
        )
        return {"schemaVersion": 1, "accepted": True}

    def icon_asset(self, cube_id: str) -> tuple[bytes, str]:
        """Return icon bytes and media type."""

        self.calls.append(("icon_asset", {"cube_id": cube_id}))
        if cube_id == "Owner/Repo/svg.cube":
            return b"<svg></svg>", "image/svg+xml"
        return b"png-bytes", "image/png"

    def list_packs(self) -> JsonObject:
        """Return a pack listing."""

        self.calls.append(("list_packs", {}))
        return {"schemaVersion": 1, "packs": []}

    def preflight_pack(self, *, owner: str, repo: str, branch: str) -> JsonObject:
        """Return preflight response."""

        self.calls.append(("preflight_pack", {"owner": owner, "repo": repo, "branch": branch}))
        return {"schemaVersion": 1, "preflight": {"owner": owner, "repo": repo}}

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
        """Return add response."""

        self.calls.append(
            (
                "add_pack",
                {
                    "owner": owner,
                    "repo": repo,
                    "branch": branch,
                    "enabled": enabled,
                    "auto_update": auto_update,
                    "sync_immediately": sync_immediately,
                },
            )
        )
        return {"schemaVersion": 1, "pack": {"repoRef": f"{owner}/{repo}"}}

    def update_pack(
        self,
        *,
        owner: str,
        repo: str,
        branch: str | None,
        enabled: bool | None,
        auto_update: bool | None,
    ) -> JsonObject:
        """Return update response."""

        self.calls.append(
            (
                "update_pack",
                {
                    "owner": owner,
                    "repo": repo,
                    "branch": branch,
                    "enabled": enabled,
                    "auto_update": auto_update,
                },
            )
        )
        return {"schemaVersion": 1, "pack": {"repoRef": f"{owner}/{repo}"}}

    def remove_pack(self, *, owner: str, repo: str) -> JsonObject:
        """Return remove response."""

        self.calls.append(("remove_pack", {"owner": owner, "repo": repo}))
        return {"schemaVersion": 1, "removed": {"owner": owner, "repo": repo}}

    def sync_pack(self, *, owner: str, repo: str) -> JsonObject:
        """Return sync response."""

        self.calls.append(("sync_pack", {"owner": owner, "repo": repo}))
        return {"schemaVersion": 1, "pack": {"repoRef": f"{owner}/{repo}"}}

    def sync_all_packs(self) -> JsonObject:
        """Return sync-all response."""

        self.calls.append(("sync_all_packs", {}))
        return {"schemaVersion": 1, "packs": []}

    def readiness(self) -> JsonObject:
        """Return readiness response."""

        self.calls.append(("readiness", {}))
        return {"schemaVersion": 1, "ready": True}


def _handlers(gateway: RecordingGateway) -> CubeLibraryRouteHandlers:
    """Build route handlers for a fake gateway."""

    return build_cube_library_route_handlers(
        CubeLibraryServices(library=CubeLibraryService(gateway=gateway)),
        logger=get_logger("tests.cube_library.routes"),
        diagnostics=diagnostics_from_environment(get_logger("tests.cube_library.diagnostics")),
    )


def _payload(response: Any) -> dict[str, Any]:
    """Decode one aiohttp JSON response."""

    return cast(dict[str, Any], json.loads(response.text or "{}"))


def _diagnostic_records(
    caplog: pytest.LogCaptureFixture,
) -> list[logging.LogRecord]:
    """Return captured Substitute diagnostic log records."""

    return [
        record
        for record in caplog.records
        if getattr(record, "diagnostic_feature", "") == CUBE_LIBRARY_DIAGNOSTICS
    ]


def test_catalog_route_parses_include_disabled_query() -> None:
    """Catalog route should pass includeDisabled through as a boolean."""

    async def run() -> None:
        gateway = RecordingGateway()
        response = await _handlers(gateway).catalog(_request(query={"includeDisabled": "true"}))

        assert response.status == 200
        assert _payload(response)["schemaVersion"] == 1
        assert gateway.calls == [("catalog", {"include_disabled": True})]

    asyncio.run(run())


def test_route_diagnostics_are_silent_by_default(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cube Library route diagnostics should require explicit environment opt-in."""

    monkeypatch.delenv(DIAGNOSTICS_ENV_VAR, raising=False)

    async def run() -> None:
        gateway = RecordingGateway()
        with caplog.at_level(logging.DEBUG):
            response = await _handlers(gateway).catalog(
                _request(headers={"X-Substitute-Cube-Trace": "trace-1"})
            )

        assert response.status == 200
        assert _diagnostic_records(caplog) == []

    asyncio.run(run())


def test_route_diagnostics_require_trace_header(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cube Library route diagnostics should remain targeted to traced requests."""

    monkeypatch.setenv(DIAGNOSTICS_ENV_VAR, "cube-library")

    async def run() -> None:
        gateway = RecordingGateway()
        with caplog.at_level(logging.DEBUG):
            response = await _handlers(gateway).catalog(_request())

        assert response.status == 200
        assert _diagnostic_records(caplog) == []

    asyncio.run(run())


def test_route_diagnostics_emit_with_env_flag_and_trace_header(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cube Library route diagnostics should emit only for explicitly traced requests."""

    monkeypatch.setenv(DIAGNOSTICS_ENV_VAR, "cube-library")

    async def run() -> None:
        gateway = RecordingGateway()
        with caplog.at_level(logging.DEBUG):
            response = await _handlers(gateway).catalog(
                _request(headers={"X-Substitute-Cube-Trace": "trace-1"})
            )

        events = {getattr(record, "diagnostic_event", "") for record in _diagnostic_records(caplog)}
        assert response.status == 200
        assert events == {"backend_catalog_route_start", "backend_catalog_route_return"}
        assert all(
            getattr(record, "trace_id", "") == "trace-1" for record in _diagnostic_records(caplog)
        )

    asyncio.run(run())


def test_route_diagnostics_respect_debug_level(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cube Library route diagnostics should not bypass the configured log level."""

    monkeypatch.setenv(DIAGNOSTICS_ENV_VAR, "cube-library")

    async def run() -> None:
        gateway = RecordingGateway()
        with caplog.at_level(logging.INFO):
            response = await _handlers(gateway).catalog(
                _request(headers={"X-Substitute-Cube-Trace": "trace-1"})
            )

        assert response.status == 200
        assert _diagnostic_records(caplog) == []

    asyncio.run(run())


def test_load_route_requires_query_cube_id() -> None:
    """Load route should reject missing cube ids before calling the gateway."""

    async def run() -> None:
        gateway = RecordingGateway()
        response = await _handlers(gateway).load_cube(_request())

        assert response.status == 400
        assert _payload(response)["error"]["code"] == "invalid-query"
        assert gateway.calls == []

    asyncio.run(run())


def test_versions_route_delegates_to_gateway() -> None:
    """Versions route should pass cube id through to the gateway."""

    async def run() -> None:
        gateway = RecordingGateway()
        response = await _handlers(gateway).cube_versions(
            _request(query={"cubeId": "Owner/Repo/demo.cube"})
        )

        assert response.status == 200
        assert _payload(response)["versions"] == []
        assert gateway.calls == [("list_cube_versions", {"cube_id": "Owner/Repo/demo.cube"})]

    asyncio.run(run())


def test_load_route_delegates_version_selector() -> None:
    """Load route should pass a version selector when provided."""

    async def run() -> None:
        gateway = RecordingGateway()
        response = await _handlers(gateway).load_cube(
            _request(
                query={
                    "cubeId": "Owner/Repo/demo.cube",
                    "version": "1.2.3",
                }
            )
        )

        assert response.status == 200
        assert _payload(response)["version"] == "1.2.3"
        assert gateway.calls == [
            (
                "load_cube_version",
                {
                    "cube_id": "Owner/Repo/demo.cube",
                    "version": "1.2.3",
                },
            )
        ]

    asyncio.run(run())


def test_prewarm_route_delegates_version_request() -> None:
    """Prewarm route should schedule a version warmup through the gateway."""

    async def run() -> None:
        gateway = RecordingGateway()
        response = await _handlers(gateway).prewarm_cube(
            _request(
                body={
                    "cubeId": "Owner/Repo/demo.cube",
                    "version": "1.2.3",
                }
            )
        )

        assert response.status == 200
        assert _payload(response) == {"schemaVersion": 1, "accepted": True}
        assert gateway.calls == [
            (
                "prewarm_cube_version",
                {
                    "cube_id": "Owner/Repo/demo.cube",
                    "version": "1.2.3",
                },
            )
        ]

    asyncio.run(run())


def test_icon_asset_route_returns_png_bytes() -> None:
    """Icon asset route should return bytes and media type from the gateway."""

    async def run() -> None:
        gateway = RecordingGateway()
        response = await _handlers(gateway).icon_asset(
            _request(query={"cubeId": "Owner/Repo/Icon.cube"})
        )
        web_response = cast(web.Response, response)

        assert response.status == 200
        assert web_response.body == b"png-bytes"
        assert response.content_type == "image/png"
        assert gateway.calls == [("icon_asset", {"cube_id": "Owner/Repo/Icon.cube"})]

    asyncio.run(run())


def test_icon_asset_route_returns_svg_bytes() -> None:
    """Icon asset route should preserve SVG media type."""

    async def run() -> None:
        gateway = RecordingGateway()
        response = await _handlers(gateway).icon_asset(
            _request(query={"cubeId": "Owner/Repo/svg.cube"})
        )
        web_response = cast(web.Response, response)

        assert response.status == 200
        assert web_response.body == b"<svg></svg>"
        assert response.content_type == "image/svg+xml"
        assert gateway.calls == [("icon_asset", {"cube_id": "Owner/Repo/svg.cube"})]

    asyncio.run(run())


def test_icon_asset_route_requires_query_cube_id() -> None:
    """Icon asset route should reject missing cube ids before gateway calls."""

    async def run() -> None:
        gateway = RecordingGateway()
        response = await _handlers(gateway).icon_asset(_request())

        assert response.status == 400
        assert _payload(response)["error"]["code"] == "invalid-query"
        assert gateway.calls == []

    asyncio.run(run())


def test_icon_asset_route_preserves_backend_errors() -> None:
    """Icon asset route should return structured gateway errors."""

    class MissingIconGateway(RecordingGateway):
        """Gateway that reports missing icon assets."""

        def icon_asset(self, cube_id: str) -> tuple[bytes, str]:
            """Raise a typed backend error."""

            _ = cube_id
            raise BackendHttpError(
                message="Cube icon not found.",
                status=404,
                code="cube-library-not-found",
            )

    async def run() -> None:
        response = await _handlers(MissingIconGateway()).icon_asset(
            _request(query={"cubeId": "Owner/Repo/Plain.cube"})
        )

        assert response.status == 404
        assert _payload(response)["error"] == {
            "code": "cube-library-not-found",
            "message": "Cube icon not found.",
        }

    asyncio.run(run())


def test_pack_routes_delegate_to_gateway_without_patch() -> None:
    """Pack management routes should use GET, POST, and DELETE semantics only."""

    async def run() -> None:
        gateway = RecordingGateway()
        handlers = _handlers(gateway)

        add_response = await handlers.add_pack(
            _request(
                body={
                    "owner": "ExampleOwner",
                    "repo": "ExampleCubes",
                    "branch": "main",
                    "enabled": False,
                    "autoUpdate": True,
                    "syncImmediately": False,
                }
            )
        )
        update_response = await handlers.update_pack(
            _request(
                body={
                    "owner": "ExampleOwner",
                    "repo": "ExampleCubes",
                    "enabled": True,
                }
            )
        )
        remove_response = await handlers.remove_pack(
            _request(query={"owner": "ExampleOwner", "repo": "ExampleCubes"})
        )

        assert add_response.status == 201
        assert update_response.status == 200
        assert remove_response.status == 200
        assert gateway.calls == [
            (
                "add_pack",
                {
                    "owner": "ExampleOwner",
                    "repo": "ExampleCubes",
                    "branch": "main",
                    "enabled": False,
                    "auto_update": True,
                    "sync_immediately": False,
                },
            ),
            (
                "update_pack",
                {
                    "owner": "ExampleOwner",
                    "repo": "ExampleCubes",
                    "branch": None,
                    "enabled": True,
                    "auto_update": None,
                },
            ),
            ("remove_pack", {"owner": "ExampleOwner", "repo": "ExampleCubes"}),
        ]

    asyncio.run(run())


def test_gateway_errors_return_structured_json() -> None:
    """Expected gateway errors should preserve status and code."""

    class FailingGateway(RecordingGateway):
        """Gateway that fails catalog requests."""

        def catalog(
            self,
            *,
            include_disabled: bool,
            diagnostic_context: DiagnosticContext | None = None,
        ) -> JsonObject:
            """Raise a typed backend error."""

            _ = include_disabled, diagnostic_context
            raise BackendHttpError(
                message="Catalog unavailable.",
                status=503,
                code="catalog-unavailable",
            )

    async def run() -> None:
        response = await _handlers(FailingGateway()).catalog(_request())

        assert response.status == 503
        assert _payload(response)["error"] == {
            "code": "catalog-unavailable",
            "message": "Catalog unavailable.",
        }

    asyncio.run(run())

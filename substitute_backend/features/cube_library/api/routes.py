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
"""HTTP route handlers for Substitute BackEnd Cube Library APIs."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from aiohttp import web

from substitute_backend.api.errors import BackendHttpError, json_error
from substitute_backend.features.cube_library.application import CubeLibraryServices
from substitute_backend.infrastructure.diagnostics import (
    CUBE_LIBRARY_DIAGNOSTICS,
    DiagnosticContext,
    DiagnosticLogger,
)

RouteHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]
CUBE_LIBRARY_TRACE_HEADER = "X-Substitute-Cube-Trace"


@dataclass(frozen=True)
class CubeLibraryRouteHandlers:
    """Concrete Cube Library route callables used for registration and tests."""

    status: RouteHandler
    catalog: RouteHandler
    cube_versions: RouteHandler
    load_cube: RouteHandler
    prewarm_cube: RouteHandler
    icon_asset: RouteHandler
    list_packs: RouteHandler
    preflight_pack: RouteHandler
    add_pack: RouteHandler
    update_pack: RouteHandler
    remove_pack: RouteHandler
    sync_pack: RouteHandler
    sync_all_packs: RouteHandler
    readiness: RouteHandler
    dependency_readiness: RouteHandler
    repair_dependencies: RouteHandler


def build_cube_library_route_handlers(
    services: CubeLibraryServices,
    logger: logging.Logger,
    *,
    diagnostics: DiagnosticLogger,
) -> CubeLibraryRouteHandlers:
    """Build thin HTTP handlers over Cube Library application services."""

    async def status(request: web.Request) -> web.Response:
        """Return target Cube Library availability."""

        _ = request
        return web.json_response(services.library.status())

    async def catalog(request: web.Request) -> web.Response:
        """Return target Cube Library catalog metadata."""

        try:
            include_disabled = _parse_bool(request.query.get("includeDisabled"), False)
            diagnostic_context = _route_diagnostic_context(request)
            _log_route_diagnostic(
                diagnostics,
                diagnostic_context,
                "backend_catalog_route_start",
                include_disabled=include_disabled,
            )
            payload = services.library.catalog(
                include_disabled=include_disabled,
                diagnostic_context=diagnostic_context,
            )
            cubes = payload.get("cubes")
            _log_route_diagnostic(
                diagnostics,
                diagnostic_context,
                "backend_catalog_route_return",
                catalog_revision=payload.get("catalogRevision", ""),
                cube_count=len(cubes) if isinstance(cubes, list) else "",
            )
            return web.json_response(payload)
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary
            logger.exception(
                "cube library catalog route failed",
                extra={
                    "operation": "cube-library-catalog",
                    "route": "/substitute/v1/cube-library/catalog",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Cube Library catalog unavailable.",
                    status=500,
                    code="catalog-unavailable",
                )
            )

    async def load_cube(request: web.Request) -> web.Response:
        """Return one canonical cube artifact by query cube id."""

        try:
            cube_id = _required_query(request, "cubeId")
            version = _optional_query(request, "version")
            diagnostic_context = _route_diagnostic_context(request)
            _log_route_diagnostic(
                diagnostics,
                diagnostic_context,
                "backend_load_cube_route_start",
                cube_id=cube_id,
                version=version or "",
            )
            if version:
                payload = services.library.load_cube_version(
                    cube_id=cube_id,
                    version=version,
                    diagnostic_context=diagnostic_context,
                )
            else:
                payload = services.library.load_cube(
                    cube_id,
                    diagnostic_context=diagnostic_context,
                )
            _log_route_diagnostic(
                diagnostics,
                diagnostic_context,
                "backend_load_cube_route_return",
                requested_cube_id=cube_id,
                loaded_cube_id=payload.get("cubeId", ""),
                loaded_version=payload.get("version", ""),
                content_hash=payload.get("contentHash", ""),
            )
            return web.json_response(payload)
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary
            logger.exception(
                "cube library load route failed",
                extra={
                    "operation": "cube-library-load",
                    "route": "/substitute/v1/cube-library/cubes/load",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Cube artifact could not be loaded.",
                    status=500,
                    code="cube-load-failed",
                )
            )

    async def prewarm_cube(request: web.Request) -> web.Response:
        """Schedule best-effort warming for one cube version artifact."""

        try:
            body = await _json_object_body(request)
            cube_id = _required_str(body, "cubeId")
            version = _required_str(body, "version")
            return web.json_response(
                services.library.prewarm_cube_version(
                    cube_id=cube_id,
                    version=version,
                )
            )
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary
            logger.exception(
                "cube library prewarm route failed",
                extra={
                    "operation": "cube-library-prewarm",
                    "route": "/substitute/v1/cube-library/cubes/prewarm",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Cube artifact prewarm could not be scheduled.",
                    status=500,
                    code="cube-prewarm-failed",
                )
            )

    async def cube_versions(request: web.Request) -> web.Response:
        """Return versions for one cube id."""

        try:
            cube_id = _required_query(request, "cubeId")
            return web.json_response(services.library.list_cube_versions(cube_id))
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary
            logger.exception(
                "cube library versions route failed",
                extra={
                    "operation": "cube-library-versions",
                    "route": "/substitute/v1/cube-library/cubes/versions",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Cube versions could not be listed.",
                    status=500,
                    code="cube-versions-failed",
                )
            )

    async def icon_asset(request: web.Request) -> web.Response:
        """Return one cube icon asset."""

        try:
            cube_id = _required_query(request, "cubeId")
            content, media_type = services.library.icon_asset(cube_id)
            return web.Response(body=content, content_type=media_type)
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary
            logger.exception(
                "cube library icon route failed",
                extra={
                    "operation": "cube-library-icon",
                    "route": "/substitute/v1/cube-library/cubes/icon",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Cube icon asset could not be loaded.",
                    status=500,
                    code="cube-icon-load-failed",
                )
            )

    async def list_packs(request: web.Request) -> web.Response:
        """Return tracked Cube Packs."""

        _ = request
        try:
            return web.json_response(services.library.list_packs())
        except BackendHttpError as exc:
            return json_error(exc)

    async def preflight_pack(request: web.Request) -> web.Response:
        """Return candidate Cube Pack preflight results."""

        try:
            body = await _json_object_body(request)
            return web.json_response(
                services.library.preflight_pack(
                    owner=_required_str(body, "owner"),
                    repo=_required_str(body, "repo"),
                    branch=_optional_str(body, "branch") or "main",
                )
            )
        except BackendHttpError as exc:
            return json_error(exc)

    async def add_pack(request: web.Request) -> web.Response:
        """Track a Cube Pack on the active target."""

        try:
            body = await _json_object_body(request)
            return web.json_response(
                services.library.add_pack(
                    owner=_required_str(body, "owner"),
                    repo=_required_str(body, "repo"),
                    branch=_optional_str(body, "branch") or "main",
                    enabled=_optional_bool(body, "enabled", True),
                    auto_update=_optional_bool(body, "autoUpdate", False),
                    sync_immediately=_optional_bool(body, "syncImmediately", True),
                ),
                status=201,
            )
        except BackendHttpError as exc:
            return json_error(exc)

    async def update_pack(request: web.Request) -> web.Response:
        """Update a tracked Cube Pack."""

        try:
            body = await _json_object_body(request)
            return web.json_response(
                services.library.update_pack(
                    owner=_required_str(body, "owner"),
                    repo=_required_str(body, "repo"),
                    branch=_optional_str(body, "branch"),
                    enabled=_nullable_bool(body, "enabled"),
                    auto_update=_nullable_bool(body, "autoUpdate"),
                )
            )
        except BackendHttpError as exc:
            return json_error(exc)

    async def remove_pack(request: web.Request) -> web.Response:
        """Remove a tracked Cube Pack from the active target."""

        try:
            owner = _required_query(request, "owner")
            repo = _required_query(request, "repo")
            return web.json_response(services.library.remove_pack(owner=owner, repo=repo))
        except BackendHttpError as exc:
            return json_error(exc)

    async def sync_pack(request: web.Request) -> web.Response:
        """Sync one tracked Cube Pack synchronously."""

        try:
            body = await _json_object_body(request)
            return web.json_response(
                services.library.sync_pack(
                    owner=_required_str(body, "owner"),
                    repo=_required_str(body, "repo"),
                )
            )
        except BackendHttpError as exc:
            return json_error(exc)

    async def sync_all_packs(request: web.Request) -> web.Response:
        """Sync every enabled Cube Pack synchronously."""

        _ = request
        try:
            return web.json_response(services.library.sync_all_packs())
        except BackendHttpError as exc:
            return json_error(exc)

    async def readiness(request: web.Request) -> web.Response:
        """Return read-only dependency readiness for the target library."""

        _ = request
        try:
            return web.json_response(services.library.readiness())
        except BackendHttpError as exc:
            return json_error(exc)

    async def dependency_readiness(request: web.Request) -> web.Response:
        """Return install-capable dependency readiness for the target library."""

        _ = request
        try:
            return web.json_response(services.library.dependency_readiness())
        except BackendHttpError as exc:
            return json_error(exc)

    async def repair_dependencies(request: web.Request) -> web.Response:
        """Repair approved target library dependencies."""

        try:
            body = await _json_object_body(request)
            approved_node_ids = body.get("approvedNodeIds")
            if not isinstance(approved_node_ids, list):
                approved_node_ids = []
            return web.json_response(
                services.library.repair_dependencies(
                    baseline_only=_optional_bool(body, "baselineOnly", False),
                    approved_node_ids=tuple(
                        value.strip()
                        for value in approved_node_ids
                        if isinstance(value, str) and value.strip()
                    ),
                    sync_enabled_repos=_optional_bool(body, "syncEnabledRepos", False),
                )
            )
        except BackendHttpError as exc:
            return json_error(exc)

    return CubeLibraryRouteHandlers(
        status=status,
        catalog=catalog,
        cube_versions=cube_versions,
        load_cube=load_cube,
        prewarm_cube=prewarm_cube,
        icon_asset=icon_asset,
        list_packs=list_packs,
        preflight_pack=preflight_pack,
        add_pack=add_pack,
        update_pack=update_pack,
        remove_pack=remove_pack,
        sync_pack=sync_pack,
        sync_all_packs=sync_all_packs,
        readiness=readiness,
        dependency_readiness=dependency_readiness,
        repair_dependencies=repair_dependencies,
    )


async def _json_object_body(request: web.Request) -> dict[str, object]:
    """Parse a JSON object request body."""

    body = await request.json()
    if not isinstance(body, dict):
        raise BackendHttpError(
            message="Request body must be a JSON object.",
            status=400,
            code="invalid-request-body",
        )
    return body


def _required_query(request: web.Request, key: str) -> str:
    """Read one required string query parameter."""

    value = request.query.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise BackendHttpError(
        message=f"'{key}' query parameter is required.",
        status=400,
        code="invalid-query",
    )


def _optional_query(request: web.Request, key: str) -> str | None:
    """Read one optional query parameter."""

    value = request.query.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _required_str(data: dict[str, object], key: str) -> str:
    """Read one required string field."""

    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise BackendHttpError(
        message=f"'{key}' is required.",
        status=400,
        code="invalid-request-body",
    )


def _optional_str(data: dict[str, object], key: str) -> str | None:
    """Read one optional string field."""

    value = data.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_bool(data: dict[str, object], key: str, default: bool) -> bool:
    """Read one optional boolean field with a default."""

    value = data.get(key)
    return value if isinstance(value, bool) else default


def _nullable_bool(data: dict[str, object], key: str) -> bool | None:
    """Read one optional boolean field where absence means no update."""

    value = data.get(key)
    return value if isinstance(value, bool) else None


def _parse_bool(value: str | None, default: bool) -> bool:
    """Parse a boolean query value."""

    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise BackendHttpError(
        message=f"Invalid boolean query value: {value}",
        status=400,
        code="invalid-query-value",
    )


def _trace_id(request: web.Request) -> str:
    """Read the cube-library trace id from a request header."""

    headers = getattr(request, "headers", {})
    if not isinstance(headers, Mapping):
        return ""
    value = headers.get(CUBE_LIBRARY_TRACE_HEADER, "")
    return value.strip() if isinstance(value, str) else ""


def _route_diagnostic_context(request: web.Request) -> DiagnosticContext | None:
    """Build the Cube Library diagnostic context for one HTTP request."""

    trace_id = _trace_id(request)
    if not trace_id:
        return None
    return DiagnosticContext(feature=CUBE_LIBRARY_DIAGNOSTICS, trace_id=trace_id)


def _log_route_diagnostic(
    diagnostics: DiagnosticLogger,
    context: DiagnosticContext | None,
    event: str,
    **fields: object,
) -> None:
    """Emit one request-bound Cube Library route diagnostic."""

    if context is None:
        return
    diagnostics.debug(context, event, fields)

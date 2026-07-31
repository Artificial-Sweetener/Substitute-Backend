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
"""Authorize local execution assets through a loopback-only HTTP route."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Protocol, cast

from aiohttp import web

from substitute_backend.features.local_assets.application import (
    LocalAssetAuthorizationError,
    LocalAssetAuthorizationService,
)
from substitute_backend.features.local_assets.domain import local_execution_node_class

LOCAL_ASSET_AUTHORIZE_ROUTE = "/substitute/v1/local-assets/authorize"


class _RequestLike(Protocol):
    """Describe request behavior used by the local asset route."""

    remote: str | None

    async def json(self) -> object:
        """Return the decoded JSON request body."""


@dataclass(frozen=True)
class LocalAssetRouteHandlers:
    """Handle loopback authorization of local execution assets."""

    service: LocalAssetAuthorizationService

    async def authorize(self, request: web.Request) -> web.Response:
        """Return an opaque token for one exact local source file."""

        request_like = cast(_RequestLike, request)
        if not _is_loopback(request_like.remote):
            return _error(
                status=403,
                code="local-asset-loopback-required",
                message="Local asset authorization requires a loopback connection.",
            )
        try:
            payload = await request_like.json()
        except (UnicodeDecodeError, ValueError):
            return _error(
                status=400,
                code="invalid-local-asset-request",
                message="Local asset authorization body must be valid JSON.",
            )
        if not isinstance(payload, dict):
            return _error(
                status=400,
                code="invalid-local-asset-request",
                message="Local asset authorization body must be an object.",
            )
        source_path = payload.get("sourcePath")
        source_node_class = payload.get("nodeClass")
        content_hash = payload.get("contentHash")
        if (
            not isinstance(source_path, str)
            or not isinstance(source_node_class, str)
            or not isinstance(content_hash, str)
        ):
            return _error(
                status=400,
                code="invalid-local-asset-request",
                message="Local asset authorization fields must be strings.",
            )
        try:
            asset = self.service.authorize(
                source_path=source_path,
                source_node_class=source_node_class,
                content_hash=content_hash,
            )
        except LocalAssetAuthorizationError as error:
            return _error(
                status=422,
                code="local-asset-rejected",
                message=str(error),
            )
        return web.json_response(
            {
                "token": asset.token,
                "nodeClass": asset.source_node_class,
                "executionNodeClass": local_execution_node_class(asset.source_node_class),
                "contentHash": asset.content_hash,
            }
        )


def build_local_asset_route_handlers(
    service: LocalAssetAuthorizationService,
) -> LocalAssetRouteHandlers:
    """Build handlers for one authorization service."""

    return LocalAssetRouteHandlers(service=service)


def _is_loopback(remote: str | None) -> bool:
    """Return whether an aiohttp remote address is local to this machine."""

    if not remote:
        return False
    try:
        address = ipaddress.ip_address(remote)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or bool(mapped is not None and mapped.is_loopback)


def _error(*, status: int, code: str, message: str) -> web.Response:
    """Return one stable JSON error response."""

    return web.json_response(
        {"error": {"code": code, "message": message}},
        status=status,
    )


__all__ = [
    "LOCAL_ASSET_AUTHORIZE_ROUTE",
    "LocalAssetRouteHandlers",
    "build_local_asset_route_handlers",
]

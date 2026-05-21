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
"""HTTP route handlers for backend-managed preview assets."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiohttp import web

from substitute_backend.api.errors import BackendHttpError, json_error
from substitute_backend.features.preview_assets.application import PreviewAssetServices
from substitute_backend.features.preview_assets.domain import PreviewAssetError

RouteHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@dataclass(frozen=True)
class PreviewAssetRouteHandlers:
    """Concrete preview asset route callables used by host registration."""

    taesd_status: RouteHandler
    ensure_taesd: RouteHandler


def build_preview_asset_route_handlers(
    services: PreviewAssetServices,
    logger: logging.Logger,
) -> PreviewAssetRouteHandlers:
    """Build thin HTTP handlers over preview asset services."""

    async def taesd_status(request: web.Request) -> web.Response:
        """Return TAESD decoder readiness without network access."""

        _ = request
        try:
            return web.json_response(services.taesd.status().to_payload())
        except PreviewAssetError as exc:
            return json_error(
                BackendHttpError(
                    message=exc.message,
                    status=exc.status,
                    code=exc.code,
                )
            )
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "TAESD preview asset status route failed",
                extra={
                    "operation": "taesd-preview-assets-status",
                    "route": "/substitute/v1/preview-assets/taesd/status",
                },
            )
            return json_error(
                BackendHttpError(
                    message="TAESD preview asset status unavailable.",
                    status=500,
                    code="taesd-preview-assets-status-unavailable",
                )
            )

    async def ensure_taesd(request: web.Request) -> web.Response:
        """Download missing TAESD decoder assets and return readiness."""

        _ = request
        try:
            return web.json_response(services.taesd.ensure().to_payload())
        except PreviewAssetError as exc:
            return json_error(
                BackendHttpError(
                    message=exc.message,
                    status=exc.status,
                    code=exc.code,
                )
            )
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "TAESD preview asset ensure route failed",
                extra={
                    "operation": "taesd-preview-assets-ensure",
                    "route": "/substitute/v1/preview-assets/taesd/ensure",
                },
            )
            return json_error(
                BackendHttpError(
                    message="TAESD preview assets could not be prepared.",
                    status=500,
                    code="taesd-preview-assets-ensure-failed",
                )
            )

    return PreviewAssetRouteHandlers(
        taesd_status=taesd_status,
        ensure_taesd=ensure_taesd,
    )

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
"""HTTP route handlers for backend-owned Sugar compilation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from aiohttp import web

from substitute_backend.api.errors import BackendHttpError, json_error
from substitute_backend.api.serialization import JsonObject
from substitute_backend.features.sugar_compile.application import SugarCompileServices
from substitute_backend.features.sugar_compile.domain import (
    SugarCompileError,
    SugarCompileRequest,
)

RouteHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@dataclass(frozen=True)
class SugarCompileRouteHandlers:
    """Concrete Sugar compile route callables used by host registration."""

    compile_sugar: RouteHandler


def build_sugar_compile_route_handlers(
    services: SugarCompileServices,
    logger: logging.Logger,
) -> SugarCompileRouteHandlers:
    """Build thin HTTP handlers over Sugar compile application services."""

    async def compile_sugar(request: web.Request) -> web.Response:
        """Compile one Sugar script into prompt and workflow artifacts."""

        try:
            body = await _json_object_body(request)
            result = services.compile.compile(SugarCompileRequest.from_payload(body))
            return web.json_response(result.to_payload())
        except BackendHttpError as exc:
            return json_error(exc)
        except SugarCompileError as exc:
            return json_error(
                BackendHttpError(
                    message=exc.message,
                    status=exc.status,
                    code=exc.code,
                )
            )
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "Sugar compile route failed.",
                extra={
                    "operation": "sugar-compile",
                    "route": "/substitute/v1/sugar/compile",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Sugar workflow could not be compiled.",
                    status=500,
                    code="sugar-compile-failed",
                )
            )

    return SugarCompileRouteHandlers(compile_sugar=compile_sugar)


async def _json_object_body(request: web.Request) -> JsonObject:
    """Parse and validate a JSON object request body."""

    try:
        body = await request.json()
    except (TypeError, ValueError) as exc:
        raise BackendHttpError(
            message="Request body must be a JSON object.",
            status=400,
            code="sugar-compile-invalid-request",
        ) from exc
    if not isinstance(body, dict):
        raise BackendHttpError(
            message="Request body must be a JSON object.",
            status=400,
            code="sugar-compile-invalid-request",
        )
    return cast(
        JsonObject,
        {str(key): value for key, value in body.items() if isinstance(key, str)},
    )

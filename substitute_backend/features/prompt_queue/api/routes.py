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
"""HTTP route handlers for backend-owned prompt queueing."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiohttp import web

from substitute_backend.api.errors import BackendHttpError, json_error
from substitute_backend.features.prompt_queue.application.services import PromptQueueServices

RouteHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@dataclass(frozen=True)
class PromptQueueRouteHandlers:
    """Concrete prompt queue route callables used by host registration."""

    queue_prompt: RouteHandler


def build_prompt_queue_route_handlers(
    services: PromptQueueServices,
    logger: logging.Logger,
) -> PromptQueueRouteHandlers:
    """Build thin HTTP handlers over prompt queue services."""

    async def queue_prompt(request: web.Request) -> web.Response:
        """Queue one prompt through Substitute BackEnd's Comfy facade."""

        try:
            body = await _json_object_body(request)
            result = await services.queue.queue_prompt(body)
            return web.json_response(result.payload, status=result.status)
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "Prompt queue route failed.",
                extra={
                    "operation": "prompt-queue",
                    "route": "/substitute/v1/prompt/queue",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Prompt could not be queued.",
                    status=500,
                    code="prompt-queue-failed",
                )
            )

    return PromptQueueRouteHandlers(queue_prompt=queue_prompt)


async def _json_object_body(request: web.Request) -> dict[str, object]:
    """Parse a JSON object request body."""

    body = await request.json()
    if not isinstance(body, dict):
        raise BackendHttpError(
            message="Request body must be a JSON object.",
            status=400,
            code="invalid-request-body",
        )
    return dict(body)

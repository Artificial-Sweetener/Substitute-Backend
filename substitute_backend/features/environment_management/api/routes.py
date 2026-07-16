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
"""HTTP route handlers for Substitute BackEnd environment management APIs."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiohttp import web

from substitute_backend.api.errors import BackendHttpError, json_error
from substitute_backend.features.environment_management.application.services import (
    EnvironmentManagementServices,
)
from substitute_backend.features.environment_management.domain.model_root import ModelRootMode

RouteHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@dataclass(frozen=True)
class EnvironmentRouteHandlers:
    """Concrete environment route callables used for registration and tests."""

    capabilities: RouteHandler
    status: RouteHandler
    get_model_root: RouteHandler
    update_model_root: RouteHandler
    list_packages: RouteHandler
    list_components: RouteHandler
    plan_operation: RouteHandler
    get_maintenance_plan: RouteHandler
    add_maintenance_plan_item: RouteHandler
    remove_maintenance_plan_item: RouteHandler
    reorder_maintenance_plan_items: RouteHandler
    clear_maintenance_plan: RouteHandler
    validate_maintenance_plan: RouteHandler
    apply_maintenance_plan: RouteHandler
    restart: RouteHandler
    get_job: RouteHandler


def build_environment_route_handlers(
    services: EnvironmentManagementServices,
    logger: logging.Logger,
) -> EnvironmentRouteHandlers:
    """Build thin HTTP handlers over environment management services."""

    async def capabilities(request: web.Request) -> web.Response:
        """Return environment management capabilities."""

        _ = request
        return web.json_response(services.environment.get_capabilities().to_payload())

    async def status(request: web.Request) -> web.Response:
        """Return current Comfy Python environment status."""

        _ = request
        try:
            return web.json_response(services.environment.get_status().to_payload())
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "environment status route failed",
                extra={
                    "operation": "environment-status",
                    "route": "/substitute/v1/environment/status",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Environment status unavailable.",
                    status=500,
                    code="environment-status-unavailable",
                )
            )

    async def get_model_root(request: web.Request) -> web.Response:
        """Return persisted and active Comfy model-root state."""

        _ = request
        try:
            return web.json_response(services.model_root.get_status().to_payload())
        except (OSError, ValueError) as exc:
            logger.warning(
                "model-root status unavailable",
                extra={"operation": "model-root-status", "error": repr(exc)},
            )
            return json_error(
                BackendHttpError(
                    message="Model-root configuration could not be read.",
                    status=500,
                    code="model-root-status-unavailable",
                )
            )

    async def update_model_root(request: web.Request) -> web.Response:
        """Persist the model root that ComfyUI will use after restart."""

        try:
            body = await _json_object_body(request)
            mode, raw_path = _parse_model_root_update(body)
            status = services.model_root.configure(mode, raw_path)
            return web.json_response(status.to_payload())
        except BackendHttpError as exc:
            return json_error(exc)
        except (OSError, ValueError) as exc:
            return json_error(
                BackendHttpError(
                    message=str(exc),
                    status=400,
                    code="invalid-model-root",
                )
            )

    async def restart(request: web.Request) -> web.Response:
        """Queue a Comfy restart operation."""

        _ = request
        try:
            job = services.restart.restart()
            return web.json_response(job.to_payload(), status=202)
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "environment restart route failed",
                extra={
                    "operation": "restart-comfy",
                    "route": "/substitute/v1/environment/restart",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Comfy restart failed.",
                    status=500,
                    code="restart-failed",
                )
            )

    async def list_packages(request: web.Request) -> web.Response:
        """Return installed Python packages with attribution."""

        _ = request
        inventory = services.inventory.list_packages()
        return web.json_response(
            {
                "schemaVersion": 1,
                "packages": [package.to_payload() for package in inventory.packages],
            }
        )

    async def list_components(request: web.Request) -> web.Response:
        """Return UI-friendly installed environment components."""

        _ = request
        inventory = services.inventory.list_components()
        return web.json_response(
            {
                "schemaVersion": 1,
                "components": [component.to_payload() for component in inventory.components],
            }
        )

    async def get_job(request: web.Request) -> web.Response:
        """Return the current state for an environment job."""

        job_id = request.match_info.get("jobId", "")
        job = services.jobs.get(job_id)
        if job is None:
            return json_error(
                BackendHttpError(
                    message="Environment job not found.",
                    status=404,
                    code="environment-job-not-found",
                )
            )
        return web.json_response(job.to_payload())

    async def plan_operation(request: web.Request) -> web.Response:
        """Return a reviewable environment operation plan."""

        try:
            body = await _json_object_body(request)
            plan = services.operation_planning.plan(body)
            return web.json_response(plan.to_payload())
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "environment operation planning route failed",
                extra={
                    "operation": "environment-operation-plan",
                    "route": "/substitute/v1/environment/operations/plan",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Environment operation planning failed.",
                    status=500,
                    code="operation-planning-failed",
                )
            )

    async def get_maintenance_plan(request: web.Request) -> web.Response:
        """Return the current backend-owned maintenance plan."""

        _ = request
        return web.json_response(services.maintenance_plan.get().to_payload())

    async def add_maintenance_plan_item(request: web.Request) -> web.Response:
        """Add a requested item to the maintenance plan."""

        try:
            body = await _json_object_body(request)
            plan = services.maintenance_plan.add_item(body)
            return web.json_response(plan.to_payload(), status=201)
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "environment maintenance plan add route failed",
                extra={
                    "operation": "environment-maintenance-plan-add",
                    "route": "/substitute/v1/environment/maintenance-plan/items",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Maintenance plan item could not be added.",
                    status=500,
                    code="maintenance-plan-add-failed",
                )
            )

    async def remove_maintenance_plan_item(request: web.Request) -> web.Response:
        """Remove one item from the maintenance plan."""

        item_id = request.match_info.get("itemId", "")
        try:
            plan = services.maintenance_plan.remove_item(item_id)
            return web.json_response(plan.to_payload())
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "environment maintenance plan remove route failed",
                extra={
                    "operation": "environment-maintenance-plan-remove",
                    "route": "/substitute/v1/environment/maintenance-plan/items/{itemId}",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Maintenance plan item could not be removed.",
                    status=500,
                    code="maintenance-plan-remove-failed",
                )
            )

    async def reorder_maintenance_plan_items(request: web.Request) -> web.Response:
        """Apply a user-proposed maintenance plan order."""

        try:
            body = await _json_object_body(request)
            revision = _required_int(body, "revision")
            item_ids = _required_str_tuple(body, "itemIds")
            plan = services.maintenance_plan.reorder_items(
                revision=revision,
                item_ids=item_ids,
            )
            return web.json_response(plan.to_payload())
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "environment maintenance plan reorder route failed",
                extra={
                    "operation": "environment-maintenance-plan-reorder",
                    "route": "/substitute/v1/environment/maintenance-plan/items/reorder",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Maintenance plan items could not be reordered.",
                    status=500,
                    code="maintenance-plan-reorder-failed",
                )
            )

    async def clear_maintenance_plan(request: web.Request) -> web.Response:
        """Clear the maintenance plan."""

        _ = request
        return web.json_response(services.maintenance_plan.clear().to_payload())

    async def validate_maintenance_plan(request: web.Request) -> web.Response:
        """Validate and normalize the maintenance plan."""

        _ = request
        return web.json_response(services.maintenance_plan.validate().to_payload())

    async def apply_maintenance_plan(request: web.Request) -> web.Response:
        """Apply the current maintenance plan when it is executable."""

        try:
            body = await _json_object_body(request)
            job = services.maintenance_plan.apply(
                revision=_required_int(body, "revision"),
            )
            return web.json_response(job.to_payload(), status=202)
        except BackendHttpError as exc:
            return json_error(exc)
        except Exception:  # pragma: no cover - defensive host boundary.
            logger.exception(
                "environment maintenance plan apply route failed",
                extra={
                    "operation": "environment-maintenance-plan-apply",
                    "route": "/substitute/v1/environment/maintenance-plan/apply",
                },
            )
            return json_error(
                BackendHttpError(
                    message="Maintenance plan could not be applied.",
                    status=500,
                    code="maintenance-plan-apply-failed",
                )
            )

    return EnvironmentRouteHandlers(
        capabilities=capabilities,
        status=status,
        get_model_root=get_model_root,
        update_model_root=update_model_root,
        list_packages=list_packages,
        list_components=list_components,
        plan_operation=plan_operation,
        get_maintenance_plan=get_maintenance_plan,
        add_maintenance_plan_item=add_maintenance_plan_item,
        remove_maintenance_plan_item=remove_maintenance_plan_item,
        reorder_maintenance_plan_items=reorder_maintenance_plan_items,
        clear_maintenance_plan=clear_maintenance_plan,
        validate_maintenance_plan=validate_maintenance_plan,
        apply_maintenance_plan=apply_maintenance_plan,
        restart=restart,
        get_job=get_job,
    )


async def _json_object_body(request: web.Request) -> dict[str, object]:
    """Parse a JSON object request body."""

    body = await request.json()
    if not isinstance(body, dict):
        raise BackendHttpError(
            message="Request body must be a JSON object.",
            status=400,
            code="invalid-operation-plan-request",
        )
    return body


def _parse_model_root_update(
    body: dict[str, object],
) -> tuple[ModelRootMode, str | None]:
    """Parse one model-root update without leaking untyped request data."""

    raw_mode = body.get("mode")
    if not isinstance(raw_mode, str):
        raise BackendHttpError(
            message="Model-root mode is required.",
            status=400,
            code="invalid-model-root",
        )
    try:
        mode = ModelRootMode(raw_mode)
    except ValueError as exc:
        raise BackendHttpError(
            message="Model-root mode must be 'default' or 'custom'.",
            status=400,
            code="invalid-model-root",
        ) from exc
    raw_path = body.get("path")
    if raw_path is not None and not isinstance(raw_path, str):
        raise BackendHttpError(
            message="Model-root path must be a string.",
            status=400,
            code="invalid-model-root",
        )
    return mode, raw_path


def _required_int(data: dict[str, object], key: str) -> int:
    """Read one required integer request field."""

    value = data.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise BackendHttpError(
        message=f"'{key}' is required.",
        status=400,
        code="invalid-maintenance-plan-request",
    )


def _required_str_tuple(data: dict[str, object], key: str) -> tuple[str, ...]:
    """Read one required list of string request field."""

    value = data.get(key)
    if isinstance(value, list):
        items = tuple(item for item in value if isinstance(item, str) and item.strip())
        if len(items) == len(value):
            return items
    raise BackendHttpError(
        message=f"'{key}' must be a list of strings.",
        status=400,
        code="invalid-maintenance-plan-request",
    )

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
"""PromptServer route registration for Substitute BackEnd."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar, runtime_checkable

from aiohttp import web

from substitute_backend.api.serialization import JsonValue
from substitute_backend.features.cube_library.api.routes import (
    CubeLibraryRouteHandlers,
    build_cube_library_route_handlers,
)
from substitute_backend.features.cube_library.application.services import (
    CubeLibraryServices,
)
from substitute_backend.features.cube_library.domain import CubeLibraryCapabilities
from substitute_backend.features.cube_outputs.application import CubeOutputServices
from substitute_backend.features.downloads.application import DownloadServices
from substitute_backend.features.environment_management.api.routes import (
    EnvironmentRouteHandlers,
    build_environment_route_handlers,
)
from substitute_backend.features.environment_management.application.services import (
    EnvironmentManagementServices,
)
from substitute_backend.features.model_loading.application.services import (
    ModelLoadingServices,
)
from substitute_backend.features.model_metadata.api.routes import (
    ModelMetadataRouteHandlers,
    build_model_metadata_route_handlers,
)
from substitute_backend.features.model_metadata.application.services import (
    ModelMetadataServices,
)
from substitute_backend.features.preview_assets.api.routes import (
    PreviewAssetRouteHandlers,
    build_preview_asset_route_handlers,
)
from substitute_backend.features.preview_assets.application.services import (
    PreviewAssetServices,
)
from substitute_backend.features.prompt_queue.api.routes import (
    PromptQueueRouteHandlers,
    build_prompt_queue_route_handlers,
)
from substitute_backend.features.prompt_queue.application.services import PromptQueueServices
from substitute_backend.features.sugar_compile.api.routes import (
    SugarCompileRouteHandlers,
    build_sugar_compile_route_handlers,
)
from substitute_backend.features.sugar_compile.application import SugarCompileServices
from substitute_backend.features.sugar_compile.domain import SUGAR_COMPILE_ROUTE
from substitute_backend.infrastructure.diagnostics import DiagnosticLogger
from substitute_backend.infrastructure.logging import get_logger

_RouteHandler = TypeVar("_RouteHandler", bound=Callable[..., object])


class RouteRegistrar(Protocol):
    """Subset of aiohttp route registration used by ComfyUI PromptServer."""

    def get(self, path: str) -> Callable[[_RouteHandler], _RouteHandler]:
        """Return a decorator registering a GET handler."""

    def post(self, path: str) -> Callable[[_RouteHandler], _RouteHandler]:
        """Return a decorator registering a POST handler."""

    def delete(self, path: str) -> Callable[[_RouteHandler], _RouteHandler]:
        """Return a decorator registering a DELETE handler."""


@runtime_checkable
class PromptServerLike(Protocol):
    """Subset of PromptServer needed for route registration."""

    routes: RouteRegistrar


class PromptServerClassLike(Protocol):
    """Subset of PromptServer class shape exposed by ComfyUI."""

    instance: PromptServerLike


class BackendServicesLike(Protocol):
    """Feature services consumed by host route registration."""

    @property
    def model_metadata(self) -> ModelMetadataServices:
        """Return model metadata services."""

    @property
    def cube_library(self) -> CubeLibraryServices:
        """Return Cube Library services."""

    @property
    def environment(self) -> EnvironmentManagementServices:
        """Return environment management services."""

    @property
    def model_loading(self) -> ModelLoadingServices:
        """Return model-loading telemetry services."""

    @property
    def downloads(self) -> DownloadServices:
        """Return download telemetry services."""

    @property
    def preview_assets(self) -> PreviewAssetServices:
        """Return preview asset preparation services."""

    @property
    def cube_outputs(self) -> CubeOutputServices:
        """Return cube-output publishing services."""

    @property
    def prompt_queue(self) -> PromptQueueServices:
        """Return prompt queue facade services."""

    @property
    def sugar_compile(self) -> SugarCompileServices:
        """Return Sugar compile services."""

    @property
    def diagnostics(self) -> DiagnosticLogger:
        """Return opt-in diagnostic logging services."""


@dataclass(frozen=True)
class BackendRouteHandlers:
    """Own all registered Substitute BackEnd route handlers."""

    model_metadata: ModelMetadataRouteHandlers
    cube_library: CubeLibraryRouteHandlers
    environment: EnvironmentRouteHandlers
    preview_assets: PreviewAssetRouteHandlers
    prompt_queue: PromptQueueRouteHandlers
    sugar_compile: SugarCompileRouteHandlers


def register_routes(
    prompt_server: PromptServerLike | PromptServerClassLike,
    services: BackendServicesLike,
) -> BackendRouteHandlers:
    """Register Substitute BackEnd routes on a PromptServer instance."""

    model_handlers = build_model_metadata_route_handlers(
        services.model_metadata,
        logger=get_logger("routes"),
    )
    environment_handlers = build_environment_route_handlers(
        services.environment,
        logger=get_logger("environment.routes"),
    )
    cube_library_handlers = build_cube_library_route_handlers(
        services.cube_library,
        logger=get_logger("cube_library.routes"),
        diagnostics=services.diagnostics,
    )
    preview_asset_handlers = build_preview_asset_route_handlers(
        services.preview_assets,
        logger=get_logger("preview_assets.routes"),
    )
    prompt_queue_handlers = build_prompt_queue_route_handlers(
        services.prompt_queue,
        logger=get_logger("prompt_queue.routes"),
    )
    sugar_compile_handlers = build_sugar_compile_route_handlers(
        services.sugar_compile,
        logger=get_logger("sugar_compile.routes"),
    )
    routes = _resolve_routes(prompt_server)
    routes.get("/substitute/v1/capabilities")(_build_capabilities_handler(services))
    routes.post("/substitute/v1/prompt/queue")(prompt_queue_handlers.queue_prompt)
    routes.post(SUGAR_COMPILE_ROUTE)(sugar_compile_handlers.compile_sugar)
    routes.get("/substitute/v1/models")(model_handlers.list_models)
    routes.get("/substitute/v1/models/changes")(model_handlers.latest_model_changes)
    routes.get("/substitute/v1/models/by-hash/{sha256}")(model_handlers.lookup_model_by_hash)
    routes.post("/substitute/v1/models/downloads/civitai")(
        model_handlers.start_civitai_model_download
    )
    routes.get("/substitute/v1/models/downloads/jobs/{jobId}")(
        model_handlers.get_model_download_job
    )
    routes.post("/substitute/v1/models/downloads/jobs/{jobId}/cancel")(
        model_handlers.cancel_model_download_job
    )
    routes.post("/substitute/v1/models/fingerprints/refresh")(model_handlers.refresh_fingerprints)
    routes.get("/substitute/v1/models/fingerprints/jobs/{jobId}")(
        model_handlers.get_fingerprint_job
    )
    routes.get("/substitute/v1/previews/{previewId}")(model_handlers.get_preview)
    routes.get("/substitute/v1/cube-library/status")(cube_library_handlers.status)
    routes.get("/substitute/v1/cube-library/catalog")(cube_library_handlers.catalog)
    routes.get("/substitute/v1/cube-library/cubes/versions")(cube_library_handlers.cube_versions)
    routes.get("/substitute/v1/cube-library/cubes/load")(cube_library_handlers.load_cube)
    routes.post("/substitute/v1/cube-library/cubes/prewarm")(cube_library_handlers.prewarm_cube)
    routes.get("/substitute/v1/cube-library/cubes/icon")(cube_library_handlers.icon_asset)
    routes.get("/substitute/v1/cube-library/packs")(cube_library_handlers.list_packs)
    routes.post("/substitute/v1/cube-library/packs/preflight")(cube_library_handlers.preflight_pack)
    routes.post("/substitute/v1/cube-library/packs")(cube_library_handlers.add_pack)
    routes.post("/substitute/v1/cube-library/packs/update")(cube_library_handlers.update_pack)
    routes.delete("/substitute/v1/cube-library/packs")(cube_library_handlers.remove_pack)
    routes.post("/substitute/v1/cube-library/packs/sync")(cube_library_handlers.sync_pack)
    routes.post("/substitute/v1/cube-library/packs/sync-all")(cube_library_handlers.sync_all_packs)
    routes.get("/substitute/v1/cube-library/readiness")(cube_library_handlers.readiness)
    routes.get("/substitute/v1/cube-library/dependencies/readiness")(
        cube_library_handlers.dependency_readiness
    )
    routes.post("/substitute/v1/cube-library/dependencies/repair")(
        cube_library_handlers.repair_dependencies
    )
    routes.get("/substitute/v1/environment/capabilities")(environment_handlers.capabilities)
    routes.get("/substitute/v1/environment/status")(environment_handlers.status)
    routes.get("/substitute/v1/environment/packages")(environment_handlers.list_packages)
    routes.get("/substitute/v1/environment/components")(environment_handlers.list_components)
    routes.post("/substitute/v1/environment/operations/plan")(environment_handlers.plan_operation)
    routes.get("/substitute/v1/environment/maintenance-plan")(
        environment_handlers.get_maintenance_plan
    )
    routes.post("/substitute/v1/environment/maintenance-plan/items")(
        environment_handlers.add_maintenance_plan_item
    )
    routes.delete("/substitute/v1/environment/maintenance-plan/items/{itemId}")(
        environment_handlers.remove_maintenance_plan_item
    )
    routes.post("/substitute/v1/environment/maintenance-plan/items/reorder")(
        environment_handlers.reorder_maintenance_plan_items
    )
    routes.delete("/substitute/v1/environment/maintenance-plan")(
        environment_handlers.clear_maintenance_plan
    )
    routes.post("/substitute/v1/environment/maintenance-plan/validate")(
        environment_handlers.validate_maintenance_plan
    )
    routes.post("/substitute/v1/environment/maintenance-plan/apply")(
        environment_handlers.apply_maintenance_plan
    )
    routes.post("/substitute/v1/environment/restart")(environment_handlers.restart)
    routes.get("/substitute/v1/environment/jobs/{jobId}")(environment_handlers.get_job)
    routes.get("/substitute/v1/preview-assets/taesd/status")(preview_asset_handlers.taesd_status)
    routes.post("/substitute/v1/preview-assets/taesd/ensure")(preview_asset_handlers.ensure_taesd)
    return BackendRouteHandlers(
        model_metadata=model_handlers,
        cube_library=cube_library_handlers,
        environment=environment_handlers,
        preview_assets=preview_asset_handlers,
        prompt_queue=prompt_queue_handlers,
        sugar_compile=sugar_compile_handlers,
    )


def _build_capabilities_handler(
    services: BackendServicesLike,
) -> Callable[[web.Request], object]:
    """Build the top-level capability route across feature handlers."""

    async def capabilities(request: web.Request) -> web.Response:
        """Return backend capabilities with all feature payloads."""

        _ = request
        services.cube_outputs.registration.register()
        payload = services.model_metadata.capabilities.get_capabilities().to_payload()
        features = payload.get("features")
        feature_list = (
            [item for item in features if isinstance(item, str)]
            if isinstance(features, list)
            else []
        )
        if "environment-management" not in feature_list:
            feature_list.append("environment-management")
        if "preview-assets" not in feature_list:
            feature_list.append("preview-assets")
        if "cube-library" not in feature_list:
            feature_list.append("cube-library")
        if "download-telemetry" not in feature_list:
            feature_list.append("download-telemetry")
        if "prompt-queue-facade" not in feature_list:
            feature_list.append("prompt-queue-facade")
        sugar_compile_capabilities = services.sugar_compile.compile.capabilities()
        if sugar_compile_capabilities.available and "sugar-compile" not in feature_list:
            feature_list.append("sugar-compile")
        feature_payload: list[JsonValue] = list(feature_list)
        payload["features"] = feature_payload
        payload["cubeLibrary"] = CubeLibraryCapabilities().to_payload()
        payload["environmentManagement"] = (
            services.environment.environment.get_capabilities().to_payload()
        )
        payload["modelLoadingTelemetry"] = {
            "supported": True,
            "eventType": "substitute_model_load_progress",
            "sourceMetadata": "best-effort-prompt-graph",
            "percentMode": "best-effort-runtime-patch",
            "fallback": "progress_state",
        }
        payload["downloadTelemetry"] = {
            "supported": True,
            "eventType": "substitute_download_progress",
            "providers": ["huggingface"],
            "percentMode": "huggingface-byte-progress",
            "scope": "best-effort-runtime-patch",
        }
        payload["previewAssets"] = {
            "schemaVersion": 1,
            "taesdPreparationSupported": True,
        }
        payload["promptQueue"] = {
            "schemaVersion": 1,
            "queueRoute": "/substitute/v1/prompt/queue",
            "optimizationSupported": True,
            "optimizationReportSupported": True,
            "debugDumpSupported": False,
        }
        payload["sugarCompile"] = sugar_compile_capabilities.to_payload()
        return web.json_response(payload)

    return capabilities


def _resolve_routes(
    prompt_server: PromptServerLike | PromptServerClassLike,
) -> RouteRegistrar:
    """Return the route registrar from a PromptServer object or class."""

    if isinstance(prompt_server, PromptServerLike):
        return prompt_server.routes
    return prompt_server.instance.routes

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
"""Extension service construction and ComfyUI registration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from substitute_backend.features.cube_library.application import (
    CubeLibraryChangeMonitor,
    CubeLibraryService,
    CubeLibraryServices,
)
from substitute_backend.features.cube_library.infrastructure import (
    PromptServerCubeLibraryPublisher,
    SugarCubesLibraryAdapter,
)
from substitute_backend.features.cube_outputs.application import CubeOutputServices
from substitute_backend.features.cube_outputs.infrastructure import (
    PromptServerCubeOutputPublisher,
    SubstituteCubeOutputObserver,
    SugarCubesCubeOutputRegistration,
    SugarCubesObserverHookResolver,
)
from substitute_backend.features.downloads.application import DownloadServices
from substitute_backend.features.downloads.application.telemetry_service import (
    DownloadTelemetryService,
)
from substitute_backend.features.downloads.infrastructure import (
    HuggingFaceDownloadPatchInstaller,
    PromptServerDownloadPublisher,
)
from substitute_backend.features.environment_management.application import (
    MaintenancePlanService,
    OperationPlanningService,
)
from substitute_backend.features.environment_management.application.environment_service import (
    EnvironmentService,
)
from substitute_backend.features.environment_management.application.inventory_service import (
    InventoryService,
)
from substitute_backend.features.environment_management.application.job_service import (
    JobService,
)
from substitute_backend.features.environment_management.application.restart_service import (
    RestartService,
)
from substitute_backend.features.environment_management.application.services import (
    EnvironmentManagementServices,
)
from substitute_backend.features.environment_management.infrastructure import (
    ComfyRequirementsScanner,
    CustomNodeRequirementsScanner,
    MaintenancePlanStore,
    PipInspector,
)
from substitute_backend.features.environment_management.infrastructure.job_store import JobStore
from substitute_backend.features.environment_management.infrastructure.python_environment import (
    PythonEnvironmentInspector,
)
from substitute_backend.features.environment_management.infrastructure.restart_coordinator import (
    RestartCoordinator,
)
from substitute_backend.features.model_loading.application.services import (
    ModelLoadingServices,
)
from substitute_backend.features.model_loading.application.telemetry_service import (
    ModelLoadingTelemetryService,
)
from substitute_backend.features.model_loading.infrastructure.comfy_context import (
    ComfyExecutionContextReader,
)
from substitute_backend.features.model_loading.infrastructure.comfy_log_parser import (
    ComfyModelLoadLogObserver,
    ComfyModelLoadLogParser,
)
from substitute_backend.features.model_loading.infrastructure.comfy_model_patch import (
    ComfyModelLoadPatchInstaller,
)
from substitute_backend.features.model_loading.infrastructure.prompt_server_publisher import (
    PromptServerModelLoadPublisher,
)
from substitute_backend.features.model_metadata.application.capability_service import (
    CapabilityService,
)
from substitute_backend.features.model_metadata.application.catalog_service import (
    CatalogService,
)
from substitute_backend.features.model_metadata.application.fingerprint_service import (
    FingerprintService,
)
from substitute_backend.features.model_metadata.application.hash_lookup_service import (
    HashLookupService,
)
from substitute_backend.features.model_metadata.application.model_download_service import (
    ModelDownloadService,
)
from substitute_backend.features.model_metadata.application.preview_service import (
    PreviewService,
)
from substitute_backend.features.model_metadata.application.services import (
    ModelMetadataServices,
)
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    ComfyModelRootsProvider,
    ModelRootsProvider,
)
from substitute_backend.features.model_metadata.infrastructure.fingerprint_cache import (
    FingerprintCache,
)
from substitute_backend.features.model_metadata.infrastructure.fingerprint_worker import (
    FingerprintWorker,
)
from substitute_backend.features.model_metadata.infrastructure.preview_store import (
    PreviewStore,
)
from substitute_backend.features.model_metadata.infrastructure.sidecar_reader import (
    SidecarReader,
)
from substitute_backend.features.preview_assets.application import (
    PreviewAssetServices,
    TaesdAssetService,
)
from substitute_backend.features.preview_assets.domain import taesd_asset_manifest
from substitute_backend.features.preview_assets.infrastructure import (
    ComfyVaeApproxPathProvider,
    HttpAssetDownloader,
)
from substitute_backend.host.routes import (
    BackendRouteHandlers,
    PromptServerClassLike,
    PromptServerLike,
    register_routes,
)
from substitute_backend.infrastructure.cache_paths import ensure_cache_root
from substitute_backend.infrastructure.diagnostics import (
    DiagnosticLogger,
    diagnostics_from_environment,
)
from substitute_backend.infrastructure.logging import get_logger


@dataclass(frozen=True)
class BackendServices:
    """Own all Substitute BackEnd feature service containers."""

    model_metadata: ModelMetadataServices
    cube_library: CubeLibraryServices
    cube_library_compile_executor: ThreadPoolExecutor
    cube_library_change_monitor: CubeLibraryChangeMonitor
    environment: EnvironmentManagementServices
    model_loading: ModelLoadingServices
    downloads: DownloadServices
    preview_assets: PreviewAssetServices
    cube_outputs: CubeOutputServices
    diagnostics: DiagnosticLogger


def build_model_metadata_services(
    extension_root: Path,
    model_roots: ModelRootsProvider | None = None,
) -> ModelMetadataServices:
    """Build application services for the model metadata feature."""

    roots = model_roots or ComfyModelRootsProvider()
    cache_root = ensure_cache_root(extension_root)
    fingerprint_cache = FingerprintCache(cache_root / "model_metadata.sqlite3")
    preview_store = PreviewStore(approved_roots=roots.approved_roots())
    worker = FingerprintWorker(cache=fingerprint_cache)
    fingerprints = FingerprintService(
        model_roots=roots,
        fingerprint_cache=fingerprint_cache,
        worker=worker,
    )
    return ModelMetadataServices(
        capabilities=CapabilityService(model_roots=roots),
        catalog=CatalogService(
            model_roots=roots,
            fingerprint_cache=fingerprint_cache,
            sidecar_reader=SidecarReader(),
            preview_store=preview_store,
            logger=get_logger("catalog"),
        ),
        fingerprints=fingerprints,
        hash_lookup=HashLookupService(
            model_roots=roots,
            fingerprint_cache=fingerprint_cache,
            sidecar_reader=SidecarReader(),
            fingerprints=fingerprints,
            logger=get_logger("hash_lookup"),
        ),
        downloads=ModelDownloadService(
            model_roots=roots,
            fingerprint_cache=fingerprint_cache,
        ),
        previews=PreviewService(preview_store=preview_store),
    )


def build_environment_management_services(extension_root: Path) -> EnvironmentManagementServices:
    """Build application services for the environment management feature."""

    cache_root = ensure_cache_root(extension_root)
    restart_coordinator = RestartCoordinator()
    restart_support = restart_coordinator.support()
    comfy_root = extension_root.parents[1]
    inspector = PythonEnvironmentInspector(
        comfy_root=comfy_root,
        restart_supported=restart_support.supported,
    )
    jobs = JobService(JobStore(cache_root / "environment_jobs.json"))
    inventory = InventoryService(
        pip_inspector=PipInspector(),
        requirements_scanner=CustomNodeRequirementsScanner(comfy_root / "custom_nodes"),
        comfy_requirements_scanner=ComfyRequirementsScanner(comfy_root),
        logger=get_logger("environment.inventory"),
    )
    return EnvironmentManagementServices(
        environment=EnvironmentService(
            inspector=inspector,
            restart_coordinator=restart_coordinator,
        ),
        inventory=inventory,
        maintenance_plan=MaintenancePlanService(
            store=MaintenancePlanStore(environment_id=str(comfy_root)),
            inventory=inventory,
            jobs=jobs,
            package_mutation_supported=False,
        ),
        jobs=jobs,
        operation_planning=OperationPlanningService(),
        restart=RestartService(
            jobs=jobs,
            coordinator=restart_coordinator,
            logger=get_logger("environment.restart"),
        ),
    )


def build_cube_library_services(
    extension_root: Path,
    diagnostics: DiagnosticLogger,
) -> CubeLibraryServices:
    """Build application services for the Cube Library feature."""

    return CubeLibraryServices(
        library=CubeLibraryService(
            gateway=SugarCubesLibraryAdapter(
                extension_root=extension_root,
                diagnostics=diagnostics,
            )
        )
    )


def build_cube_library_compile_executor() -> ThreadPoolExecutor:
    """Build the bounded executor used for blocking Cube Library compile work."""

    return ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="substitute-cube-compile",
    )


def build_cube_library_change_monitor(
    cube_library: CubeLibraryServices,
    diagnostics: DiagnosticLogger,
    prompt_server: object | None = None,
) -> CubeLibraryChangeMonitor:
    """Build the Cube Library catalog-revision monitor."""

    publisher = PromptServerCubeLibraryPublisher(
        prompt_server=prompt_server or object(),
        logger=get_logger("cube_library.publisher"),
    )
    monitor = CubeLibraryChangeMonitor(
        get_catalog_revision=lambda: _catalog_revision_from_status(cube_library),
        publisher=publisher,
        logger=get_logger("cube_library.change_monitor"),
        diagnostics=diagnostics,
    )
    _subscribe_cube_library_immediate_changes(cube_library, monitor)
    return monitor


def build_model_loading_services(prompt_server: object | None = None) -> ModelLoadingServices:
    """Build application services for model-loading telemetry."""

    publisher = PromptServerModelLoadPublisher(
        prompt_server=prompt_server or object(),
        logger=get_logger("model_loading.publisher"),
    )
    telemetry = ModelLoadingTelemetryService(publisher=publisher)
    context_reader = ComfyExecutionContextReader()
    log_parser = ComfyModelLoadLogParser()
    return ModelLoadingServices(
        telemetry=telemetry,
        log_parser=log_parser,
        log_observer=ComfyModelLoadLogObserver(
            parser=log_parser,
            telemetry=telemetry,
            context_reader=context_reader,
            logger=get_logger("model_loading.logs"),
        ),
        patch_installer=ComfyModelLoadPatchInstaller(
            telemetry=telemetry,
            context_reader=context_reader,
            logger=get_logger("model_loading.patch"),
        ),
    )


def build_download_services(prompt_server: object | None = None) -> DownloadServices:
    """Build application services for download telemetry."""

    publisher = PromptServerDownloadPublisher(
        prompt_server=prompt_server or object(),
        logger=get_logger("downloads.publisher"),
    )
    telemetry = DownloadTelemetryService(
        publisher=publisher,
        logger=get_logger("downloads.telemetry"),
    )
    return DownloadServices(
        telemetry=telemetry,
        patch_installer=HuggingFaceDownloadPatchInstaller(
            telemetry=telemetry,
            context_reader=ComfyExecutionContextReader(),
            logger=get_logger("downloads.huggingface"),
        ),
    )


def build_cube_output_services(
    extension_root: Path,
    prompt_server: object | None = None,
) -> CubeOutputServices:
    """Build services for SugarCubes cube-output websocket publishing."""

    publisher = PromptServerCubeOutputPublisher(
        prompt_server=prompt_server or object(),
        logger=get_logger("cube_outputs.publisher"),
    )
    observer = SubstituteCubeOutputObserver(
        publisher=publisher,
        logger=get_logger("cube_outputs.observer"),
    )
    hook_resolver = SugarCubesObserverHookResolver(
        extension_root=extension_root,
        logger=get_logger("cube_outputs.sugarcubes"),
    )
    return CubeOutputServices(
        registration=SugarCubesCubeOutputRegistration(
            hook_resolver=hook_resolver,
            observer=observer,
            logger=get_logger("cube_outputs.registration"),
        )
    )


def build_preview_asset_services() -> PreviewAssetServices:
    """Build application services for backend-managed preview assets."""

    manifest = taesd_asset_manifest()
    downloader = HttpAssetDownloader(
        allowed_urls={asset.url for asset in manifest},
        timeout_seconds=30.0,
    )
    return PreviewAssetServices(
        taesd=TaesdAssetService(
            path_provider=ComfyVaeApproxPathProvider(),
            downloader=downloader,
            logger=get_logger("preview_assets.taesd"),
            manifest=manifest,
        )
    )


def build_backend_services(
    extension_root: Path,
    model_roots: ModelRootsProvider | None = None,
    prompt_server: object | None = None,
    preview_assets: PreviewAssetServices | None = None,
) -> BackendServices:
    """Build all application services for Substitute BackEnd."""

    diagnostics = diagnostics_from_environment(get_logger("diagnostics"))
    cube_library = build_cube_library_services(extension_root, diagnostics)
    cube_library_compile_executor = build_cube_library_compile_executor()
    return BackendServices(
        model_metadata=build_model_metadata_services(extension_root, model_roots=model_roots),
        cube_library=cube_library,
        cube_library_compile_executor=cube_library_compile_executor,
        cube_library_change_monitor=build_cube_library_change_monitor(
            cube_library,
            diagnostics,
            prompt_server=prompt_server,
        ),
        environment=build_environment_management_services(extension_root),
        model_loading=build_model_loading_services(prompt_server=prompt_server),
        downloads=build_download_services(prompt_server=prompt_server),
        preview_assets=preview_assets or build_preview_asset_services(),
        cube_outputs=build_cube_output_services(extension_root, prompt_server=prompt_server),
        diagnostics=diagnostics,
    )


def register_extension(
    prompt_server: PromptServerLike | PromptServerClassLike,
    extension_root: Path,
) -> BackendRouteHandlers:
    """Build services and register Substitute BackEnd routes."""

    prompt_server_instance = _resolve_prompt_server_instance(prompt_server)
    services = build_backend_services(extension_root, prompt_server=prompt_server_instance)
    services.model_loading.patch_installer.install()
    services.model_loading.log_observer.install()
    services.downloads.patch_installer.install()
    services.cube_outputs.registration.register()
    _schedule_cube_output_registration_retry(services.cube_outputs.registration)
    services.cube_library_change_monitor.start()
    return register_routes(prompt_server, services)


def _resolve_prompt_server_instance(
    prompt_server: PromptServerLike | PromptServerClassLike,
) -> object:
    """Return a PromptServer instance for websocket publication."""

    instance = getattr(prompt_server, "instance", None)
    if instance is not None:
        return instance
    return prompt_server


def _schedule_cube_output_registration_retry(
    registration: SugarCubesCubeOutputRegistration,
) -> None:
    """Retry cube-output registration after Comfy finishes the current startup task."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.call_soon(registration.register)


def _catalog_revision_from_status(cube_library: CubeLibraryServices) -> str:
    """Read the current Cube Library catalog revision from status payloads."""

    revision = cube_library.library.status().get("catalogRevision")
    return revision if isinstance(revision, str) else ""


def _subscribe_cube_library_immediate_changes(
    cube_library: CubeLibraryServices,
    monitor: CubeLibraryChangeMonitor,
) -> None:
    """Bridge SugarCubes immediate library-change hooks into Substitute events."""

    gateway = getattr(cube_library.library, "gateway", None)
    subscribe = getattr(gateway, "subscribe_library_changes", None)
    if not callable(subscribe):
        return

    def publish_change(event: Mapping[str, object]) -> None:
        """Publish one SugarCubes change event through the existing monitor."""

        revision = event.get("catalogRevision")
        reason = event.get("reason")
        monitor.publish_immediate_change(
            catalog_revision=revision if isinstance(revision, str) else "",
            reason=reason if isinstance(reason, str) and reason else "library-changed",
        )

    subscribe(publish_change)

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
"""Tests for capabilities and host route registration."""

import asyncio
import importlib.util
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar, cast

import pytest
from aiohttp import web

from substitute_backend.api.serialization import JsonObject
from substitute_backend.features.model_metadata.application.capability_service import (
    CapabilityService,
)
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    StaticModelRootsProvider,
)
from substitute_backend.features.preview_assets.application import (
    DownloadResult,
    PreviewAssetServices,
    TaesdAssetService,
)
from substitute_backend.host.extension import build_backend_services
from substitute_backend.host.routes import PromptServerLike, register_routes
from substitute_backend.infrastructure.logging import get_logger

_RouteHandler = TypeVar("_RouteHandler", bound=Callable[..., object])


class FakeRoutes:
    """Collect route registrations without depending on ComfyUI."""

    def __init__(self) -> None:
        """Initialize an empty route registry."""

        self.registered: list[tuple[str, str]] = []
        self.handlers: dict[tuple[str, str], Callable[..., object]] = {}

    def get(self, path: str) -> Callable[[_RouteHandler], _RouteHandler]:
        """Record a GET route registration."""

        return self._record("GET", path)

    def post(self, path: str) -> Callable[[_RouteHandler], _RouteHandler]:
        """Record a POST route registration."""

        return self._record("POST", path)

    def delete(self, path: str) -> Callable[[_RouteHandler], _RouteHandler]:
        """Record a DELETE route registration."""

        return self._record("DELETE", path)

    def _record(self, method: str, path: str) -> Callable[[_RouteHandler], _RouteHandler]:
        """Return a decorator that records a route registration."""

        def decorator(handler: _RouteHandler) -> _RouteHandler:
            self.registered.append((method, path))
            self.handlers[(method, path)] = handler
            return handler

        return decorator


class FakePromptServer:
    """PromptServer test double with route registration support."""

    def __init__(self) -> None:
        """Initialize a fake PromptServer."""

        self.routes = FakeRoutes()


def test_capabilities_payload_is_feature_based(tmp_path: Path) -> None:
    """Capabilities advertise model metadata without making it the whole backend."""

    provider = StaticModelRootsProvider({"loras": (tmp_path,)}, {".safetensors"})
    payload = CapabilityService(model_roots=provider).get_capabilities().to_payload()
    model_metadata = cast("JsonObject", payload["modelMetadata"])

    assert payload["extensionName"] == "Substitute BackEnd"
    assert payload["features"] == ["model-metadata"]
    assert model_metadata["supportedModelKinds"] == ["loras"]
    assert model_metadata["hashLookup"] is True
    assert model_metadata["sidecarWriting"] is False


def test_register_routes_uses_expected_surface(tmp_path: Path) -> None:
    """Route registration exposes the planned Substitute API surface."""

    provider = StaticModelRootsProvider({"loras": (tmp_path,)}, {".safetensors"})
    services = build_backend_services(
        tmp_path,
        model_roots=provider,
        preview_assets=_preview_asset_services(tmp_path),
    )
    prompt_server = FakePromptServer()

    register_routes(cast("PromptServerLike", prompt_server), services)

    assert prompt_server.routes.registered == [
        ("GET", "/substitute/v1/capabilities"),
        ("POST", "/substitute/v1/prompt/queue"),
        ("POST", "/substitute/v1/sugar/compile"),
        ("GET", "/substitute/v1/models"),
        ("GET", "/substitute/v1/models/changes"),
        ("GET", "/substitute/v1/models/by-hash/{sha256}"),
        ("POST", "/substitute/v1/models/downloads/civitai"),
        ("GET", "/substitute/v1/models/downloads/jobs/{jobId}"),
        ("POST", "/substitute/v1/models/downloads/jobs/{jobId}/cancel"),
        ("POST", "/substitute/v1/models/fingerprints/refresh"),
        ("GET", "/substitute/v1/models/fingerprints/jobs/{jobId}"),
        ("GET", "/substitute/v1/previews/{previewId}"),
        ("GET", "/substitute/v1/cube-library/status"),
        ("GET", "/substitute/v1/cube-library/catalog"),
        ("GET", "/substitute/v1/cube-library/cubes/versions"),
        ("GET", "/substitute/v1/cube-library/cubes/load"),
        ("POST", "/substitute/v1/cube-library/cubes/prewarm"),
        ("GET", "/substitute/v1/cube-library/cubes/icon"),
        ("GET", "/substitute/v1/cube-library/packs"),
        ("POST", "/substitute/v1/cube-library/packs/preflight"),
        ("POST", "/substitute/v1/cube-library/packs"),
        ("POST", "/substitute/v1/cube-library/packs/update"),
        ("DELETE", "/substitute/v1/cube-library/packs"),
        ("POST", "/substitute/v1/cube-library/packs/sync"),
        ("POST", "/substitute/v1/cube-library/packs/sync-all"),
        ("GET", "/substitute/v1/cube-library/readiness"),
        ("GET", "/substitute/v1/cube-library/dependencies/readiness"),
        ("POST", "/substitute/v1/cube-library/dependencies/repair"),
        ("POST", "/substitute/v1/cube-library/sync-and-check"),
        ("GET", "/substitute/v1/environment/capabilities"),
        ("GET", "/substitute/v1/environment/status"),
        ("GET", "/substitute/v1/environment/packages"),
        ("GET", "/substitute/v1/environment/components"),
        ("POST", "/substitute/v1/environment/operations/plan"),
        ("GET", "/substitute/v1/environment/maintenance-plan"),
        ("POST", "/substitute/v1/environment/maintenance-plan/items"),
        ("DELETE", "/substitute/v1/environment/maintenance-plan/items/{itemId}"),
        ("POST", "/substitute/v1/environment/maintenance-plan/items/reorder"),
        ("DELETE", "/substitute/v1/environment/maintenance-plan"),
        ("POST", "/substitute/v1/environment/maintenance-plan/validate"),
        ("POST", "/substitute/v1/environment/maintenance-plan/apply"),
        ("POST", "/substitute/v1/environment/restart"),
        ("GET", "/substitute/v1/environment/jobs/{jobId}"),
        ("GET", "/substitute/v1/preview-assets/taesd/status"),
        ("POST", "/substitute/v1/preview-assets/taesd/ensure"),
    ]


def test_capabilities_payload_advertises_preview_assets(tmp_path: Path) -> None:
    """Top-level capabilities should expose preview asset preparation support."""

    async def run_capabilities() -> None:
        provider = StaticModelRootsProvider({"loras": (tmp_path,)}, {".safetensors"})
        services = build_backend_services(
            tmp_path,
            model_roots=provider,
            preview_assets=_preview_asset_services(tmp_path),
        )
        prompt_server = FakePromptServer()

        register_routes(cast("PromptServerLike", prompt_server), services)
        handler = cast(
            "Callable[[web.Request], Awaitable[web.Response]]",
            prompt_server.routes.handlers[("GET", "/substitute/v1/capabilities")],
        )
        response = await handler(cast("web.Request", object()))

        assert isinstance(response, web.Response)
        assert response.text is not None
        payload = json.loads(response.text)
        assert "preview-assets" in payload["features"]
        assert "cube-library" in payload["features"]
        assert "prompt-queue-facade" in payload["features"]
        assert "sugar-compile" in payload["features"]
        assert payload["cubeLibrary"] == {
            "schemaVersion": 1,
            "available": False,
            "unavailableReason": "SugarCubes is not available on this target.",
            "sugarCubesVersion": "",
            "catalogSupported": False,
            "artifactLoadSupported": False,
            "workflowCompileSupported": False,
            "packManagementSupported": False,
            "dependencyReadinessSupported": False,
            "dependencyRepairSupported": False,
            "versionedDependencyReadinessSupported": False,
            "syncDependencyOrchestrationSupported": False,
        }
        assert payload["previewAssets"] == {
            "schemaVersion": 1,
            "taesdPreparationSupported": True,
        }
        assert payload["promptQueue"] == {
            "schemaVersion": 1,
            "queueRoute": "/substitute/v1/prompt/queue",
            "optimizationSupported": True,
            "optimizationReportSupported": True,
            "debugDumpSupported": False,
        }
        assert payload["sugarCompile"] == {
            "schemaVersion": 1,
            "available": True,
            "compileRoute": "/substitute/v1/sugar/compile",
            "liveNodeDefinitions": True,
        }

    asyncio.run(run_capabilities())


def test_extension_entrypoint_bootstraps_package_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extension entrypoint should import when Comfy loads it by file path."""

    extension_root = Path(__file__).resolve().parents[1]
    module_path = extension_root / "__init__.py"
    module_name = "substitute_backend_entrypoint_import_test"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.syspath_prepend(str(extension_root.parent))

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    assert module.__dict__["NODE_CLASS_MAPPINGS"] == {}


class _StaticPathProvider:
    """Resolve the test preview asset root."""

    def __init__(self, root: Path) -> None:
        """Store the root."""

        self._root = root

    def resolve_root(self) -> Path:
        """Return the root without importing ComfyUI globals."""

        return self._root


class _NoopDownloader:
    """Provide a downloader test double for route-registration tests."""

    def download(self, url: str, destination: Path) -> DownloadResult:
        """Return a failed result without touching the network."""

        _ = (url, destination)
        return DownloadResult(succeeded=False, error="noop")


def _preview_asset_services(tmp_path: Path) -> PreviewAssetServices:
    """Build preview asset services without importing ComfyUI ``folder_paths``."""

    return PreviewAssetServices(
        taesd=TaesdAssetService(
            path_provider=_StaticPathProvider(tmp_path / "vae_approx"),
            downloader=_NoopDownloader(),
            logger=get_logger("tests.preview_assets.routes"),
        )
    )

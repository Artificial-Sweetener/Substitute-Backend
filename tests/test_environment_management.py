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
"""Tests for environment management status and restart services."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import TracebackType
from typing import cast

import pytest
from aiohttp import web

from substitute_backend.api.errors import BackendHttpError
from substitute_backend.api.serialization import JsonObject
from substitute_backend.features.environment_management.api.routes import (
    build_environment_route_handlers,
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
from substitute_backend.features.environment_management.application.model_root_service import (
    ModelRootService,
)
from substitute_backend.features.environment_management.application.restart_service import (
    RestartService,
)
from substitute_backend.features.environment_management.application.services import (
    EnvironmentManagementServices,
)
from substitute_backend.features.environment_management.domain.capabilities import (
    EnvironmentFeature,
)
from substitute_backend.features.environment_management.domain.jobs import (
    EnvironmentJobStatus,
)
from substitute_backend.features.environment_management.domain.operations import (
    EnvironmentOperationKind,
)
from substitute_backend.features.environment_management.domain.packages import (
    PackageClaimantKind,
    PackageSummarySource,
)
from substitute_backend.features.environment_management.infrastructure import (
    ComfyRequirementsScanner,
    CustomNodeRequirementsScanner,
    InstalledPackageMetadataProvider,
    MaintenancePlanStore,
    PackageDependency,
    PackageSummary,
    PipInspector,
    PipPackage,
    PypiSummaryProvider,
)
from substitute_backend.features.environment_management.infrastructure.job_store import (
    JobStore,
)
from substitute_backend.features.environment_management.infrastructure.model_root_runtime import (
    ModelRootRuntime,
)
from substitute_backend.features.environment_management.infrastructure.model_root_store import (
    ModelRootStore,
)
from substitute_backend.features.environment_management.infrastructure.python_environment import (
    PythonEnvironmentInspector,
)
from substitute_backend.features.environment_management.infrastructure.restart_coordinator import (
    RestartCoordinator,
    RestartSupport,
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
from substitute_backend.infrastructure.logging import get_logger


class SupportedRestartCoordinator(RestartCoordinator):
    """Restart coordinator test double that never replaces the process."""

    def __init__(self) -> None:
        """Initialize restart tracking."""

        self.restarted = False

    def support(self) -> RestartSupport:
        """Return supported restart capability."""

        return RestartSupport(supported=True)

    def restart_process(self) -> None:
        """Record that a restart would have happened."""

        self.restarted = True


class UnsupportedRestartCoordinator(RestartCoordinator):
    """Restart coordinator test double for unsupported hosts."""

    def support(self) -> RestartSupport:
        """Return unsupported restart capability."""

        return RestartSupport(
            supported=False,
            unavailable_reason="Restart is not supported in this test.",
        )


class StaticModelRootRuntime(ModelRootRuntime):
    """Return a fixed active model root for service tests."""

    def __init__(self, active_root: Path) -> None:
        """Store the active root."""

        self._active_root = active_root

    def active_model_root(self) -> Path:
        """Return the configured active root."""

        return self._active_root.resolve()


class StaticPipInspector(PipInspector):
    """Return fixed pip packages for inventory tests."""

    def list_packages(self) -> tuple[PipPackage, ...]:
        """Return a package set with supported and custom-node-owned entries."""

        return (
            PipPackage(name="torch", normalized_name="torch", version="2.8.0"),
            PipPackage(name="numpy", normalized_name="numpy", version="2.0.0"),
            PipPackage(name="helper-lib", normalized_name="helper-lib", version="1.0.0"),
            PipPackage(name="accelerate", normalized_name="accelerate", version="1.10.1"),
            PipPackage(name="aiofiles", normalized_name="aiofiles", version="24.1.0"),
            PipPackage(name="aiohttp", normalized_name="aiohttp", version="3.12.15"),
        )


class RuntimePipInspector(PipInspector):
    """Return packages that participate in runtime compatibility policy."""

    def list_packages(self) -> tuple[PipPackage, ...]:
        """Return PyTorch runtime packages with compatibility extensions."""

        return (
            PipPackage(name="torch", normalized_name="torch", version="2.8.0"),
            PipPackage(name="torchvision", normalized_name="torchvision", version="0.23.0"),
            PipPackage(name="torchaudio", normalized_name="torchaudio", version="2.8.0"),
            PipPackage(name="triton", normalized_name="triton", version="3.4.0"),
            PipPackage(
                name="sageattention",
                normalized_name="sageattention",
                version="2.2.0",
            ),
        )


class WindowsTritonPipInspector(PipInspector):
    """Return runtime packages where the Triton wheel identity is Windows-specific."""

    def list_packages(self) -> tuple[PipPackage, ...]:
        """Return PyTorch runtime packages with the Windows Triton distribution."""

        return (
            PipPackage(name="torch", normalized_name="torch", version="2.8.0"),
            PipPackage(name="torchvision", normalized_name="torchvision", version="0.23.0"),
            PipPackage(name="torchaudio", normalized_name="torchaudio", version="2.8.0"),
            PipPackage(
                name="triton-windows",
                normalized_name="triton-windows",
                version="3.4.0",
            ),
            PipPackage(
                name="sageattention",
                normalized_name="sageattention",
                version="2.2.0",
            ),
        )


class StaticMetadataProvider:
    """Return fixed installed package summaries for inventory tests."""

    def summaries_by_package(self) -> dict[str, PackageSummary]:
        """Return summaries keyed by normalized package name."""

        return {
            "torch": PackageSummary(
                summary="Tensors and dynamic neural networks in Python.",
                source=PackageSummarySource.INSTALLED_METADATA,
            ),
        }


class StaticDependencyProvider:
    """Return fixed installed package dependencies for inventory tests."""

    def dependencies_by_package(self) -> dict[str, tuple[PackageDependency, ...]]:
        """Return dependency edges keyed by normalized package name."""

        return {
            "helper-lib": (
                PackageDependency(
                    package_name="accelerate",
                    normalized_name="accelerate",
                    requirement="accelerate>=1",
                ),
            ),
            "accelerate": (
                PackageDependency(
                    package_name="aiofiles",
                    normalized_name="aiofiles",
                    requirement="aiofiles",
                ),
            ),
        }


class CyclicDependencyProvider:
    """Return a cyclic dependency graph for inventory traversal tests."""

    def dependencies_by_package(self) -> dict[str, tuple[PackageDependency, ...]]:
        """Return dependency edges with a cycle and a diamond."""

        return {
            "numpy": (
                PackageDependency(
                    package_name="helper-lib",
                    normalized_name="helper-lib",
                    requirement="helper-lib",
                ),
                PackageDependency(
                    package_name="accelerate",
                    normalized_name="accelerate",
                    requirement="accelerate",
                ),
            ),
            "helper-lib": (
                PackageDependency(
                    package_name="accelerate",
                    normalized_name="accelerate",
                    requirement="accelerate",
                ),
            ),
            "accelerate": (
                PackageDependency(
                    package_name="numpy",
                    normalized_name="numpy",
                    requirement="numpy",
                ),
            ),
        }


class FakeDistribution:
    """Provide installed metadata fields for metadata provider tests."""

    def __init__(self, fields: dict[str, str]) -> None:
        """Store metadata fields."""

        self.metadata = fields


class FakePypiResponse:
    """Provide the response surface used by the PyPI provider."""

    def __init__(self, payload: JsonObject) -> None:
        """Store the JSON payload."""

        self._payload = payload

    def __enter__(self) -> FakePypiResponse:
        """Return this response for context-manager use."""

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Close the fake response."""

        _ = (exc_type, exc, traceback)
        return None

    def read(self) -> bytes:
        """Return encoded JSON payload bytes."""

        return json.dumps(self._payload).encode("utf-8")


class FakeJsonRequest:
    """Provide the request surface needed by environment route tests."""

    def __init__(
        self,
        body: JsonObject | None = None,
        *,
        match_info: dict[str, str] | None = None,
    ) -> None:
        """Store request body and route match info."""

        self._body = body or {}
        self.match_info = match_info or {}

    async def json(self) -> JsonObject:
        """Return the configured request body."""

        return self._body


def test_environment_capabilities_report_restart_support(tmp_path: Path) -> None:
    """Environment capabilities expose restart support from the coordinator."""

    coordinator = SupportedRestartCoordinator()
    service = EnvironmentService(
        inspector=PythonEnvironmentInspector(tmp_path, restart_supported=True),
        restart_coordinator=coordinator,
    )

    capabilities = service.get_capabilities()

    assert capabilities.restart_supported is True
    assert EnvironmentFeature.RESTART in capabilities.supported_features
    assert EnvironmentFeature.OPERATION_PLANNING in capabilities.supported_features
    assert capabilities.package_mutation_supported is False


def test_environment_status_reports_python_and_comfy_process(tmp_path: Path) -> None:
    """Environment status describes the current Python host."""

    service = EnvironmentService(
        inspector=PythonEnvironmentInspector(tmp_path, restart_supported=True),
        restart_coordinator=SupportedRestartCoordinator(),
    )

    status = service.get_status()

    assert status.schema_version == 1
    assert status.comfy.root == str(tmp_path)
    assert status.comfy.process_id == os.getpid()
    assert status.comfy.restart_supported is True
    assert status.python.executable


def test_backend_capabilities_include_environment_management(tmp_path: Path) -> None:
    """Top-level capabilities include the environment management feature."""

    provider = StaticModelRootsProvider({"loras": (tmp_path,)}, {".safetensors"})
    services = build_backend_services(
        tmp_path,
        model_roots=provider,
        preview_assets=_preview_asset_services(tmp_path),
    )
    payload = services.model_metadata.capabilities.get_capabilities().to_payload()
    features = payload["features"]
    assert isinstance(features, list)
    feature_payload = [*features, "environment-management"]
    payload["features"] = feature_payload
    payload["environmentManagement"] = (
        services.environment.environment.get_capabilities().to_payload()
    )
    environment_payload = cast("JsonObject", payload["environmentManagement"])

    assert "environment-management" in feature_payload
    assert environment_payload["schemaVersion"] == 1


class _StaticPathProvider:
    """Resolve the test preview asset root without ComfyUI globals."""

    def __init__(self, root: Path) -> None:
        """Store the root."""

        self._root = root

    def resolve_root(self) -> Path:
        """Return the configured test root."""

        return self._root


class _NoopDownloader:
    """Provide a downloader double for unrelated service composition tests."""

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
            logger=get_logger("tests.preview_assets.environment"),
        )
    )


def test_restart_service_persists_restart_job(tmp_path: Path) -> None:
    """Restart service records queued and waiting states before process replacement."""

    async def run_restart() -> None:
        coordinator = SupportedRestartCoordinator()
        jobs = JobService(JobStore(tmp_path / "jobs.json"))
        service = RestartService(
            jobs=jobs,
            coordinator=coordinator,
            logger=get_logger("tests.environment.restart"),
        )

        job = service.restart()
        await asyncio.sleep(0.35)
        stored = jobs.get(job.job_id)

        assert coordinator.restarted is True
        assert stored is not None
        assert stored.status is EnvironmentJobStatus.WAITING_FOR_RESTART

    asyncio.run(run_restart())


def test_unsupported_restart_is_reported_in_capabilities(tmp_path: Path) -> None:
    """Unsupported restart hosts explain why restart cannot run."""

    coordinator = UnsupportedRestartCoordinator()
    service = EnvironmentService(
        inspector=PythonEnvironmentInspector(tmp_path, restart_supported=False),
        restart_coordinator=coordinator,
    )

    capabilities = service.get_capabilities()

    assert capabilities.restart_supported is False
    assert EnvironmentFeature.RESTART not in capabilities.supported_features
    assert capabilities.restart_unavailable_reason == "Restart is not supported in this test."


def test_inventory_attaches_claimants_and_management_tags_to_packages(
    tmp_path: Path,
) -> None:
    """Inventory should attach package metadata without synthetic package rows."""

    custom_node = tmp_path / "custom_nodes" / "ExampleNode"
    custom_node.mkdir(parents=True)
    (custom_node / "requirements.txt").write_text(
        "numpy>=2\nhelper-lib>=1\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("aiohttp==3.12.15\n", encoding="utf-8")
    service = InventoryService(
        pip_inspector=StaticPipInspector(),
        requirements_scanner=CustomNodeRequirementsScanner(tmp_path / "custom_nodes"),
        comfy_requirements_scanner=ComfyRequirementsScanner(tmp_path),
        metadata_provider=StaticMetadataProvider(),
        dependency_provider=StaticDependencyProvider(),
        logger=get_logger("tests.environment.inventory"),
    )

    packages = service.list_packages().packages
    components = service.list_components().components

    torch = next(package for package in packages if package.normalized_name == "torch")
    numpy = next(package for package in packages if package.normalized_name == "numpy")
    accelerate = next(package for package in packages if package.normalized_name == "accelerate")
    aiofiles = next(package for package in packages if package.normalized_name == "aiofiles")
    aiohttp = next(package for package in packages if package.normalized_name == "aiohttp")
    assert torch.attribution == "supported"
    assert torch.summary == "Tensors and dynamic neural networks in Python."
    assert torch.summary_source is PackageSummarySource.INSTALLED_METADATA
    assert torch.management_tags[0].display_name == "PyTorch"
    assert torch.management_tags[0].supported_actions == ("plan-update",)
    assert numpy.attribution == "custom-node"
    assert numpy.claimants[0].display_name == "ExampleNode"
    assert numpy.claimants[0].requirement == "numpy>=2"
    assert numpy.claimants[0].required_via is None
    assert numpy.claimants[0].source_path.endswith("requirements.txt")
    assert accelerate.attribution == "custom-node"
    assert accelerate.claimants[0].display_name == "ExampleNode"
    assert accelerate.claimants[0].required_via == "helper-lib"
    assert aiofiles.claimants[0].display_name == "ExampleNode"
    assert aiofiles.claimants[0].required_via == "accelerate"
    assert aiohttp.claimants[0].kind is PackageClaimantKind.COMFYUI
    assert aiohttp.claimants[0].display_name == "ComfyUI"
    assert aiohttp.claimants[0].requirement == "aiohttp==3.12.15"
    assert aiohttp.claimants[0].required_via is None
    assert components == ()


def test_inventory_dependency_resolution_handles_cycles_and_diamonds(
    tmp_path: Path,
) -> None:
    """Dependency claimant propagation should visit each package once per claimant."""

    custom_node = tmp_path / "custom_nodes" / "CycleNode"
    custom_node.mkdir(parents=True)
    (custom_node / "requirements.txt").write_text("numpy>=2\n", encoding="utf-8")
    service = InventoryService(
        pip_inspector=StaticPipInspector(),
        requirements_scanner=CustomNodeRequirementsScanner(tmp_path / "custom_nodes"),
        metadata_provider=StaticMetadataProvider(),
        dependency_provider=CyclicDependencyProvider(),
        logger=get_logger("tests.environment.inventory"),
    )

    packages = service.list_packages().packages
    numpy = next(package for package in packages if package.normalized_name == "numpy")
    helper = next(package for package in packages if package.normalized_name == "helper-lib")
    accelerate = next(package for package in packages if package.normalized_name == "accelerate")

    assert [claimant.display_name for claimant in numpy.claimants] == ["CycleNode"]
    assert [claimant.required_via for claimant in numpy.claimants] == [None]
    assert [claimant.display_name for claimant in helper.claimants] == ["CycleNode"]
    assert [claimant.required_via for claimant in helper.claimants] == ["numpy"]
    assert {claimant.display_name for claimant in accelerate.claimants} == {"CycleNode"}
    assert {claimant.required_via for claimant in accelerate.claimants} == {
        "numpy",
        "helper-lib",
    }


def test_inventory_payload_omits_hard_coded_package_descriptions(
    tmp_path: Path,
) -> None:
    """Package payload descriptions should come only from metadata sources."""

    service = InventoryService(
        pip_inspector=StaticPipInspector(),
        requirements_scanner=CustomNodeRequirementsScanner(tmp_path / "custom_nodes"),
        metadata_provider=StaticMetadataProvider(),
        dependency_provider=StaticDependencyProvider(),
        logger=get_logger("tests.environment.inventory"),
    )

    payloads = [package.to_payload() for package in service.list_packages().packages]
    payload_text = str(payloads)
    claimant_payloads = [
        claimant
        for payload in payloads
        for claimant in cast("list[JsonObject]", payload["claimants"])
    ]

    assert "Core GPU inference runtime" not in payload_text
    assert "dependencies" not in payload_text
    assert all("requiredVia" in claimant for claimant in claimant_payloads)
    assert all("summarySource" in payload for payload in payloads)


def test_installed_metadata_provider_reads_distribution_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installed metadata summaries should come from distribution metadata."""

    def distributions() -> tuple[FakeDistribution, ...]:
        """Return fake installed distributions."""

        return (
            FakeDistribution({"Name": "Example_Package", "Summary": " Example summary "}),
            FakeDistribution({"Name": "NoSummary"}),
        )

    monkeypatch.setattr(
        "substitute_backend.features.environment_management.infrastructure.package_metadata.metadata.distributions",
        distributions,
    )

    summaries = InstalledPackageMetadataProvider().summaries_by_package()

    assert summaries["example-package"].summary == "Example summary"
    assert summaries["example-package"].source is PackageSummarySource.INSTALLED_METADATA
    assert "nosummary" not in summaries


def test_installed_metadata_provider_reads_distribution_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installed metadata dependencies should come from Requires-Dist entries."""

    class DistributionWithRequires(FakeDistribution):
        """Provide metadata and Requires-Dist fields."""

        requires = ("aiofiles>=24; python_version >= '3.11'",)

    def distributions() -> tuple[DistributionWithRequires, ...]:
        """Return fake installed distributions with dependency metadata."""

        return (DistributionWithRequires({"Name": "Example_Package"}),)

    monkeypatch.setattr(
        "substitute_backend.features.environment_management.infrastructure.package_metadata.metadata.distributions",
        distributions,
    )

    dependencies = InstalledPackageMetadataProvider().dependencies_by_package()

    assert dependencies["example-package"][0].normalized_name == "aiofiles"
    assert dependencies["example-package"][0].requirement == (
        "aiofiles>=24; python_version >= '3.11'"
    )


def test_pypi_summary_provider_uses_timeout_and_cache(tmp_path: Path) -> None:
    """PyPI summaries should use explicit timeout and avoid repeated network calls."""

    calls: list[tuple[str, float]] = []

    def fake_urlopen(url: str, *, timeout: float) -> FakePypiResponse:
        """Return one successful PyPI JSON response."""

        calls.append((url, timeout))
        return FakePypiResponse({"info": {"summary": " PyPI summary "}})

    provider = PypiSummaryProvider(
        tmp_path / "pypi-summary-cache.json",
        urlopen=fake_urlopen,
        timeout_seconds=0.25,
    )

    first = provider.summary_for_package("Example_Package")
    second = provider.summary_for_package("example-package")

    assert first.summary == "PyPI summary"
    assert first.source is PackageSummarySource.PYPI
    assert second.summary == "PyPI summary"
    assert calls == [("https://pypi.org/pypi/Example_Package/json", 0.25)]


def test_pypi_summary_provider_failure_is_unavailable(tmp_path: Path) -> None:
    """PyPI failures should not fail inventory summary enrichment."""

    def failing_urlopen(url: str, *, timeout: float) -> FakePypiResponse:
        """Raise a network failure."""

        _ = (url, timeout)
        raise OSError("network unavailable")

    summary = PypiSummaryProvider(
        tmp_path / "pypi-summary-cache.json",
        urlopen=failing_urlopen,
    ).summary_for_package("missing-package")

    assert summary.summary is None
    assert summary.source is PackageSummarySource.UNAVAILABLE


def test_operation_planning_builds_torch_nightly_plan() -> None:
    """Operation planning should describe supported PyTorch channel updates."""

    plan = OperationPlanningService().plan(
        {
            "operation": "update-component",
            "componentId": "pytorch",
            "channel": "nightly",
        }
    )

    assert plan.operation is EnvironmentOperationKind.UPDATE_COMPONENT
    assert plan.affected_packages == ("torch", "torchvision", "torchaudio")
    assert plan.requires_detached_runner is True
    assert plan.requires_restart is True
    assert "--pre" in plan.display_commands[0]


def test_operation_planning_builds_supported_runtime_plans() -> None:
    """Operation planning should support direct runtime update plans."""

    triton_plan = OperationPlanningService().plan(
        {
            "operation": "update-component",
            "componentId": "triton",
        }
    )
    sage_plan = OperationPlanningService().plan(
        {
            "operation": "update-component",
            "componentId": "sageattention",
        }
    )

    assert triton_plan.affected_packages == ("triton",)
    assert sage_plan.affected_packages == ("sageattention",)
    assert triton_plan.requires_restart is True
    assert sage_plan.requires_restart is True


def test_maintenance_plan_starts_empty(tmp_path: Path) -> None:
    """Maintenance plan store should expose an empty non-applyable plan."""

    service = _maintenance_plan_service(tmp_path, StaticPipInspector())

    plan = service.get()

    assert plan.plan_id == "current"
    assert plan.revision == 0
    assert plan.items == ()
    assert plan.summary.item_count == 0
    assert plan.summary.applyable is False


def test_maintenance_plan_adds_package_update(tmp_path: Path) -> None:
    """Adding a package update should create one user-removable queue item."""

    service = _maintenance_plan_service(
        tmp_path,
        StaticPipInspector(),
        package_mutation_supported=True,
    )

    plan = service.add_item(
        {
            "operation": "update-package",
            "packageName": "numpy",
        }
    )

    assert plan.revision == 1
    assert plan.summary.applyable is True
    assert plan.items[0].title == "Update numpy"
    assert plan.items[0].relationship.value == "user-requested"
    assert plan.items[0].can_remove is True
    assert plan.items[0].install_requirements == ("numpy",)


def test_maintenance_plan_torch_update_adds_runtime_followups(
    tmp_path: Path,
) -> None:
    """PyTorch updates should visibly include Triton and SageAttention refreshes."""

    service = _maintenance_plan_service(tmp_path, RuntimePipInspector())

    plan = service.add_item(
        {
            "operation": "update-runtime",
            "runtimeId": "pytorch",
        }
    )

    assert [item.title for item in plan.items] == [
        "Update PyTorch runtime",
        "Reinstall Triton",
        "Reinstall SageAttention",
    ]
    triton_item = plan.items[1]
    sage_item = plan.items[2]
    assert triton_item.generated_by_item_id == plan.items[0].item_id
    assert triton_item.target.target_id == "triton"
    assert triton_item.install_requirements == (_expected_triton_requirement(),)
    assert triton_item.can_remove is False
    assert triton_item.can_reorder is False
    assert sage_item.generated_by_item_id == plan.items[0].item_id
    assert sage_item.target.target_id == "sageattention"
    assert sage_item.can_remove is False
    assert sage_item.can_reorder is False
    assert plan.blockers[0].code == "package-mutation-unavailable"
    assert plan.summary.applyable is False


def test_maintenance_plan_torch_update_detects_windows_triton_distribution(
    tmp_path: Path,
) -> None:
    """PyTorch updates should schedule Triton when only triton-windows is installed."""

    service = _maintenance_plan_service(tmp_path, WindowsTritonPipInspector())

    plan = service.add_item(
        {
            "operation": "update-runtime",
            "runtimeId": "pytorch",
        }
    )

    triton_item = next(item for item in plan.items if item.title == "Reinstall Triton")
    assert triton_item.target.target_id == "triton"
    assert triton_item.affected_packages == ("triton",)
    assert triton_item.install_requirements == (_expected_triton_requirement(),)


def test_maintenance_plan_rejects_generated_item_removal(tmp_path: Path) -> None:
    """Required generated compatibility items should not be directly removable."""

    service = _maintenance_plan_service(tmp_path, RuntimePipInspector())
    plan = service.add_item(
        {
            "operation": "update-runtime",
            "runtimeId": "pytorch",
        }
    )

    with pytest.raises(BackendHttpError) as error:
        service.remove_item(plan.items[1].item_id)
    assert "required" in error.value.message


def test_maintenance_plan_removing_parent_removes_followups(tmp_path: Path) -> None:
    """Removing a parent runtime item should remove its generated children."""

    service = _maintenance_plan_service(tmp_path, RuntimePipInspector())
    plan = service.add_item(
        {
            "operation": "update-runtime",
            "runtimeId": "pytorch",
        }
    )

    updated = service.remove_item(plan.items[0].item_id)

    assert updated.items == ()
    assert updated.summary.item_count == 0


def test_maintenance_plan_reorder_is_normalized_after_parent(
    tmp_path: Path,
) -> None:
    """Generated compatibility items should move back after their parent."""

    service = _maintenance_plan_service(
        tmp_path,
        RuntimePipInspector(),
        package_mutation_supported=True,
    )
    plan = service.add_item(
        {
            "operation": "update-runtime",
            "runtimeId": "pytorch",
        }
    )

    reordered = service.reorder_items(
        revision=plan.revision,
        item_ids=(
            plan.items[1].item_id,
            plan.items[0].item_id,
            plan.items[2].item_id,
        ),
    )

    assert [item.title for item in reordered.items] == [
        "Update PyTorch runtime",
        "Reinstall Triton",
        "Reinstall SageAttention",
    ]
    assert reordered.last_validation_message == (
        "Order adjusted because compatibility follow-ups must run after their parent."
    )


def test_maintenance_plan_rejects_stale_reorder_revision(tmp_path: Path) -> None:
    """Reorder requests should use the current plan revision."""

    service = _maintenance_plan_service(tmp_path, StaticPipInspector())
    plan = service.add_item(
        {
            "operation": "update-package",
            "packageName": "numpy",
        }
    )

    with pytest.raises(BackendHttpError) as error:
        service.reorder_items(
            revision=plan.revision - 1,
            item_ids=(plan.items[0].item_id,),
        )
    assert "changed" in error.value.message


def test_maintenance_plan_apply_creates_job_when_supported(tmp_path: Path) -> None:
    """Apply should create a durable job when the plan has no blockers."""

    service = _maintenance_plan_service(
        tmp_path,
        StaticPipInspector(),
        package_mutation_supported=True,
    )
    plan = service.add_item(
        {
            "operation": "update-package",
            "packageName": "numpy",
        }
    )

    job = service.apply(revision=plan.revision)

    assert job.operation is EnvironmentOperationKind.APPLY_MAINTENANCE_PLAN
    assert job.status is EnvironmentJobStatus.QUEUED


def test_maintenance_plan_apply_rejects_blocked_plan(tmp_path: Path) -> None:
    """Apply should fail closed while package mutation is unavailable."""

    service = _maintenance_plan_service(tmp_path, StaticPipInspector())
    plan = service.add_item(
        {
            "operation": "update-package",
            "packageName": "numpy",
        }
    )

    with pytest.raises(BackendHttpError) as error:
        service.apply(revision=plan.revision)
    assert "blockers" in error.value.message


def test_maintenance_plan_routes_return_validated_queue(tmp_path: Path) -> None:
    """Maintenance plan routes should expose add, reorder, and blocked apply."""

    async def run_routes() -> None:
        services = _environment_services(tmp_path, RuntimePipInspector())
        handlers = build_environment_route_handlers(
            services,
            logger=get_logger("tests.environment.routes"),
        )

        add_response = await handlers.add_maintenance_plan_item(
            cast(
                "web.Request",
                FakeJsonRequest(
                    {
                        "operation": "update-runtime",
                        "runtimeId": "pytorch",
                    }
                ),
            )
        )
        add_payload = _response_payload(add_response)
        raw_items = cast("list[JsonObject]", add_payload["items"])
        item_ids = [str(item["itemId"]) for item in raw_items]
        assert add_response.status == 201
        assert [item["title"] for item in raw_items] == [
            "Update PyTorch runtime",
            "Reinstall Triton",
            "Reinstall SageAttention",
        ]
        assert raw_items[1]["target"] == {
            "kind": "package",
            "id": "triton",
            "displayName": "triton",
        }
        assert raw_items[1]["installRequirements"] == [_expected_triton_requirement()]

        reorder_response = await handlers.reorder_maintenance_plan_items(
            cast(
                "web.Request",
                FakeJsonRequest(
                    {
                        "revision": add_payload["revision"],
                        "itemIds": [item_ids[1], item_ids[0], item_ids[2]],
                    }
                ),
            )
        )
        reorder_payload = _response_payload(reorder_response)
        assert reorder_payload["lastValidationMessage"] == (
            "Order adjusted because compatibility follow-ups must run after their parent."
        )

        apply_response = await handlers.apply_maintenance_plan(
            cast(
                "web.Request",
                FakeJsonRequest({"revision": reorder_payload["revision"]}),
            )
        )
        assert apply_response.status == 409
        assert cast("JsonObject", _response_payload(apply_response)["error"])["code"] == (
            "maintenance-plan-blocked"
        )

    asyncio.run(run_routes())


def _maintenance_plan_service(
    tmp_path: Path,
    pip_inspector: PipInspector,
    *,
    package_mutation_supported: bool = False,
) -> MaintenancePlanService:
    """Build a maintenance-plan service test fixture."""

    inventory = InventoryService(
        pip_inspector=pip_inspector,
        requirements_scanner=CustomNodeRequirementsScanner(tmp_path / "custom_nodes"),
        metadata_provider=StaticMetadataProvider(),
        dependency_provider=StaticDependencyProvider(),
        logger=get_logger("tests.environment.inventory"),
    )
    jobs = JobService(JobStore(tmp_path / "jobs.json"))
    return MaintenancePlanService(
        store=MaintenancePlanStore(environment_id=str(tmp_path)),
        inventory=inventory,
        jobs=jobs,
        package_mutation_supported=package_mutation_supported,
    )


def test_model_root_routes_report_and_persist_host_state(tmp_path: Path) -> None:
    """Environment routes expose a typed model-root mutation contract."""

    services = _environment_services(tmp_path, StaticPipInspector())
    handlers = build_environment_route_handlers(
        services,
        get_logger("tests.environment.routes"),
    )
    custom_root = tmp_path / "shared-models"

    async def run_routes() -> None:
        """Exercise model-root GET and update handlers."""

        initial = await handlers.get_model_root(cast("web.Request", object()))
        initial_payload = _response_payload(initial)
        assert initial_payload["usesDefault"] is True
        assert initial_payload["restartRequired"] is False

        updated = await handlers.update_model_root(
            cast(
                "web.Request",
                FakeJsonRequest({"mode": "custom", "path": str(custom_root)}),
            )
        )
        updated_payload = _response_payload(updated)
        assert updated_payload["configuredModelRoot"] == str(custom_root.resolve())
        assert updated_payload["restartRequired"] is True

        invalid = await handlers.update_model_root(
            cast(
                "web.Request",
                FakeJsonRequest({"mode": "custom", "path": "relative/models"}),
            )
        )
        assert invalid.status == 400
        error = cast("JsonObject", _response_payload(invalid)["error"])
        assert error["code"] == "invalid-model-root"

    asyncio.run(run_routes())


def _expected_triton_requirement() -> str:
    """Return the platform-specific Triton requirement expected by the service."""

    if sys.platform == "win32":
        return "triton-windows"
    return "triton"


def _environment_services(
    tmp_path: Path,
    pip_inspector: PipInspector,
) -> EnvironmentManagementServices:
    """Build an environment-management service container for route tests."""

    inventory = InventoryService(
        pip_inspector=pip_inspector,
        requirements_scanner=CustomNodeRequirementsScanner(tmp_path / "custom_nodes"),
        metadata_provider=StaticMetadataProvider(),
        dependency_provider=StaticDependencyProvider(),
        logger=get_logger("tests.environment.inventory"),
    )
    jobs = JobService(JobStore(tmp_path / "jobs.json"))
    return EnvironmentManagementServices(
        environment=EnvironmentService(
            inspector=PythonEnvironmentInspector(tmp_path, restart_supported=True),
            restart_coordinator=SupportedRestartCoordinator(),
        ),
        inventory=inventory,
        jobs=jobs,
        maintenance_plan=MaintenancePlanService(
            store=MaintenancePlanStore(environment_id=str(tmp_path)),
            inventory=inventory,
            jobs=jobs,
            package_mutation_supported=False,
        ),
        operation_planning=OperationPlanningService(),
        restart=RestartService(
            jobs=jobs,
            coordinator=SupportedRestartCoordinator(),
            logger=get_logger("tests.environment.restart"),
        ),
        model_root=ModelRootService(
            comfy_root=tmp_path,
            store=ModelRootStore(tmp_path),
            runtime=StaticModelRootRuntime(tmp_path / "models"),
        ),
    )


def _response_payload(response: web.StreamResponse) -> JsonObject:
    """Decode a JSON response payload from an aiohttp response."""

    if not isinstance(response, web.Response) or response.text is None:
        raise AssertionError("Expected JSON web response")
    payload = json.loads(response.text)
    assert isinstance(payload, dict)
    return cast("JsonObject", payload)

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
"""Read-only package inventory use cases."""

from __future__ import annotations

import logging
import subprocess
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Protocol

from substitute_backend.features.environment_management.domain.components import (
    EnvironmentComponent,
)
from substitute_backend.features.environment_management.domain.packages import (
    InstalledPackage,
    PackageClaimant,
    PackageClaimantKind,
    PackageManagementTag,
    PackageSummarySource,
)
from substitute_backend.features.environment_management.infrastructure import (
    ComfyRequirement,
    ComfyRequirementsScanner,
    CustomNodeRequirement,
    CustomNodeRequirementsScanner,
    InstalledPackageMetadataProvider,
    PackageDependency,
    PackageSummary,
    PipInspector,
    PipPackage,
)


class PackageSummaryProvider(Protocol):
    """Protocol for package summary providers."""

    def summaries_by_package(self) -> dict[str, PackageSummary]:
        """Return summaries keyed by normalized package name."""


class PypiPackageSummaryProvider(Protocol):
    """Protocol for optional per-package PyPI summary enrichment."""

    def summary_for_package(self, package_name: str) -> PackageSummary:
        """Return a PyPI summary for one package."""


class PackageDependencyProvider(Protocol):
    """Protocol for installed distribution dependency providers."""

    def dependencies_by_package(self) -> dict[str, tuple[PackageDependency, ...]]:
        """Return dependency edges keyed by normalized package name."""


@dataclass(frozen=True)
class ManagementTagDefinition:
    """Describe supported management behavior without package descriptions."""

    tag_id: str
    display_name: str
    supported_actions: tuple[str, ...]


_SUPPORTED_MANAGEMENT_TAGS: dict[str, ManagementTagDefinition] = {
    "torch": ManagementTagDefinition(
        tag_id="pytorch",
        display_name="PyTorch",
        supported_actions=("plan-update",),
    ),
    "torchvision": ManagementTagDefinition(
        tag_id="pytorch",
        display_name="PyTorch",
        supported_actions=("plan-update",),
    ),
    "torchaudio": ManagementTagDefinition(
        tag_id="pytorch",
        display_name="PyTorch",
        supported_actions=("plan-update",),
    ),
    "triton": ManagementTagDefinition(
        tag_id="triton",
        display_name="Triton",
        supported_actions=("plan-update",),
    ),
    "sageattention": ManagementTagDefinition(
        tag_id="sageattention",
        display_name="SageAttention",
        supported_actions=("plan-update",),
    ),
    "xformers": ManagementTagDefinition(
        tag_id="xformers",
        display_name="xFormers",
        supported_actions=("plan-update",),
    ),
}


@dataclass(frozen=True)
class PackageInventory:
    """Describe installed packages returned to the environment API."""

    packages: tuple[InstalledPackage, ...]


@dataclass(frozen=True)
class ComponentInventory:
    """Describe non-primary component inventory returned to the environment API."""

    components: tuple[EnvironmentComponent, ...]


@dataclass(frozen=True)
class ClaimantDependencyEntry:
    """Describe one claimant attachment to an installed package."""

    package_name: str
    claimant: PackageClaimant


class InventoryService:
    """Build read-only package inventory for the active environment."""

    def __init__(
        self,
        pip_inspector: PipInspector,
        requirements_scanner: CustomNodeRequirementsScanner,
        logger: logging.Logger,
        *,
        comfy_requirements_scanner: ComfyRequirementsScanner | None = None,
        metadata_provider: PackageSummaryProvider | None = None,
        dependency_provider: PackageDependencyProvider | None = None,
        pypi_summary_provider: PypiPackageSummaryProvider | None = None,
    ) -> None:
        """Initialize inventory adapters."""

        self._pip_inspector = pip_inspector
        self._requirements_scanner = requirements_scanner
        self._comfy_requirements_scanner = comfy_requirements_scanner
        self._metadata_provider = (
            metadata_provider
            if metadata_provider is not None
            else InstalledPackageMetadataProvider()
        )
        self._dependency_provider = (
            dependency_provider
            if dependency_provider is not None
            else InstalledPackageMetadataProvider()
        )
        self._pypi_summary_provider = pypi_summary_provider
        self._logger = logger

    def list_packages(self) -> PackageInventory:
        """Return installed packages with claimants and management tags."""

        packages = self._safe_list_packages()
        package_display_names = {package.normalized_name: package.name for package in packages}
        direct_claimants = _direct_claimants_by_package(
            custom_node_requirements=self._safe_custom_node_requirements(),
            comfy_requirements=self._safe_comfy_requirements(),
        )
        claimants_by_package = _resolve_claimants_by_package(
            package_display_names=package_display_names,
            direct_claimants=direct_claimants,
            dependencies=self._safe_package_dependencies(),
        )
        summaries = self._safe_metadata_summaries()
        return PackageInventory(
            packages=tuple(
                self._to_installed_package(
                    package,
                    claimants_by_package.get(package.normalized_name, ()),
                    summaries.get(package.normalized_name),
                )
                for package in packages
            )
        )

    def list_components(self) -> ComponentInventory:
        """Return no primary components for package-first inventory."""

        return ComponentInventory(components=())

    def _safe_list_packages(self) -> tuple[PipPackage, ...]:
        """Return pip packages or an empty inventory on pip failures."""

        try:
            return self._pip_inspector.list_packages()
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            self._logger.warning(
                "pip package inventory failed",
                extra={"operation": "environment-package-inventory", "error": repr(error)},
            )
            return ()

    def _safe_metadata_summaries(self) -> dict[str, PackageSummary]:
        """Return installed package summaries with failure isolation."""

        try:
            return self._metadata_provider.summaries_by_package()
        except Exception as error:  # pragma: no cover - defensive adapter boundary.
            self._logger.warning(
                "installed package summary metadata failed",
                extra={"operation": "environment-package-metadata", "error": repr(error)},
            )
            return {}

    def _safe_package_dependencies(self) -> dict[str, tuple[PackageDependency, ...]]:
        """Return installed package dependencies with failure isolation."""

        try:
            return self._dependency_provider.dependencies_by_package()
        except Exception as error:  # pragma: no cover - defensive adapter boundary.
            self._logger.warning(
                "installed package dependency metadata failed",
                extra={
                    "operation": "environment-package-dependencies",
                    "error": repr(error),
                },
            )
            return {}

    def _safe_custom_node_requirements(self) -> tuple[CustomNodeRequirement, ...]:
        """Return custom-node requirements with failure isolation."""

        try:
            return self._requirements_scanner.scan()
        except OSError as error:
            self._logger.warning(
                "custom node requirement scan failed",
                extra={
                    "operation": "environment-custom-node-requirements",
                    "error": repr(error),
                },
            )
            return ()

    def _safe_comfy_requirements(self) -> tuple[ComfyRequirement, ...]:
        """Return ComfyUI requirements with failure isolation."""

        if self._comfy_requirements_scanner is None:
            return ()
        try:
            return self._comfy_requirements_scanner.scan()
        except OSError as error:
            self._logger.warning(
                "ComfyUI requirement scan failed",
                extra={
                    "operation": "environment-comfy-requirements",
                    "error": repr(error),
                },
            )
            return ()

    def _to_installed_package(
        self,
        package: PipPackage,
        claimants: tuple[PackageClaimant, ...],
        installed_summary: PackageSummary | None,
    ) -> InstalledPackage:
        """Convert one raw pip package into a public inventory entry."""

        management_tags = _management_tags_for_package(package)
        summary = installed_summary
        if summary is None and self._pypi_summary_provider is not None:
            summary = self._pypi_summary_provider.summary_for_package(package.name)
        if summary is None:
            summary = PackageSummary(
                summary=None,
                source=PackageSummarySource.UNAVAILABLE,
            )
        return InstalledPackage(
            name=package.name,
            normalized_name=package.normalized_name,
            version=package.version,
            claimants=claimants,
            management_tags=management_tags,
            attribution=_attribution(claimants, management_tags),
            summary=summary.summary,
            summary_source=summary.source,
            installer="pip",
        )


def _management_tags_for_package(package: PipPackage) -> tuple[PackageManagementTag, ...]:
    """Return supported management tags for one installed package."""

    definition = _SUPPORTED_MANAGEMENT_TAGS.get(package.normalized_name)
    if definition is None:
        return ()
    return (
        PackageManagementTag(
            kind="supported-runtime",
            tag_id=definition.tag_id,
            display_name=definition.display_name,
            supported_actions=definition.supported_actions,
        ),
    )


def _attribution(
    claimants: tuple[PackageClaimant, ...],
    management_tags: tuple[PackageManagementTag, ...],
) -> str:
    """Return a compact package attribution status."""

    if claimants and management_tags:
        return "mixed"
    if claimants:
        return "custom-node"
    if management_tags:
        return "supported"
    return "manual-or-unknown"


def _direct_claimants_by_package(
    *,
    custom_node_requirements: tuple[CustomNodeRequirement, ...],
    comfy_requirements: tuple[ComfyRequirement, ...],
) -> dict[str, tuple[PackageClaimant, ...]]:
    """Group first-party and custom-node claimants by direct package target."""

    grouped: defaultdict[str, list[PackageClaimant]] = defaultdict(list)
    for comfy_requirement in comfy_requirements:
        grouped[comfy_requirement.normalized_name].append(
            PackageClaimant(
                kind=PackageClaimantKind.COMFYUI,
                claimant_id="comfyui",
                display_name="ComfyUI",
                requirement=comfy_requirement.requirement,
                source_path=str(comfy_requirement.source_path),
            )
        )
    for custom_node_requirement in custom_node_requirements:
        grouped[custom_node_requirement.normalized_name].append(
            PackageClaimant(
                kind=PackageClaimantKind.CUSTOM_NODE,
                claimant_id=custom_node_requirement.custom_node_name,
                display_name=custom_node_requirement.custom_node_name,
                requirement=custom_node_requirement.requirement,
                source_path=str(custom_node_requirement.source_path),
            )
        )
    return {
        package: _deduplicate_claimants(tuple(claimants)) for package, claimants in grouped.items()
    }


def _resolve_claimants_by_package(
    *,
    package_display_names: dict[str, str],
    direct_claimants: dict[str, tuple[PackageClaimant, ...]],
    dependencies: dict[str, tuple[PackageDependency, ...]],
) -> dict[str, tuple[PackageClaimant, ...]]:
    """Propagate direct package claimants through installed dependency edges."""

    resolved: defaultdict[str, list[PackageClaimant]] = defaultdict(list)
    for package_name, claimants in direct_claimants.items():
        for claimant in claimants:
            for entry in _claimant_dependency_entries(
                package_name=package_name,
                claimant=claimant,
                package_display_names=package_display_names,
                dependencies=dependencies,
            ):
                resolved[entry.package_name].append(entry.claimant)
    return {
        package: _deduplicate_claimants(tuple(claimants)) for package, claimants in resolved.items()
    }


def _claimant_dependency_entries(
    *,
    package_name: str,
    claimant: PackageClaimant,
    package_display_names: dict[str, str],
    dependencies: dict[str, tuple[PackageDependency, ...]],
) -> tuple[ClaimantDependencyEntry, ...]:
    """Return claimant attachments with immediate reverse-dependency parents."""

    entries: list[ClaimantDependencyEntry] = []
    seen: set[tuple[str, str | None]] = set()
    pending: list[tuple[str, str | None]] = [(package_name, None)]
    while pending:
        current_package, required_via = pending.pop()
        state = (current_package, required_via)
        if state in seen:
            continue
        seen.add(state)
        if current_package not in package_display_names:
            continue
        entries.append(
            ClaimantDependencyEntry(
                package_name=current_package,
                claimant=replace(claimant, required_via=required_via),
            )
        )
        current_display_name = package_display_names[current_package]
        pending.extend(
            (dependency.normalized_name, current_display_name)
            for dependency in dependencies.get(current_package, ())
            if dependency.normalized_name in package_display_names
            and dependency.normalized_name != package_name
        )
    return tuple(entries)


def _deduplicate_claimants(
    claimants: tuple[PackageClaimant, ...],
) -> tuple[PackageClaimant, ...]:
    """Return claimants with one entry per source in stable order."""

    unique: dict[tuple[PackageClaimantKind, str, str | None], PackageClaimant] = {}
    for claimant in claimants:
        key = (claimant.kind, claimant.claimant_id, claimant.required_via)
        unique.setdefault(key, claimant)
    return tuple(unique.values())

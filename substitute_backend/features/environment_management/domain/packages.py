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
"""Python environment status models for Comfy host reporting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from substitute_backend.api.serialization import JsonObject


@dataclass(frozen=True)
class PythonEnvironmentStatus:
    """Describe the Python interpreter running the current Comfy server."""

    executable: str
    version: str
    prefix: str
    base_prefix: str
    is_virtual_environment: bool

    def to_payload(self) -> JsonObject:
        """Return the Python status payload."""

        return {
            "executable": self.executable,
            "version": self.version,
            "prefix": self.prefix,
            "basePrefix": self.base_prefix,
            "isVirtualEnvironment": self.is_virtual_environment,
        }


@dataclass(frozen=True)
class ComfyHostStatus:
    """Describe Comfy process facts relevant to environment operations."""

    root: str
    process_id: int
    restart_supported: bool

    def to_payload(self) -> JsonObject:
        """Return the Comfy host status payload."""

        return {
            "root": self.root,
            "processId": self.process_id,
            "restartSupported": self.restart_supported,
        }


@dataclass(frozen=True)
class EnvironmentAvailability:
    """Describe currently available environment management surfaces."""

    inventory_available: bool
    mutation_available: bool

    def to_payload(self) -> JsonObject:
        """Return the environment availability payload."""

        return {
            "inventoryAvailable": self.inventory_available,
            "mutationAvailable": self.mutation_available,
        }


@dataclass(frozen=True)
class EnvironmentStatus:
    """Describe the active Comfy Python environment."""

    schema_version: int
    python: PythonEnvironmentStatus
    comfy: ComfyHostStatus
    environment: EnvironmentAvailability

    def to_payload(self) -> JsonObject:
        """Return the complete environment status payload."""

        return {
            "schemaVersion": self.schema_version,
            "python": self.python.to_payload(),
            "comfy": self.comfy.to_payload(),
            "environment": self.environment.to_payload(),
        }


class PackageSummarySource(StrEnum):
    """Identify where a package summary came from."""

    INSTALLED_METADATA = "installed-metadata"
    PYPI = "pypi"
    UNAVAILABLE = "unavailable"


class PackageClaimantKind(StrEnum):
    """Identify a source that declares a package dependency."""

    COMFYUI = "comfyui"
    CUSTOM_NODE = "custom-node"


@dataclass(frozen=True)
class PackageClaimant:
    """Describe one dependency source attached to an installed package."""

    kind: PackageClaimantKind
    claimant_id: str
    display_name: str
    requirement: str
    source_path: str
    required_via: str | None = None

    def to_payload(self) -> JsonObject:
        """Return the package claimant payload."""

        return {
            "kind": self.kind.value,
            "id": self.claimant_id,
            "displayName": self.display_name,
            "requirement": self.requirement,
            "sourcePath": self.source_path,
            "requiredVia": self.required_via,
        }


@dataclass(frozen=True)
class PackageManagementTag:
    """Describe backend-supported management behavior for a package."""

    kind: str
    tag_id: str
    display_name: str
    supported_actions: tuple[str, ...] = ()

    def to_payload(self) -> JsonObject:
        """Return the management tag payload."""

        return {
            "kind": self.kind,
            "id": self.tag_id,
            "displayName": self.display_name,
            "supportedActions": list(self.supported_actions),
        }


@dataclass(frozen=True)
class InstalledPackage:
    """Describe one installed Python package."""

    name: str
    normalized_name: str
    version: str
    claimants: tuple[PackageClaimant, ...]
    management_tags: tuple[PackageManagementTag, ...]
    attribution: str
    summary: str | None = None
    summary_source: PackageSummarySource = PackageSummarySource.UNAVAILABLE
    location: str | None = None
    installer: str | None = None
    editable: bool = False

    def to_payload(self) -> JsonObject:
        """Return the installed package payload."""

        payload: JsonObject = {
            "name": self.name,
            "normalizedName": self.normalized_name,
            "version": self.version,
            "claimants": [claimant.to_payload() for claimant in self.claimants],
            "managementTags": [tag.to_payload() for tag in self.management_tags],
            "attribution": self.attribution,
            "summary": self.summary,
            "summarySource": self.summary_source.value,
            "editable": self.editable,
        }
        if self.location is not None:
            payload["location"] = self.location
        if self.installer is not None:
            payload["installer"] = self.installer
        return payload

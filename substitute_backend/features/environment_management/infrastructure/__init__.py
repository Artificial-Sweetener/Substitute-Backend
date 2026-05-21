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
"""Infrastructure adapters for environment management."""

from __future__ import annotations

from .comfy_requirements import (
    ComfyRequirement,
    ComfyRequirementsScanner,
)
from .custom_node_requirements import (
    CustomNodeRequirement,
    CustomNodeRequirementsScanner,
)
from .maintenance_plan_store import MaintenancePlanRecord, MaintenancePlanStore
from .package_metadata import (
    InstalledPackageMetadataProvider,
    PackageDependency,
    PackageSummary,
)
from .pip_inspector import (
    PipInspector,
    PipPackage,
    normalize_package_name,
)
from .pypi_metadata import PypiSummaryProvider

__all__ = [
    "ComfyRequirement",
    "ComfyRequirementsScanner",
    "CustomNodeRequirement",
    "CustomNodeRequirementsScanner",
    "InstalledPackageMetadataProvider",
    "MaintenancePlanRecord",
    "MaintenancePlanStore",
    "PackageDependency",
    "PackageSummary",
    "PipInspector",
    "PipPackage",
    "PypiSummaryProvider",
    "normalize_package_name",
]

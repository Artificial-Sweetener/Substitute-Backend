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
"""Domain models for Cube Library feature contracts."""

from __future__ import annotations

from dataclasses import dataclass

from substitute_backend.api.serialization import JsonObject


@dataclass(frozen=True)
class CubeLibraryCapabilities:
    """Describe Cube Library support in the active target backend."""

    schema_version: int = 1
    catalog_supported: bool = True
    artifact_load_supported: bool = True
    workflow_compile_supported: bool = False
    pack_management_supported: bool = True
    dependency_readiness_supported: bool = True

    def to_payload(self) -> JsonObject:
        """Return the public capability payload."""

        return {
            "schemaVersion": self.schema_version,
            "catalogSupported": self.catalog_supported,
            "artifactLoadSupported": self.artifact_load_supported,
            "workflowCompileSupported": self.workflow_compile_supported,
            "packManagementSupported": self.pack_management_supported,
            "dependencyReadinessSupported": self.dependency_readiness_supported,
        }

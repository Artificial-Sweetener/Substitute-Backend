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
"""Capability contracts for Comfy Python environment management."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from substitute_backend.api.serialization import JsonObject


class EnvironmentFeature(StrEnum):
    """Identify environment management feature support."""

    PACKAGE_INVENTORY = "package-inventory"
    COMPONENT_INVENTORY = "component-inventory"
    RESTART = "restart"
    OPERATION_PLANNING = "operation-planning"
    PACKAGE_MUTATION = "package-mutation"
    MODEL_ROOT_MANAGEMENT = "model-root-management"


@dataclass(frozen=True)
class EnvironmentCapabilities:
    """Describe host-supported environment management behavior."""

    schema_version: int
    supported_features: tuple[EnvironmentFeature, ...]
    restart_supported: bool
    package_mutation_supported: bool
    operation_planning_supported: bool
    model_root_management_supported: bool
    restart_unavailable_reason: str | None = None

    def to_payload(self) -> JsonObject:
        """Return the environment capability payload."""

        payload: JsonObject = {
            "schemaVersion": self.schema_version,
            "supportedFeatures": [feature.value for feature in self.supported_features],
            "restartSupported": self.restart_supported,
            "packageMutationSupported": self.package_mutation_supported,
            "operationPlanningSupported": self.operation_planning_supported,
            "modelRootManagementSupported": self.model_root_management_supported,
        }
        if self.restart_unavailable_reason is not None:
            payload["restartUnavailableReason"] = self.restart_unavailable_reason
        return payload

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
"""Environment status and capability use cases."""

from __future__ import annotations

from dataclasses import dataclass

from substitute_backend import ENVIRONMENT_MANAGEMENT_SCHEMA_VERSION
from substitute_backend.features.environment_management.domain.capabilities import (
    EnvironmentCapabilities,
    EnvironmentFeature,
)
from substitute_backend.features.environment_management.domain.packages import (
    EnvironmentStatus,
)
from substitute_backend.features.environment_management.infrastructure.python_environment import (
    PythonEnvironmentInspector,
)
from substitute_backend.features.environment_management.infrastructure.restart_coordinator import (
    RestartCoordinator,
)


@dataclass(frozen=True)
class EnvironmentService:
    """Report environment management support and current host status."""

    inspector: PythonEnvironmentInspector
    restart_coordinator: RestartCoordinator

    def get_capabilities(self) -> EnvironmentCapabilities:
        """Return environment management capabilities for this host."""

        restart_support = self.restart_coordinator.support()
        supported_features: list[EnvironmentFeature] = [
            EnvironmentFeature.PACKAGE_INVENTORY,
            EnvironmentFeature.COMPONENT_INVENTORY,
            EnvironmentFeature.OPERATION_PLANNING,
            EnvironmentFeature.MODEL_ROOT_MANAGEMENT,
        ]
        if restart_support.supported:
            supported_features.append(EnvironmentFeature.RESTART)
        return EnvironmentCapabilities(
            schema_version=ENVIRONMENT_MANAGEMENT_SCHEMA_VERSION,
            supported_features=tuple(supported_features),
            restart_supported=restart_support.supported,
            package_mutation_supported=False,
            operation_planning_supported=True,
            model_root_management_supported=True,
            restart_unavailable_reason=restart_support.unavailable_reason,
        )

    def get_status(self) -> EnvironmentStatus:
        """Return current Comfy Python environment status."""

        return self.inspector.get_status()

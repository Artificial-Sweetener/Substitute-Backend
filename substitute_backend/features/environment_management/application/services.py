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
"""Service container for the environment management feature."""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class EnvironmentManagementServices:
    """Own environment management application services."""

    environment: EnvironmentService
    inventory: InventoryService
    jobs: JobService
    maintenance_plan: MaintenancePlanService
    operation_planning: OperationPlanningService
    restart: RestartService

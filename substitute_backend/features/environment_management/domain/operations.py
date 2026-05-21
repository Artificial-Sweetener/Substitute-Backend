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
"""Operation identifiers for environment management jobs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from substitute_backend.api.serialization import JsonObject


class EnvironmentOperationKind(StrEnum):
    """Identify user-requested environment operations."""

    RESTART_COMFY = "restart-comfy"
    REFRESH_INVENTORY = "refresh-inventory"
    INSTALL_PACKAGE = "install-package"
    UNINSTALL_PACKAGE = "uninstall-package"
    UPDATE_PACKAGE = "update-package"
    UPDATE_COMPONENT = "update-component"
    UPDATE_RUNTIME = "update-runtime"
    SWITCH_TORCH_CHANNEL = "switch-torch-channel"
    APPLY_MAINTENANCE_PLAN = "apply-maintenance-plan"


@dataclass(frozen=True)
class EnvironmentOperationPlan:
    """Describe a proposed environment operation before execution."""

    plan_id: str
    operation: EnvironmentOperationKind
    affected_packages: tuple[str, ...]
    summary: str
    warnings: tuple[str, ...]
    requires_comfy_stop: bool
    requires_restart: bool
    requires_detached_runner: bool
    display_commands: tuple[tuple[str, ...], ...] = ()

    def to_payload(self) -> JsonObject:
        """Return the operation plan payload."""

        return {
            "schemaVersion": 1,
            "planId": self.plan_id,
            "operation": self.operation.value,
            "affectedPackages": list(self.affected_packages),
            "summary": self.summary,
            "warnings": list(self.warnings),
            "requiresComfyStop": self.requires_comfy_stop,
            "requiresRestart": self.requires_restart,
            "requiresDetachedRunner": self.requires_detached_runner,
            "displayCommands": [list(command) for command in self.display_commands],
        }

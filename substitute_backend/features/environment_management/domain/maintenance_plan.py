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
"""Maintenance-plan contracts for environment package operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from substitute_backend.api.serialization import JsonObject


class MaintenancePlanRelationship(StrEnum):
    """Identify why a plan item exists in the queue."""

    USER_REQUESTED = "user-requested"
    REQUIRED_COMPATIBILITY_FOLLOW_UP = "required-compatibility-follow-up"
    RECOMMENDED_COMPATIBILITY_FOLLOW_UP = "recommended-compatibility-follow-up"


class MaintenancePlanRequestSource(StrEnum):
    """Identify the source that requested a plan item."""

    USER = "user"
    BACKEND_POLICY = "backend-policy"


@dataclass(frozen=True)
class MaintenancePlanTarget:
    """Describe the primary target for one maintenance item."""

    kind: str
    target_id: str
    display_name: str

    def to_payload(self) -> JsonObject:
        """Return the public target payload."""

        return {
            "kind": self.kind,
            "id": self.target_id,
            "displayName": self.display_name,
        }


@dataclass(frozen=True)
class MaintenancePlanRequest:
    """Describe who requested one maintenance item."""

    source: MaintenancePlanRequestSource
    package_name: str | None = None

    def to_payload(self) -> JsonObject:
        """Return the public request payload."""

        payload: JsonObject = {"source": self.source.value}
        if self.package_name is not None:
            payload["packageName"] = self.package_name
        return payload


@dataclass(frozen=True)
class MaintenancePlanIssue:
    """Describe one warning or blocker on a maintenance plan."""

    code: str
    message: str
    item_id: str | None = None

    def to_payload(self) -> JsonObject:
        """Return the public issue payload."""

        payload: JsonObject = {
            "code": self.code,
            "message": self.message,
        }
        if self.item_id is not None:
            payload["itemId"] = self.item_id
        return payload


@dataclass(frozen=True)
class MaintenancePlanItem:
    """Describe one ordered operation in the maintenance queue."""

    item_id: str
    operation: str
    title: str
    target: MaintenancePlanTarget
    requested: MaintenancePlanRequest
    generated: bool
    relationship: MaintenancePlanRelationship
    affected_packages: tuple[str, ...]
    install_requirements: tuple[str, ...]
    requires_comfy_stop: bool
    requires_comfy_restart: bool
    locked_relative_order: bool
    can_remove: bool
    can_reorder: bool
    generated_by_item_id: str | None = None
    warnings: tuple[MaintenancePlanIssue, ...] = ()
    blockers: tuple[MaintenancePlanIssue, ...] = ()

    def to_payload(self) -> JsonObject:
        """Return the public plan item payload."""

        return {
            "itemId": self.item_id,
            "operation": self.operation,
            "title": self.title,
            "target": self.target.to_payload(),
            "requested": self.requested.to_payload(),
            "generated": self.generated,
            "generatedByItemId": self.generated_by_item_id,
            "relationship": self.relationship.value,
            "affectedPackages": list(self.affected_packages),
            "installRequirements": list(self.install_requirements),
            "requiresComfyStop": self.requires_comfy_stop,
            "requiresComfyRestart": self.requires_comfy_restart,
            "lockedRelativeOrder": self.locked_relative_order,
            "canRemove": self.can_remove,
            "canReorder": self.can_reorder,
            "warnings": [warning.to_payload() for warning in self.warnings],
            "blockers": [blocker.to_payload() for blocker in self.blockers],
        }


@dataclass(frozen=True)
class MaintenanceExecutionPhase:
    """Describe one execution phase for the current maintenance plan."""

    phase_id: str
    title: str
    item_ids: tuple[str, ...]
    requires_comfy_stop: bool
    requires_comfy_restart: bool

    def to_payload(self) -> JsonObject:
        """Return the public execution phase payload."""

        return {
            "phaseId": self.phase_id,
            "title": self.title,
            "itemIds": list(self.item_ids),
            "requiresComfyStop": self.requires_comfy_stop,
            "requiresComfyRestart": self.requires_comfy_restart,
        }


@dataclass(frozen=True)
class MaintenancePlanSummary:
    """Summarize whether a maintenance plan can be applied."""

    item_count: int
    affected_package_count: int
    requires_comfy_stop: bool
    requires_comfy_restart: bool
    applyable: bool

    def to_payload(self) -> JsonObject:
        """Return the public summary payload."""

        return {
            "itemCount": self.item_count,
            "affectedPackageCount": self.affected_package_count,
            "requiresComfyStop": self.requires_comfy_stop,
            "requiresComfyRestart": self.requires_comfy_restart,
            "applyable": self.applyable,
        }


@dataclass(frozen=True)
class MaintenancePlan:
    """Describe the current backend-owned environment maintenance queue."""

    plan_id: str
    environment_id: str
    revision: int
    items: tuple[MaintenancePlanItem, ...]
    execution_phases: tuple[MaintenanceExecutionPhase, ...]
    warnings: tuple[MaintenancePlanIssue, ...]
    blockers: tuple[MaintenancePlanIssue, ...]
    summary: MaintenancePlanSummary
    last_validation_message: str | None = None

    def to_payload(self) -> JsonObject:
        """Return the public maintenance-plan payload."""

        return {
            "schemaVersion": 1,
            "planId": self.plan_id,
            "environmentId": self.environment_id,
            "revision": self.revision,
            "items": [item.to_payload() for item in self.items],
            "executionPhases": [phase.to_payload() for phase in self.execution_phases],
            "warnings": [warning.to_payload() for warning in self.warnings],
            "blockers": [blocker.to_payload() for blocker in self.blockers],
            "summary": self.summary.to_payload(),
            "lastValidationMessage": self.last_validation_message,
        }

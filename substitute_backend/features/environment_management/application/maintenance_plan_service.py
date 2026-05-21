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
"""Compose and validate backend-owned environment maintenance plans."""

from __future__ import annotations

import sys

from substitute_backend.api.errors import BackendHttpError
from substitute_backend.features.environment_management.application.inventory_service import (
    InventoryService,
)
from substitute_backend.features.environment_management.application.job_service import (
    JobService,
)
from substitute_backend.features.environment_management.domain.jobs import EnvironmentJob
from substitute_backend.features.environment_management.domain.maintenance_plan import (
    MaintenanceExecutionPhase,
    MaintenancePlan,
    MaintenancePlanIssue,
    MaintenancePlanItem,
    MaintenancePlanRelationship,
    MaintenancePlanRequest,
    MaintenancePlanRequestSource,
    MaintenancePlanSummary,
    MaintenancePlanTarget,
)
from substitute_backend.features.environment_management.domain.operations import (
    EnvironmentOperationKind,
)
from substitute_backend.features.environment_management.infrastructure import (
    MaintenancePlanRecord,
    MaintenancePlanStore,
)

_PYTORCH_PACKAGES = ("torch", "torchvision", "torchaudio")
_TRITON_PACKAGE = "triton"
_TRITON_WINDOWS_PACKAGE = "triton-windows"
_SAGEATTENTION_PACKAGE = "sageattention"


class MaintenancePlanService:
    """Own the current editable package maintenance queue."""

    def __init__(
        self,
        *,
        store: MaintenancePlanStore,
        inventory: InventoryService,
        jobs: JobService,
        package_mutation_supported: bool,
    ) -> None:
        """Initialize the service with plan state and environment adapters."""

        self._store = store
        self._inventory = inventory
        self._jobs = jobs
        self._package_mutation_supported = package_mutation_supported

    def get(self) -> MaintenancePlan:
        """Return the current validated maintenance plan."""

        record = self._validate_and_persist(self._store.get())
        return self._to_plan(record, last_validation_message=None)

    def add_item(self, request: dict[str, object]) -> MaintenancePlan:
        """Add one requested operation to the maintenance queue."""

        record = self._store.get()
        new_items = self._items_for_request(request)
        existing = list(record.items)
        changed = False
        for new_item in new_items:
            if _contains_equivalent_item(tuple(existing), new_item):
                continue
            existing.append(new_item)
            changed = True
        if not changed:
            return self._to_plan(record, last_validation_message="Item is already planned.")
        saved = self._store.save(tuple(existing))
        validated = self._validate_and_persist(saved)
        return self._to_plan(
            validated,
            last_validation_message=_add_message(new_items),
        )

    def remove_item(self, item_id: str) -> MaintenancePlan:
        """Remove one user-removable item from the maintenance queue."""

        record = self._store.get()
        item = _find_item(record.items, item_id)
        if item is None:
            raise BackendHttpError(
                message="Maintenance plan item not found.",
                status=404,
                code="maintenance-plan-item-not-found",
            )
        if not item.can_remove:
            raise BackendHttpError(
                message="This generated item is required by another planned change.",
                status=409,
                code="maintenance-plan-item-required",
            )
        removed_ids = {item_id}
        removed_ids.update(
            existing.item_id
            for existing in record.items
            if existing.generated_by_item_id == item_id
        )
        saved = self._store.save(
            tuple(existing for existing in record.items if existing.item_id not in removed_ids)
        )
        validated = self._validate_and_persist(saved)
        return self._to_plan(validated, last_validation_message="Planned item removed.")

    def reorder_items(
        self,
        *,
        revision: int,
        item_ids: tuple[str, ...],
    ) -> MaintenancePlan:
        """Apply a user-proposed item order and return backend-normalized order."""

        record = self._store.get()
        _require_revision(record, revision)
        existing_by_id = {item.item_id: item for item in record.items}
        if set(item_ids) != set(existing_by_id):
            raise BackendHttpError(
                message="Reorder request must include every current plan item.",
                status=400,
                code="invalid-maintenance-plan-reorder",
            )
        saved = self._store.save(tuple(existing_by_id[item_id] for item_id in item_ids))
        normalized, adjusted = _normalize_order(saved.items)
        if adjusted:
            saved = self._store.save(normalized)
        message = (
            "Order adjusted because compatibility follow-ups must run after their parent."
            if adjusted
            else "Planned order updated."
        )
        return self._to_plan(saved, last_validation_message=message)

    def clear(self) -> MaintenancePlan:
        """Remove all planned maintenance work."""

        saved = self._store.save(())
        return self._to_plan(saved, last_validation_message="Planned changes cleared.")

    def validate(self) -> MaintenancePlan:
        """Validate and normalize the current maintenance plan."""

        record = self._validate_and_persist(self._store.get())
        return self._to_plan(record, last_validation_message="Planned changes validated.")

    def apply(self, *, revision: int) -> EnvironmentJob:
        """Create an apply job when the current plan is executable."""

        record = self._validate_and_persist(self._store.get())
        _require_revision(record, revision)
        plan = self._to_plan(record, last_validation_message=None)
        if plan.blockers:
            raise BackendHttpError(
                message="Maintenance plan has blockers and cannot be applied.",
                status=409,
                code="maintenance-plan-blocked",
            )
        return self._jobs.create(
            EnvironmentOperationKind.APPLY_MAINTENANCE_PLAN,
            "Maintenance plan queued for execution.",
        )

    def _items_for_request(
        self,
        request: dict[str, object],
    ) -> tuple[MaintenancePlanItem, ...]:
        """Build one or more plan items from a backend action request."""

        operation = _required_str(request, "operation")
        if operation in {"update-runtime", "update-component"}:
            runtime_id = _optional_str(request, "runtimeId") or _optional_str(
                request,
                "componentId",
            )
            if runtime_id == "pytorch":
                return self._pytorch_runtime_items()
            if runtime_id in {_TRITON_PACKAGE, _SAGEATTENTION_PACKAGE}:
                return (self._package_update_item(runtime_id, runtime_id),)
        if operation == "update-package":
            package_name = _required_str(request, "packageName")
            if package_name.lower() in _PYTORCH_PACKAGES:
                return self._pytorch_runtime_items()
            return (self._package_update_item(package_name, package_name),)
        if operation == "uninstall-package":
            package_name = _required_str(request, "packageName")
            return (self._package_uninstall_item(package_name),)
        raise BackendHttpError(
            message=f"Maintenance planning is not supported for {operation}.",
            status=400,
            code="unsupported-maintenance-plan-operation",
        )

    def _pytorch_runtime_items(self) -> tuple[MaintenancePlanItem, ...]:
        """Build a PyTorch runtime item and required compatibility follow-ups."""

        parent_id = self._store.next_item_id()
        items = [
            MaintenancePlanItem(
                item_id=parent_id,
                operation=EnvironmentOperationKind.UPDATE_RUNTIME.value,
                title="Update PyTorch runtime",
                target=MaintenancePlanTarget(
                    kind="runtime-family",
                    target_id="pytorch",
                    display_name="PyTorch runtime",
                ),
                requested=MaintenancePlanRequest(
                    source=MaintenancePlanRequestSource.USER,
                    package_name="torch",
                ),
                generated=False,
                generated_by_item_id=None,
                relationship=MaintenancePlanRelationship.USER_REQUESTED,
                affected_packages=_PYTORCH_PACKAGES,
                install_requirements=_PYTORCH_PACKAGES,
                requires_comfy_stop=True,
                requires_comfy_restart=True,
                locked_relative_order=False,
                can_remove=True,
                can_reorder=True,
                warnings=(
                    MaintenancePlanIssue(
                        code="restart-required",
                        message="PyTorch updates require restarting Comfy.",
                        item_id=parent_id,
                    ),
                ),
                blockers=(),
            )
        ]
        installed_packages = {
            package.normalized_name for package in self._inventory.list_packages().packages
        }
        if _has_triton_runtime(installed_packages):
            items.append(
                self._compatibility_follow_up(
                    parent_id=parent_id,
                    package_name=_TRITON_PACKAGE,
                    install_requirement=_triton_install_requirement(),
                    title="Reinstall Triton",
                )
            )
        if _SAGEATTENTION_PACKAGE in installed_packages:
            items.append(
                self._compatibility_follow_up(
                    parent_id=parent_id,
                    package_name=_SAGEATTENTION_PACKAGE,
                    install_requirement=_SAGEATTENTION_PACKAGE,
                    title="Reinstall SageAttention",
                )
            )
        return tuple(items)

    def _compatibility_follow_up(
        self,
        *,
        parent_id: str,
        package_name: str,
        install_requirement: str,
        title: str,
    ) -> MaintenancePlanItem:
        """Build one required runtime compatibility follow-up item."""

        item_id = self._store.next_item_id()
        return MaintenancePlanItem(
            item_id=item_id,
            operation="reinstall-package",
            title=title,
            target=MaintenancePlanTarget(
                kind="package",
                target_id=package_name,
                display_name=package_name,
            ),
            requested=MaintenancePlanRequest(
                source=MaintenancePlanRequestSource.BACKEND_POLICY,
                package_name=package_name,
            ),
            generated=True,
            generated_by_item_id=parent_id,
            relationship=MaintenancePlanRelationship.REQUIRED_COMPATIBILITY_FOLLOW_UP,
            affected_packages=(package_name,),
            install_requirements=(install_requirement,),
            requires_comfy_stop=True,
            requires_comfy_restart=True,
            locked_relative_order=True,
            can_remove=False,
            can_reorder=False,
            warnings=(
                MaintenancePlanIssue(
                    code="runtime-compatibility",
                    message="Required by PyTorch update.",
                    item_id=item_id,
                ),
            ),
            blockers=(),
        )

    def _package_update_item(
        self,
        package_name: str,
        install_requirement: str,
    ) -> MaintenancePlanItem:
        """Build one package update item."""

        item_id = self._store.next_item_id()
        return MaintenancePlanItem(
            item_id=item_id,
            operation=EnvironmentOperationKind.UPDATE_PACKAGE.value,
            title=f"Update {package_name}",
            target=MaintenancePlanTarget(
                kind="package",
                target_id=package_name,
                display_name=package_name,
            ),
            requested=MaintenancePlanRequest(
                source=MaintenancePlanRequestSource.USER,
                package_name=package_name,
            ),
            generated=False,
            generated_by_item_id=None,
            relationship=MaintenancePlanRelationship.USER_REQUESTED,
            affected_packages=(package_name,),
            install_requirements=(install_requirement,),
            requires_comfy_stop=True,
            requires_comfy_restart=True,
            locked_relative_order=False,
            can_remove=True,
            can_reorder=True,
            warnings=(
                MaintenancePlanIssue(
                    code="restart-may-be-required",
                    message="Updating this package may require restarting Comfy.",
                    item_id=item_id,
                ),
            ),
            blockers=(),
        )

    def _package_uninstall_item(self, package_name: str) -> MaintenancePlanItem:
        """Build one package uninstall item."""

        item_id = self._store.next_item_id()
        return MaintenancePlanItem(
            item_id=item_id,
            operation=EnvironmentOperationKind.UNINSTALL_PACKAGE.value,
            title=f"Uninstall {package_name}",
            target=MaintenancePlanTarget(
                kind="package",
                target_id=package_name,
                display_name=package_name,
            ),
            requested=MaintenancePlanRequest(
                source=MaintenancePlanRequestSource.USER,
                package_name=package_name,
            ),
            generated=False,
            generated_by_item_id=None,
            relationship=MaintenancePlanRelationship.USER_REQUESTED,
            affected_packages=(package_name,),
            install_requirements=(),
            requires_comfy_stop=True,
            requires_comfy_restart=True,
            locked_relative_order=False,
            can_remove=True,
            can_reorder=True,
            warnings=(
                MaintenancePlanIssue(
                    code="dependency-risk",
                    message=(
                        "Removing a Python package can break ComfyUI or installed custom nodes."
                    ),
                    item_id=item_id,
                ),
            ),
            blockers=(),
        )

    def _validate_and_persist(
        self,
        record: MaintenancePlanRecord,
    ) -> MaintenancePlanRecord:
        """Normalize the stored order and persist it when needed."""

        normalized, adjusted = _normalize_order(record.items)
        if adjusted:
            return self._store.save(normalized)
        return record

    def _to_plan(
        self,
        record: MaintenancePlanRecord,
        *,
        last_validation_message: str | None,
    ) -> MaintenancePlan:
        """Build the public validated plan snapshot."""

        warnings = tuple(warning for item in record.items for warning in item.warnings)
        blockers = tuple(blocker for item in record.items for blocker in item.blockers)
        if record.items and not self._package_mutation_supported:
            blockers = (
                *blockers,
                MaintenancePlanIssue(
                    code="package-mutation-unavailable",
                    message=(
                        "Package execution is not available in this BackEnd build. "
                        "The plan can be reviewed but not applied."
                    ),
                ),
            )
        affected_packages = {package for item in record.items for package in item.affected_packages}
        summary = MaintenancePlanSummary(
            item_count=len(record.items),
            affected_package_count=len(affected_packages),
            requires_comfy_stop=any(item.requires_comfy_stop for item in record.items),
            requires_comfy_restart=any(item.requires_comfy_restart for item in record.items),
            applyable=bool(record.items) and not blockers,
        )
        return MaintenancePlan(
            plan_id=record.plan_id,
            environment_id=record.environment_id,
            revision=record.revision,
            items=record.items,
            execution_phases=_execution_phases(record.items),
            warnings=warnings,
            blockers=blockers,
            summary=summary,
            last_validation_message=last_validation_message,
        )


def _execution_phases(
    items: tuple[MaintenancePlanItem, ...],
) -> tuple[MaintenanceExecutionPhase, ...]:
    """Return one execution phase for currently planned package work."""

    if not items:
        return ()
    return (
        MaintenanceExecutionPhase(
            phase_id="phase-1",
            title="Package maintenance",
            item_ids=tuple(item.item_id for item in items),
            requires_comfy_stop=any(item.requires_comfy_stop for item in items),
            requires_comfy_restart=any(item.requires_comfy_restart for item in items),
        ),
    )


def _normalize_order(
    items: tuple[MaintenancePlanItem, ...],
) -> tuple[tuple[MaintenancePlanItem, ...], bool]:
    """Return order with generated follow-ups placed after their parent."""

    ordered: list[MaintenancePlanItem] = []
    added: set[str] = set()
    children_by_parent: dict[str, list[MaintenancePlanItem]] = {}
    for item in items:
        if item.generated_by_item_id is not None:
            children_by_parent.setdefault(item.generated_by_item_id, []).append(item)
    for item in items:
        if item.item_id in added or item.generated_by_item_id is not None:
            continue
        ordered.append(item)
        added.add(item.item_id)
        for child in children_by_parent.get(item.item_id, ()):
            ordered.append(child)
            added.add(child.item_id)
    for item in items:
        if item.item_id not in added:
            ordered.append(item)
            added.add(item.item_id)
    normalized = tuple(ordered)
    return (normalized, normalized != items)


def _contains_equivalent_item(
    items: tuple[MaintenancePlanItem, ...],
    new_item: MaintenancePlanItem,
) -> bool:
    """Return whether an equivalent operation target is already planned."""

    return any(
        item.operation == new_item.operation
        and item.target.kind == new_item.target.kind
        and item.target.target_id == new_item.target.target_id
        for item in items
    )


def _find_item(
    items: tuple[MaintenancePlanItem, ...],
    item_id: str,
) -> MaintenancePlanItem | None:
    """Return one item by id."""

    for item in items:
        if item.item_id == item_id:
            return item
    return None


def _require_revision(record: MaintenancePlanRecord, revision: int) -> None:
    """Reject stale maintenance-plan mutation requests."""

    if record.revision != revision:
        raise BackendHttpError(
            message="Maintenance plan changed. Refresh before continuing.",
            status=409,
            code="stale-maintenance-plan-revision",
        )


def _required_str(request: dict[str, object], key: str) -> str:
    """Read one required non-empty string field."""

    value = _optional_str(request, key)
    if value is None:
        raise BackendHttpError(
            message=f"'{key}' is required.",
            status=400,
            code="invalid-maintenance-plan-request",
        )
    return value


def _optional_str(request: dict[str, object], key: str) -> str | None:
    """Read one optional non-empty string field."""

    value = request.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _triton_install_requirement() -> str:
    """Return the pip requirement used for Triton on this platform."""

    if sys.platform == "win32":
        return _TRITON_WINDOWS_PACKAGE
    return "triton"


def _has_triton_runtime(installed_packages: set[str]) -> bool:
    """Return whether any installed distribution provides the Triton runtime."""

    return bool({_TRITON_PACKAGE, _TRITON_WINDOWS_PACKAGE} & installed_packages)


def _add_message(items: tuple[MaintenancePlanItem, ...]) -> str:
    """Return a short validation message for newly added items."""

    if len(items) > 1:
        return "Planned item added with required compatibility follow-ups."
    return "Planned item added."

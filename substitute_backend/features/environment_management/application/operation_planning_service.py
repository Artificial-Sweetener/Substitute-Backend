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
"""Plan environment mutations without executing them."""

from __future__ import annotations

import sys
from uuid import uuid4

from substitute_backend.api.errors import BackendHttpError
from substitute_backend.features.environment_management.domain.operations import (
    EnvironmentOperationKind,
    EnvironmentOperationPlan,
)


class OperationPlanningService:
    """Build user-reviewable plans for supported environment operations."""

    def plan(self, request: dict[str, object]) -> EnvironmentOperationPlan:
        """Return a typed plan for one requested operation."""

        operation = _operation(request)
        if operation is EnvironmentOperationKind.UPDATE_COMPONENT:
            return self._plan_update_component(request)
        if operation is EnvironmentOperationKind.UNINSTALL_PACKAGE:
            package_name = _required_str(request, "packageName")
            return _package_plan(
                operation=operation,
                package_names=(package_name,),
                summary=f"Uninstall {package_name}.",
                warning=(
                    "Removing a Python package can break ComfyUI or installed custom nodes. "
                    "Review ownership before applying this operation."
                ),
                command=(sys.executable, "-m", "pip", "uninstall", package_name),
            )
        if operation is EnvironmentOperationKind.UPDATE_PACKAGE:
            package_name = _required_str(request, "packageName")
            return _package_plan(
                operation=operation,
                package_names=(package_name,),
                summary=f"Update {package_name}.",
                warning="Updating this package may require restarting Comfy.",
                command=(sys.executable, "-m", "pip", "install", "--upgrade", package_name),
            )
        raise BackendHttpError(
            message=f"Operation planning is not supported for {operation.value}.",
            status=400,
            code="unsupported-operation-plan",
        )

    def _plan_update_component(
        self,
        request: dict[str, object],
    ) -> EnvironmentOperationPlan:
        """Plan one supported component update."""

        component_id = _required_str(request, "componentId")
        if component_id == "pytorch":
            return self._plan_pytorch_update(request)
        if component_id == "triton":
            return _package_plan(
                operation=EnvironmentOperationKind.UPDATE_COMPONENT,
                package_names=("triton",),
                summary="Update Triton.",
                warning="Triton updates may require restarting Comfy.",
                command=(sys.executable, "-m", "pip", "install", "--upgrade", "triton"),
            )
        if component_id == "sageattention":
            return _package_plan(
                operation=EnvironmentOperationKind.UPDATE_COMPONENT,
                package_names=("sageattention",),
                summary="Update SageAttention.",
                warning="SageAttention updates may require restarting Comfy.",
                command=(
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "sageattention",
                ),
            )
        raise BackendHttpError(
            message=f"Component planning is not supported for {component_id}.",
            status=400,
            code="unsupported-component-plan",
        )

    def _plan_pytorch_update(
        self,
        request: dict[str, object],
    ) -> EnvironmentOperationPlan:
        """Plan one supported PyTorch package update."""

        channel = _optional_str(request, "channel") or "stable"
        packages = ("torch", "torchvision", "torchaudio")
        command: tuple[str, ...]
        if channel == "nightly":
            command = (
                sys.executable,
                "-m",
                "pip",
                "install",
                "--pre",
                "--upgrade",
                *packages,
            )
            summary = "Update PyTorch packages to the latest nightly builds."
        elif channel == "stable":
            command = (
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                *packages,
            )
            summary = "Update PyTorch packages to the latest stable builds."
        else:
            raise BackendHttpError(
                message=f"PyTorch channel is not supported: {channel}.",
                status=400,
                code="unsupported-pytorch-channel",
            )
        return _package_plan(
            operation=EnvironmentOperationKind.UPDATE_COMPONENT,
            package_names=packages,
            summary=summary,
            warning="PyTorch updates require restarting Comfy before generation resumes.",
            command=command,
        )


def _package_plan(
    *,
    operation: EnvironmentOperationKind,
    package_names: tuple[str, ...],
    summary: str,
    warning: str,
    command: tuple[str, ...],
) -> EnvironmentOperationPlan:
    """Build a common restart-required package operation plan."""

    return EnvironmentOperationPlan(
        plan_id=f"envplan-{uuid4().hex}",
        operation=operation,
        affected_packages=package_names,
        summary=summary,
        warnings=(warning,),
        requires_comfy_stop=True,
        requires_restart=True,
        requires_detached_runner=True,
        display_commands=(command,),
    )


def _operation(request: dict[str, object]) -> EnvironmentOperationKind:
    """Read the requested operation kind."""

    raw_operation = _required_str(request, "operation")
    try:
        return EnvironmentOperationKind(raw_operation)
    except ValueError as error:
        raise BackendHttpError(
            message=f"Unsupported environment operation: {raw_operation}",
            status=400,
            code="unsupported-environment-operation",
        ) from error


def _required_str(request: dict[str, object], key: str) -> str:
    """Read one required request string field."""

    value = _optional_str(request, key)
    if value is None:
        raise BackendHttpError(
            message=f"'{key}' is required.",
            status=400,
            code="invalid-operation-plan-request",
        )
    return value


def _optional_str(request: dict[str, object], key: str) -> str | None:
    """Read one optional request string field."""

    value = request.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None

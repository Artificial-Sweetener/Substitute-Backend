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
"""Resolve the versioned API published by the loaded SugarCubes extension."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

SUGARCUBES_HOST_API_MODULE = "sugarcubes.host_api"
SUPPORTED_SUGARCUBES_HOST_API_VERSION = 1


class SugarCubesHostApi(Protocol):
    """Describe the cross-extension surface owned and published by SugarCubes."""

    HOST_API_VERSION: int

    def active_backend_services(self) -> object | None:
        """Return the service graph already created by SugarCubes."""

    def register_cube_output_observer(self, observer: object) -> None:
        """Register one cube-output observer."""

    def unregister_cube_output_observer(self, observer: object) -> None:
        """Unregister one cube-output observer."""


class SugarCubesHostApiResolutionStatus(StrEnum):
    """Describe whether the public SugarCubes API can be consumed now."""

    RESOLVED = "resolved"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SugarCubesHostApiResolution:
    """Return a typed API resolution or its actionable failure reason."""

    status: SugarCubesHostApiResolutionStatus
    message: str
    api: SugarCubesHostApi | None = None


class SugarCubesHostApiResolver:
    """Resolve SugarCubes without importing its package under a second identity."""

    def resolve(self) -> SugarCubesHostApiResolution:
        """Return the published API after validating its complete versioned surface."""

        module = sys.modules.get(SUGARCUBES_HOST_API_MODULE)
        if module is None:
            return SugarCubesHostApiResolution(
                status=SugarCubesHostApiResolutionStatus.PENDING,
                message="SugarCubes has not published its host API yet.",
            )

        version = getattr(module, "HOST_API_VERSION", None)
        if version != SUPPORTED_SUGARCUBES_HOST_API_VERSION:
            return SugarCubesHostApiResolution(
                status=SugarCubesHostApiResolutionStatus.UNAVAILABLE,
                message=(
                    "SugarCubes host API version "
                    f"{version!r} is not supported; expected "
                    f"{SUPPORTED_SUGARCUBES_HOST_API_VERSION}."
                ),
            )
        missing_operation = _missing_operation(module)
        if missing_operation is not None:
            return SugarCubesHostApiResolution(
                status=SugarCubesHostApiResolutionStatus.UNAVAILABLE,
                message=f"SugarCubes host API does not expose {missing_operation}.",
            )
        return SugarCubesHostApiResolution(
            status=SugarCubesHostApiResolutionStatus.RESOLVED,
            message="SugarCubes host API resolved.",
            api=cast(SugarCubesHostApi, module),
        )


def _missing_operation(module: object) -> str | None:
    """Return the first absent operation required by all BackEnd consumers."""

    for name in (
        "active_backend_services",
        "register_cube_output_observer",
        "unregister_cube_output_observer",
    ):
        if not callable(getattr(module, name, None)):
            return name
    return None

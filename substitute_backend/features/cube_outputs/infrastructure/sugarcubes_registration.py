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
"""Own idempotent Substitute observer registration with SugarCubes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from .sugarcubes_observer_hook import (
    SugarCubesHookResolutionStatus,
    SugarCubesObserverHookResolver,
)


class CubeOutputRegistrationStatus(StrEnum):
    """Describe one attempt to attach Substitute to SugarCubes output events."""

    REGISTERED = "registered"
    ALREADY_REGISTERED = "already_registered"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True)
class CubeOutputRegistrationResult:
    """Return a typed, logged result for one observer registration attempt."""

    status: CubeOutputRegistrationStatus
    message: str


class SugarCubesCubeOutputRegistration:
    """Own idempotent registration with SugarCubes' observer registry."""

    def __init__(
        self,
        *,
        hook_resolver: SugarCubesObserverHookResolver,
        observer: object,
        logger: logging.Logger,
    ) -> None:
        """Initialize registration with a lazy hook resolver."""

        self._hook_resolver = hook_resolver
        self._observer = observer
        self._logger = logger
        self._registered_hook_identity: str | None = None

    def register(self) -> CubeOutputRegistrationResult:
        """Register the Substitute observer when the canonical hook exists."""

        if self._registered_hook_identity is not None:
            self._logger.debug(
                "SugarCubes cube-output observer already registered",
                extra={"hook_identity": self._registered_hook_identity},
            )
            return CubeOutputRegistrationResult(
                status=CubeOutputRegistrationStatus.ALREADY_REGISTERED,
                message="SugarCubes cube-output observer is already registered.",
            )

        resolution = self._hook_resolver.resolve()
        if resolution.status is SugarCubesHookResolutionStatus.PENDING:
            self._logger.debug(
                "SugarCubes cube-output observer registration pending",
                extra={"reason": resolution.message},
            )
            return CubeOutputRegistrationResult(
                status=CubeOutputRegistrationStatus.PENDING,
                message=resolution.message,
            )
        if resolution.status is SugarCubesHookResolutionStatus.UNAVAILABLE:
            self._logger.warning(
                "SugarCubes cube-output observer registration unavailable",
                extra={"reason": resolution.message},
            )
            return CubeOutputRegistrationResult(
                status=CubeOutputRegistrationStatus.UNAVAILABLE,
                message=resolution.message,
            )
        hook = resolution.hook
        if hook is None:
            message = "SugarCubes hook resolution succeeded without a hook."
            self._logger.error(message)
            return CubeOutputRegistrationResult(
                status=CubeOutputRegistrationStatus.FAILED,
                message=message,
            )
        try:
            hook.register_cube_output_observer(self._observer)
        except Exception:
            self._logger.exception(
                "Failed to register SugarCubes cube-output observer",
                extra={"hook_identity": hook.identity},
            )
            return CubeOutputRegistrationResult(
                status=CubeOutputRegistrationStatus.FAILED,
                message="Failed to register SugarCubes cube-output observer.",
            )
        self._registered_hook_identity = hook.identity
        self._logger.info(
            "SugarCubes cube-output observer registered",
            extra={"hook_identity": hook.identity},
        )
        return CubeOutputRegistrationResult(
            status=CubeOutputRegistrationStatus.REGISTERED,
            message="SugarCubes cube-output observer registered.",
        )

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
"""Adapt the public SugarCubes host API to cube-output observer registration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from substitute_backend.infrastructure.sugarcubes_host_api import (
    SugarCubesHostApi,
    SugarCubesHostApiResolutionStatus,
    SugarCubesHostApiResolver,
)


class SugarCubesHookResolutionStatus(StrEnum):
    """Describe the outcome of resolving SugarCubes' observer hook."""

    RESOLVED = "resolved"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


class SugarCubesObserverHook(Protocol):
    """Describe the observer operations consumed by registration orchestration."""

    @property
    def identity(self) -> str:
        """Return the process-local hook identity used for idempotency."""

    def register_cube_output_observer(self, observer: object) -> None:
        """Register one SugarCubes cube-output observer."""

    def unregister_cube_output_observer(self, observer: object) -> None:
        """Unregister one SugarCubes cube-output observer."""


@dataclass(frozen=True)
class SugarCubesHookResolution:
    """Return a resolved hook or a typed reason registration cannot proceed."""

    status: SugarCubesHookResolutionStatus
    message: str
    hook: SugarCubesObserverHook | None = None


class _HostApiObserverHook:
    """Expose observer registration through the validated SugarCubes host API."""

    def __init__(self, api: SugarCubesHostApi) -> None:
        """Store the public API that owns the observer registry."""

        self._api = api

    @property
    def identity(self) -> str:
        """Return the stable public API identity used for idempotency."""

        return "sugarcubes.host_api:v1"

    def register_cube_output_observer(self, observer: object) -> None:
        """Register one observer through SugarCubes' public API."""

        self._api.register_cube_output_observer(observer)

    def unregister_cube_output_observer(self, observer: object) -> None:
        """Unregister one observer through SugarCubes' public API."""

        self._api.unregister_cube_output_observer(observer)


class SugarCubesObserverHookResolver:
    """Resolve the observer hook through the shared SugarCubes API boundary."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        host_api_resolver: SugarCubesHostApiResolver | None = None,
    ) -> None:
        """Configure logging and the shared public-API resolver."""

        self._logger = logger
        self._host_api_resolver = host_api_resolver or SugarCubesHostApiResolver()

    def resolve(self) -> SugarCubesHookResolution:
        """Return a public observer hook or a retryable/terminal resolution."""

        resolution = self._host_api_resolver.resolve()
        if resolution.status is SugarCubesHostApiResolutionStatus.PENDING:
            self._logger.debug(
                "SugarCubes observer hook pending",
                extra={"reason": resolution.message},
            )
            return SugarCubesHookResolution(
                status=SugarCubesHookResolutionStatus.PENDING,
                message=resolution.message,
            )
        if resolution.status is SugarCubesHostApiResolutionStatus.UNAVAILABLE:
            self._logger.warning(
                "SugarCubes observer hook unavailable",
                extra={"reason": resolution.message},
            )
            return SugarCubesHookResolution(
                status=SugarCubesHookResolutionStatus.UNAVAILABLE,
                message=resolution.message,
            )
        api = resolution.api
        if api is None:
            message = "SugarCubes host API resolved without an API object."
            self._logger.error(message)
            return SugarCubesHookResolution(
                status=SugarCubesHookResolutionStatus.UNAVAILABLE,
                message=message,
            )
        return SugarCubesHookResolution(
            status=SugarCubesHookResolutionStatus.RESOLVED,
            message="SugarCubes observer hook resolved.",
            hook=_HostApiObserverHook(api),
        )

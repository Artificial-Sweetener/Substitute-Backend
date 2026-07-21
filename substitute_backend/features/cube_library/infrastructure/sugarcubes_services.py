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
"""Own lazy access to the service graph published by SugarCubes."""

from __future__ import annotations

from collections.abc import Callable

from substitute_backend.api.errors import BackendHttpError
from substitute_backend.infrastructure.sugarcubes_host_api import (
    SugarCubesHostApiResolutionStatus,
    SugarCubesHostApiResolver,
)

SugarCubesServicesLoader = Callable[[], object]


class SugarCubesServiceProvider:
    """Cache the active SugarCubes graph without constructing a competing graph."""

    def __init__(
        self,
        *,
        resolver: SugarCubesHostApiResolver | None = None,
        services_loader: SugarCubesServicesLoader | None = None,
        on_loaded: Callable[[object], None] | None = None,
    ) -> None:
        """Configure public API resolution and an isolated test boundary."""

        self._resolver = resolver or SugarCubesHostApiResolver()
        self._services_loader = services_loader
        self._on_loaded = on_loaded
        self._services: object | None = None

    @property
    def loaded_services(self) -> object | None:
        """Return cached services without forcing SugarCubes discovery."""

        return self._services

    def services(self) -> object:
        """Return SugarCubes' active graph or raise a typed availability error."""

        if self._services is not None:
            return self._services
        if self._services_loader is not None:
            services = self._services_loader()
        else:
            resolution = self._resolver.resolve()
            if resolution.status is not SugarCubesHostApiResolutionStatus.RESOLVED:
                raise BackendHttpError(
                    message=resolution.message,
                    status=503,
                    code="sugarcubes-unavailable",
                )
            api = resolution.api
            if api is None:
                raise BackendHttpError(
                    message="SugarCubes host API resolved without an API object.",
                    status=503,
                    code="sugarcubes-unavailable",
                )
            services = api.active_backend_services()
            if services is None:
                raise BackendHttpError(
                    message="SugarCubes has not published its active services yet.",
                    status=503,
                    code="sugarcubes-unavailable",
                )
        self._services = services
        if self._on_loaded is not None:
            self._on_loaded(services)
        return services

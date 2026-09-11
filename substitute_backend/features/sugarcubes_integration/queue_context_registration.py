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
"""Own required Substitute queue-context registration with SugarCubes."""

from __future__ import annotations

import logging

from substitute_backend.features.prompt_queue.infrastructure.sugarcubes_queue_context import (
    SugarCubesQueueContextObserver,
)
from substitute_backend.infrastructure.sugarcubes_host_api import (
    SugarCubesHostApiResolutionStatus,
    SugarCubesHostApiResolver,
)


class SugarCubesQueueContextRegistration:
    """Attach BackEnd context capture to SugarCubes exactly once per process."""

    def __init__(
        self,
        *,
        observer: SugarCubesQueueContextObserver,
        logger: logging.Logger,
        host_api_resolver: SugarCubesHostApiResolver | None = None,
    ) -> None:
        """Configure lazy public-API resolution and structured diagnostics."""

        self._observer = observer
        self._logger = logger
        self._host_api_resolver = host_api_resolver or SugarCubesHostApiResolver()
        self._registered = False

    def register(self) -> None:
        """Register the required pre-queue observer when SugarCubes is available."""

        if self._registered:
            return
        resolution = self._host_api_resolver.resolve()
        if resolution.status is SugarCubesHostApiResolutionStatus.PENDING:
            self._logger.debug(
                "SugarCubes queue-context registration pending",
                extra={"reason": resolution.message},
            )
            return
        if resolution.status is SugarCubesHostApiResolutionStatus.UNAVAILABLE:
            self._logger.warning(
                "SugarCubes queue-context registration unavailable",
                extra={"reason": resolution.message},
            )
            return
        api = resolution.api
        if api is None:
            raise RuntimeError("SugarCubes host API resolved without an API object.")
        api.register_validated_queue_observer(
            self._observer.on_validated_queue,
            required=True,
        )
        self._registered = True
        self._logger.info("SugarCubes queue-context observer registered")

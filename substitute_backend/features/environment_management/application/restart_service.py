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
"""Restart use case for the active Comfy host process."""

from __future__ import annotations

import asyncio
import logging

from substitute_backend.api.errors import BackendHttpError
from substitute_backend.features.environment_management.application.job_service import (
    JobService,
)
from substitute_backend.features.environment_management.domain.jobs import (
    EnvironmentJob,
    EnvironmentJobStatus,
)
from substitute_backend.features.environment_management.domain.operations import (
    EnvironmentOperationKind,
)
from substitute_backend.features.environment_management.infrastructure.restart_coordinator import (
    RestartCoordinator,
)


class RestartService:
    """Queue and execute Comfy restart jobs."""

    def __init__(
        self,
        jobs: JobService,
        coordinator: RestartCoordinator,
        logger: logging.Logger,
    ) -> None:
        """Initialize the restart service."""

        self._jobs = jobs
        self._coordinator = coordinator
        self._logger = logger
        self._restart_tasks: set[asyncio.Task[None]] = set()

    def restart(self) -> EnvironmentJob:
        """Queue a restart job and schedule process replacement."""

        support = self._coordinator.support()
        if not support.supported:
            raise BackendHttpError(
                message=support.unavailable_reason or "Comfy restart is not supported.",
                status=409,
                code="restart-unsupported",
            )
        job = self._jobs.create(
            EnvironmentOperationKind.RESTART_COMFY,
            "Comfy restart queued.",
        )
        task = asyncio.create_task(self._run_restart(job))
        self._restart_tasks.add(task)
        task.add_done_callback(self._restart_tasks.discard)
        return job

    async def _run_restart(self, job: EnvironmentJob) -> None:
        """Persist restart progress, then replace this process."""

        running = self._jobs.update(
            job,
            status=EnvironmentJobStatus.RUNNING,
            message="Comfy restart is starting.",
        )
        await asyncio.sleep(0.25)
        waiting = self._jobs.update(
            running,
            status=EnvironmentJobStatus.WAITING_FOR_RESTART,
            message="Comfy is restarting.",
        )
        try:
            self._coordinator.restart_process()
        except Exception as error:
            self._logger.exception(
                "restart process replacement failed",
                extra={"operation": "restart-comfy", "job_id": waiting.job_id},
            )
            self._jobs.update(
                waiting,
                status=EnvironmentJobStatus.FAILED,
                message="Comfy restart failed.",
                error=repr(error),
            )

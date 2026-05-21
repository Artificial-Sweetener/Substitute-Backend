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
"""Durable environment job orchestration use cases."""

from __future__ import annotations

import os
from dataclasses import replace
from uuid import uuid4

from substitute_backend.features.environment_management.domain.jobs import (
    EnvironmentJob,
    EnvironmentJobEvent,
    EnvironmentJobStatus,
)
from substitute_backend.features.environment_management.domain.operations import (
    EnvironmentOperationKind,
)
from substitute_backend.features.environment_management.infrastructure.job_store import (
    JobStore,
)
from substitute_backend.features.model_metadata.infrastructure.time_utils import utc_now


class JobService:
    """Create, persist, and recover environment operation jobs."""

    def __init__(self, store: JobStore) -> None:
        """Initialize the service with a durable job store."""

        self._store = store

    def create(self, operation: EnvironmentOperationKind, message: str) -> EnvironmentJob:
        """Create and persist a queued environment job."""

        timestamp = _now()
        job = EnvironmentJob(
            job_id=f"envjob-{uuid4().hex}",
            operation=operation,
            status=EnvironmentJobStatus.QUEUED,
            created_at=timestamp,
            updated_at=timestamp,
            message=message,
            host_process_id=os.getpid(),
            events=(
                EnvironmentJobEvent(
                    created_at=timestamp,
                    status=EnvironmentJobStatus.QUEUED,
                    message=message,
                ),
            ),
        )
        return self._store.save(job)

    def update(
        self,
        job: EnvironmentJob,
        *,
        status: EnvironmentJobStatus,
        message: str,
        error: str | None = None,
    ) -> EnvironmentJob:
        """Persist a job state transition."""

        timestamp = _now()
        started_at = job.started_at
        completed_at = job.completed_at
        if status is EnvironmentJobStatus.RUNNING and started_at is None:
            started_at = timestamp
        if status in {
            EnvironmentJobStatus.SUCCEEDED,
            EnvironmentJobStatus.FAILED,
            EnvironmentJobStatus.CANCELLED,
        }:
            completed_at = timestamp
        updated = replace(
            job,
            status=status,
            updated_at=timestamp,
            message=message,
            started_at=started_at,
            completed_at=completed_at,
            error=error,
            events=(
                *job.events,
                EnvironmentJobEvent(
                    created_at=timestamp,
                    status=status,
                    message=message,
                ),
            )[-20:],
        )
        return self._store.save(updated)

    def get(self, job_id: str) -> EnvironmentJob | None:
        """Return a job, recovering restart jobs after a process replacement."""

        job = self._store.get(job_id)
        if job is None:
            return None
        if (
            job.operation is EnvironmentOperationKind.RESTART_COMFY
            and job.status is EnvironmentJobStatus.WAITING_FOR_RESTART
            and job.host_process_id != os.getpid()
        ):
            return self.update(
                job,
                status=EnvironmentJobStatus.SUCCEEDED,
                message="Comfy restarted and is accepting backend requests.",
            )
        return job


def _now() -> str:
    """Return the current timestamp in backend API format."""

    return utc_now()

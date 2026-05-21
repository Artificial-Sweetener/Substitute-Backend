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
"""Durable job contracts for environment management operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from substitute_backend.api.serialization import JsonObject
from substitute_backend.features.environment_management.domain.operations import (
    EnvironmentOperationKind,
)


class EnvironmentJobStatus(StrEnum):
    """Identify lifecycle state for environment operations."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_RESTART = "waiting-for-restart"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class EnvironmentJobEvent:
    """Describe one user-visible environment job event."""

    created_at: str
    status: EnvironmentJobStatus
    message: str

    def to_payload(self) -> JsonObject:
        """Return the job event payload."""

        return {
            "createdAt": self.created_at,
            "status": self.status.value,
            "message": self.message,
        }


@dataclass(frozen=True)
class EnvironmentJob:
    """Describe one durable environment management job."""

    job_id: str
    operation: EnvironmentOperationKind
    status: EnvironmentJobStatus
    created_at: str
    updated_at: str
    message: str
    host_process_id: int
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    events: tuple[EnvironmentJobEvent, ...] = ()

    def to_payload(self) -> JsonObject:
        """Return the environment job payload."""

        payload: JsonObject = {
            "jobId": self.job_id,
            "operation": self.operation.value,
            "status": self.status.value,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "message": self.message,
            "hostProcessId": self.host_process_id,
            "events": [event.to_payload() for event in self.events],
        }
        if self.started_at is not None:
            payload["startedAt"] = self.started_at
        if self.completed_at is not None:
            payload["completedAt"] = self.completed_at
        if self.error is not None:
            payload["error"] = self.error
        return payload

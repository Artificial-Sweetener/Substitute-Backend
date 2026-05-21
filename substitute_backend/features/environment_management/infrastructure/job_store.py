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
"""JSON-backed durable store for environment management jobs."""

from __future__ import annotations

import json
from pathlib import Path

from substitute_backend.features.environment_management.domain.jobs import (
    EnvironmentJob,
    EnvironmentJobEvent,
    EnvironmentJobStatus,
)
from substitute_backend.features.environment_management.domain.operations import (
    EnvironmentOperationKind,
)


class JobStore:
    """Persist bounded environment job records in the backend cache."""

    def __init__(self, path: Path, *, max_jobs: int = 50) -> None:
        """Initialize the job store path and retention policy."""

        self._path = path
        self._max_jobs = max_jobs
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, job: EnvironmentJob) -> EnvironmentJob:
        """Persist one job and return it."""

        jobs = [existing for existing in self.list_jobs() if existing.job_id != job.job_id]
        jobs.append(job)
        jobs = jobs[-self._max_jobs :]
        payload = {"jobs": [self._job_to_record(existing) for existing in jobs]}
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return job

    def get(self, job_id: str) -> EnvironmentJob | None:
        """Return one persisted job by id."""

        for job in self.list_jobs():
            if job.job_id == job_id:
                return job
        return None

    def list_jobs(self) -> list[EnvironmentJob]:
        """Return persisted jobs in stored order."""

        if not self._path.exists():
            return []
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw_jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(raw_jobs, list):
            return []
        jobs: list[EnvironmentJob] = []
        for raw_job in raw_jobs:
            if not isinstance(raw_job, dict):
                continue
            job = _record_to_job(raw_job)
            if job is not None:
                jobs.append(job)
        return jobs

    def _job_to_record(self, job: EnvironmentJob) -> dict[str, object]:
        """Return a JSON record for one job."""

        return {
            "jobId": job.job_id,
            "operation": job.operation.value,
            "status": job.status.value,
            "createdAt": job.created_at,
            "updatedAt": job.updated_at,
            "message": job.message,
            "hostProcessId": job.host_process_id,
            "startedAt": job.started_at,
            "completedAt": job.completed_at,
            "error": job.error,
            "events": [
                {
                    "createdAt": event.created_at,
                    "status": event.status.value,
                    "message": event.message,
                }
                for event in job.events
            ],
        }


def _record_to_job(record: dict[object, object]) -> EnvironmentJob | None:
    """Parse one persisted job record."""

    try:
        operation = EnvironmentOperationKind(str(record["operation"]))
        status = EnvironmentJobStatus(str(record["status"]))
        events = _parse_events(record.get("events"))
        host_process_id = record.get("hostProcessId")
        return EnvironmentJob(
            job_id=str(record["jobId"]),
            operation=operation,
            status=status,
            created_at=str(record["createdAt"]),
            updated_at=str(record["updatedAt"]),
            message=str(record["message"]),
            host_process_id=host_process_id if isinstance(host_process_id, int) else 0,
            started_at=_optional_str(record.get("startedAt")),
            completed_at=_optional_str(record.get("completedAt")),
            error=_optional_str(record.get("error")),
            events=events,
        )
    except (KeyError, ValueError):
        return None


def _parse_events(raw_events: object) -> tuple[EnvironmentJobEvent, ...]:
    """Parse persisted job event records."""

    if not isinstance(raw_events, list):
        return ()
    events: list[EnvironmentJobEvent] = []
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            continue
        try:
            events.append(
                EnvironmentJobEvent(
                    created_at=str(raw_event["createdAt"]),
                    status=EnvironmentJobStatus(str(raw_event["status"])),
                    message=str(raw_event["message"]),
                )
            )
        except (KeyError, ValueError):
            continue
    return tuple(events)


def _optional_str(value: object) -> str | None:
    """Return non-empty string values from persisted records."""

    if isinstance(value, str) and value.strip():
        return value
    return None

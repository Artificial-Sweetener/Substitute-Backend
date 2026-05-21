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
"""Background SHA256 fingerprint worker."""

from __future__ import annotations

import hashlib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from substitute_backend.features.model_metadata.domain.catalog import ModelFile
from substitute_backend.features.model_metadata.domain.fingerprints import (
    FingerprintJob,
    FingerprintJobEntry,
)
from substitute_backend.features.model_metadata.domain.statuses import JobStatus

from .fingerprint_cache import FileFreshness, FingerprintCache
from .time_utils import utc_now


@dataclass(frozen=True)
class FingerprintWorkItem:
    """Resolved model file and freshness data queued for hashing."""

    model_file: ModelFile
    freshness: FileFreshness


class FingerprintWorker:
    """Bounded background worker for model file SHA256 hashing."""

    def __init__(self, cache: FingerprintCache, max_workers: int = 1) -> None:
        """Initialize the worker with a cache and bounded concurrency."""

        self._cache = cache
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._jobs: dict[str, FingerprintJob] = {}

    def submit(self, items: tuple[FingerprintWorkItem, ...]) -> FingerprintJob:
        """Queue fingerprint work and return the initial job state."""

        job_id = uuid.uuid4().hex
        entries = tuple(
            FingerprintJobEntry(
                kind=item.model_file.kind,
                value=item.model_file.value,
                status=JobStatus.QUEUED,
            )
            for item in items
        )
        job = FingerprintJob(job_id=job_id, status=JobStatus.QUEUED, entries=entries)
        with self._lock:
            self._jobs[job_id] = job
        self._executor.submit(self._run_job, job_id, items)
        return job

    def get_job(self, job_id: str) -> FingerprintJob | None:
        """Return the current state for a background fingerprint job."""

        with self._lock:
            return self._jobs.get(job_id)

    def find_active_job_for(self, kind: str, value: str) -> FingerprintJob | None:
        """Return an active job already hashing a model entry."""

        with self._lock:
            for job in self._jobs.values():
                if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                    continue
                if any(entry.kind == kind and entry.value == value for entry in job.entries):
                    return job
        return None

    def shutdown(self) -> None:
        """Stop accepting new work and release worker threads."""

        self._executor.shutdown(wait=True)

    def _run_job(self, job_id: str, items: tuple[FingerprintWorkItem, ...]) -> None:
        """Compute SHA256 values for a job on a background thread."""

        self._set_job_status(job_id, JobStatus.RUNNING, ())
        results: list[FingerprintJobEntry] = []
        for item in items:
            try:
                sha256 = self._hash_file(item.model_file.path)
                fingerprint = self._cache.store_sha256(
                    item.freshness,
                    sha256=sha256,
                    computed_at=utc_now(),
                )
                results.append(
                    FingerprintJobEntry(
                        kind=item.model_file.kind,
                        value=item.model_file.value,
                        status=JobStatus.COMPLETE,
                        sha256=fingerprint.sha256,
                    )
                )
            except OSError as exc:
                results.append(
                    FingerprintJobEntry(
                        kind=item.model_file.kind,
                        value=item.model_file.value,
                        status=JobStatus.FAILED,
                        error=str(exc),
                    )
                )
        final_status = (
            JobStatus.FAILED
            if any(entry.status is JobStatus.FAILED for entry in results)
            else JobStatus.COMPLETE
        )
        self._set_job_status(job_id, final_status, tuple(results))

    def _set_job_status(
        self,
        job_id: str,
        status: JobStatus,
        entries: tuple[FingerprintJobEntry, ...],
    ) -> None:
        """Update a job status while preserving queued entries if needed."""

        with self._lock:
            current = self._jobs[job_id]
            self._jobs[job_id] = FingerprintJob(
                job_id=job_id,
                status=status,
                entries=entries or current.entries,
            )

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Compute SHA256 over the actual model file bytes."""

        digest = hashlib.sha256()
        with path.open("rb") as model_file:
            for block in iter(lambda: model_file.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest().upper()

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
"""Fingerprint refresh use cases for model metadata."""

from __future__ import annotations

from dataclasses import dataclass

from substitute_backend.features.model_metadata.domain.fingerprints import (
    FingerprintJob,
)
from substitute_backend.features.model_metadata.domain.statuses import JobStatus
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    ModelRootsProvider,
)
from substitute_backend.features.model_metadata.infrastructure.fingerprint_cache import (
    FileFreshness,
    FingerprintCache,
)
from substitute_backend.features.model_metadata.infrastructure.fingerprint_worker import (
    FingerprintWorker,
    FingerprintWorkItem,
)
from substitute_backend.features.model_metadata.infrastructure.time_utils import (
    format_timestamp,
)


@dataclass(frozen=True)
class FingerprintRefreshEntry:
    """Requested fingerprint refresh for one model file."""

    kind: str
    value: str
    size_bytes: int | None = None
    modified_at: str | None = None


class FingerprintService:
    """Queue and report model file fingerprint work."""

    def __init__(
        self,
        model_roots: ModelRootsProvider,
        fingerprint_cache: FingerprintCache,
        worker: FingerprintWorker,
    ) -> None:
        """Initialize the service from model roots, cache, and worker."""

        self._model_roots = model_roots
        self._fingerprint_cache = fingerprint_cache
        self._worker = worker

    def refresh(self, entries: tuple[FingerprintRefreshEntry, ...]) -> FingerprintJob:
        """Queue fingerprint refresh work for selected model entries."""

        work_items: list[FingerprintWorkItem] = []
        for entry in entries:
            model_file = self._model_roots.resolve_model_file(entry.kind, entry.value)
            if model_file is None:
                continue
            stat = model_file.path.stat()
            modified_at = format_timestamp(stat.st_mtime)
            if entry.size_bytes is not None and entry.size_bytes != stat.st_size:
                continue
            if entry.modified_at is not None and entry.modified_at != modified_at:
                continue
            freshness = FileFreshness(
                root_id=model_file.root_id,
                relative_path=model_file.relative_path,
                size_bytes=stat.st_size,
                modified_at=modified_at,
            )
            cached = self._fingerprint_cache.get_sha256(freshness)
            if cached.sha256 is not None:
                continue
            work_items.append(FingerprintWorkItem(model_file=model_file, freshness=freshness))
        if not work_items:
            return FingerprintJob(job_id="no-work", status=JobStatus.COMPLETE, entries=())
        return self._worker.submit(tuple(work_items))

    def get_job(self, job_id: str) -> FingerprintJob | None:
        """Return the current state for a fingerprint job."""

        if job_id == "no-work":
            return FingerprintJob(job_id="no-work", status=JobStatus.COMPLETE, entries=())
        return self._worker.get_job(job_id)

    def find_active_job(
        self,
        entries: tuple[FingerprintRefreshEntry, ...],
    ) -> FingerprintJob | None:
        """Return an active background job for any requested entry."""

        for entry in entries:
            active = self._worker.find_active_job_for(entry.kind, entry.value)
            if active is not None:
                return active
        return None

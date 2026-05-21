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
"""Local model lookup by SHA256 without inline hashing."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from substitute_backend.features.model_metadata.domain.catalog import (
    ModelFile,
    ModelFileStat,
    ModelSource,
)
from substitute_backend.features.model_metadata.domain.hash_lookup import (
    HashLookupMatch,
    HashLookupResult,
)
from substitute_backend.features.model_metadata.domain.statuses import (
    FingerprintStatus,
    HashLookupStatus,
)
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    ModelRootsProvider,
)
from substitute_backend.features.model_metadata.infrastructure.fingerprint_cache import (
    FileFreshness,
    FingerprintCache,
)
from substitute_backend.features.model_metadata.infrastructure.sidecar_reader import (
    SidecarReader,
)
from substitute_backend.features.model_metadata.infrastructure.time_utils import (
    format_timestamp,
)

from .fingerprint_service import FingerprintRefreshEntry, FingerprintService

_SHA256_RE = re.compile(r"^[0-9A-Fa-f]{64}$")


@dataclass(frozen=True)
class HashLookupQuery:
    """Inputs for local model hash lookup."""

    kind: str
    sha256: str


class HashLookupService:
    """Find local models by SHA256 using sidecar and cached fingerprint evidence."""

    def __init__(
        self,
        model_roots: ModelRootsProvider,
        fingerprint_cache: FingerprintCache,
        sidecar_reader: SidecarReader,
        fingerprints: FingerprintService,
        logger: logging.Logger,
    ) -> None:
        """Initialize the service from model evidence readers and hash worker access."""

        self._model_roots = model_roots
        self._fingerprint_cache = fingerprint_cache
        self._sidecar_reader = sidecar_reader
        self._fingerprints = fingerprints
        self._logger = logger

    def lookup(self, query: HashLookupQuery) -> HashLookupResult:
        """Return local matches or queue background hashing for unresolved candidates."""

        normalized_hash = query.sha256.strip().upper()
        if not _SHA256_RE.fullmatch(normalized_hash):
            return HashLookupResult(
                status=HashLookupStatus.UNAVAILABLE,
                kind=query.kind,
                sha256=normalized_hash,
            )
        if query.kind not in self._model_roots.supported_kinds():
            return HashLookupResult(
                status=HashLookupStatus.UNAVAILABLE,
                kind=query.kind,
                sha256=normalized_hash,
            )

        matches: list[HashLookupMatch] = []
        unhashed_entries: list[FingerprintRefreshEntry] = []
        for model_file in self._model_roots.list_model_files((query.kind,)):
            try:
                evidence = self._read_evidence(model_file)
            except OSError as exc:
                self._logger.warning(
                    "hash lookup candidate unavailable",
                    extra={
                        "operation": "hash-lookup",
                        "kind": model_file.kind,
                        "value": model_file.value,
                    },
                    exc_info=exc,
                )
                continue
            candidate_hash, file_stat, needs_hashing = evidence
            if candidate_hash == normalized_hash:
                matches.append(self._build_match(model_file, file_stat))
            elif needs_hashing:
                unhashed_entries.append(
                    FingerprintRefreshEntry(
                        kind=model_file.kind,
                        value=model_file.value,
                        size_bytes=file_stat.size_bytes,
                        modified_at=file_stat.modified_at,
                    )
                )

        if matches:
            return HashLookupResult(
                status=HashLookupStatus.COMPLETE,
                kind=query.kind,
                sha256=normalized_hash,
                matches=tuple(matches),
            )
        if not unhashed_entries:
            return HashLookupResult(
                status=HashLookupStatus.NOT_FOUND,
                kind=query.kind,
                sha256=normalized_hash,
            )
        entries = tuple(unhashed_entries)
        active_job = self._fingerprints.find_active_job(entries)
        if active_job is not None:
            return HashLookupResult(
                status=HashLookupStatus.HASHING_RUNNING,
                kind=query.kind,
                sha256=normalized_hash,
                job_id=active_job.job_id,
            )
        job = self._fingerprints.refresh(entries)
        if job.job_id == "no-work":
            return HashLookupResult(
                status=HashLookupStatus.NOT_FOUND,
                kind=query.kind,
                sha256=normalized_hash,
            )
        return HashLookupResult(
            status=HashLookupStatus.HASHING_REQUIRED,
            kind=query.kind,
            sha256=normalized_hash,
            job_id=job.job_id,
        )

    def _read_evidence(
        self,
        model_file: ModelFile,
    ) -> tuple[str | None, ModelFileStat, bool]:
        """Read fresh non-blocking hash evidence for one local candidate."""

        stat = model_file.path.stat()
        modified_at = format_timestamp(stat.st_mtime)
        file_stat = ModelFileStat(
            extension=model_file.path.suffix,
            size_bytes=stat.st_size,
            modified_at=modified_at,
            created_at=format_timestamp(stat.st_ctime),
        )
        sidecar, _ = self._sidecar_reader.read_sidecar(model_file.path)
        if sidecar.sha256 is not None and (
            sidecar.modified_at is None or sidecar.modified_at >= modified_at
        ):
            return sidecar.sha256.upper(), file_stat, False
        cached = self._fingerprint_cache.get_sha256(
            FileFreshness(
                root_id=model_file.root_id,
                relative_path=model_file.relative_path,
                size_bytes=stat.st_size,
                modified_at=modified_at,
            )
        )
        if cached.status is FingerprintStatus.READY and cached.sha256 is not None:
            return cached.sha256.upper(), file_stat, False
        return None, file_stat, True

    @staticmethod
    def _build_match(model_file: ModelFile, file_stat: ModelFileStat) -> HashLookupMatch:
        """Build a safe public match object from a resolved model file."""

        return HashLookupMatch(
            kind=model_file.kind,
            value=model_file.value,
            display_name=model_file.display_name,
            source=ModelSource(
                root_id=model_file.root_id,
                relative_path=model_file.relative_path,
            ),
            file=file_stat,
        )

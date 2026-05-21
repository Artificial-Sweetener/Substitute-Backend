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
"""Catalog use case for ComfyUI-visible model files."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from substitute_backend import MODEL_METADATA_SCHEMA_VERSION
from substitute_backend.features.model_metadata.domain.catalog import (
    CatalogWarning,
    ModelCatalogEntry,
    ModelFile,
    ModelFileStat,
    ModelSource,
)
from substitute_backend.features.model_metadata.domain.fingerprints import Fingerprint
from substitute_backend.features.model_metadata.domain.previews import MISSING_PREVIEW
from substitute_backend.features.model_metadata.domain.sidecars import SidecarSummary
from substitute_backend.features.model_metadata.domain.statuses import (
    FingerprintSource,
    FingerprintStatus,
)
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    ModelRootsProvider,
)
from substitute_backend.features.model_metadata.infrastructure.fingerprint_cache import (
    FileFreshness,
    FingerprintCache,
)
from substitute_backend.features.model_metadata.infrastructure.preview_store import (
    PreviewStore,
)
from substitute_backend.features.model_metadata.infrastructure.sidecar_reader import (
    SidecarReader,
)
from substitute_backend.features.model_metadata.infrastructure.time_utils import (
    format_timestamp,
)


@dataclass(frozen=True)
class CatalogQuery:
    """Inputs controlling model catalog listing behavior."""

    kinds: tuple[str, ...] | None = None
    include_hashes: bool = False
    include_local_metadata: bool = True
    include_previews: bool = True


class CatalogService:
    """Build safe model catalog entries from ComfyUI-local evidence."""

    def __init__(
        self,
        model_roots: ModelRootsProvider,
        fingerprint_cache: FingerprintCache,
        sidecar_reader: SidecarReader,
        preview_store: PreviewStore,
        logger: logging.Logger,
        target_id: str = "comfy-target",
    ) -> None:
        """Initialize the catalog service from its owned collaborators."""

        self._model_roots = model_roots
        self._fingerprint_cache = fingerprint_cache
        self._sidecar_reader = sidecar_reader
        self._preview_store = preview_store
        self._logger = logger
        self._target_id = target_id

    def list_models(self, query: CatalogQuery) -> tuple[ModelCatalogEntry, ...]:
        """List model entries without doing expensive inline fingerprinting."""

        entries: list[ModelCatalogEntry] = []
        for model_file in self._model_roots.list_model_files(query.kinds):
            try:
                entries.append(self._build_entry(model_file, query))
            except OSError as exc:
                self._logger.warning(
                    "catalog entry unavailable",
                    extra={"operation": "catalog-list", "kind": model_file.kind},
                    exc_info=exc,
                )
        return tuple(entries)

    def get_freshness(self, model_file: ModelFile) -> FileFreshness:
        """Return cache freshness data for a resolved model file."""

        stat = model_file.path.stat()
        return FileFreshness(
            root_id=model_file.root_id,
            relative_path=model_file.relative_path,
            size_bytes=stat.st_size,
            modified_at=format_timestamp(stat.st_mtime),
        )

    def _build_entry(
        self,
        model_file: ModelFile,
        query: CatalogQuery,
    ) -> ModelCatalogEntry:
        """Build one public catalog entry from local evidence."""

        stat = model_file.path.stat()
        modified_at = format_timestamp(stat.st_mtime)
        file_stat = ModelFileStat(
            extension=model_file.path.suffix,
            size_bytes=stat.st_size,
            modified_at=modified_at,
            created_at=format_timestamp(stat.st_ctime),
        )
        freshness = FileFreshness(
            root_id=model_file.root_id,
            relative_path=model_file.relative_path,
            size_bytes=stat.st_size,
            modified_at=modified_at,
        )
        warnings: list[CatalogWarning] = []
        fingerprint = self._fingerprint_cache.get_sha256(freshness)
        sidecar = SidecarSummary(found=False)
        if query.include_local_metadata:
            sidecar, sidecar_warnings = self._sidecar_reader.read_sidecar(model_file.path)
            warnings.extend(sidecar_warnings)
            fingerprint = self._prefer_sidecar_fingerprint(
                fingerprint=fingerprint,
                sidecar=sidecar,
                model_modified_at=modified_at,
            )
        local_preview = (
            self._preview_store.discover(model_file) if query.include_previews else MISSING_PREVIEW
        )
        return ModelCatalogEntry(
            schema_version=MODEL_METADATA_SCHEMA_VERSION,
            target_id=self._target_id,
            kind=model_file.kind,
            value=model_file.value,
            display_name=model_file.display_name,
            source=ModelSource(
                root_id=model_file.root_id,
                relative_path=model_file.relative_path,
            ),
            file=file_stat,
            fingerprint=fingerprint,
            sidecar=sidecar,
            local_preview=local_preview,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _prefer_sidecar_fingerprint(
        fingerprint: Fingerprint,
        sidecar: SidecarSummary,
        model_modified_at: str,
    ) -> Fingerprint:
        """Use a valid sidecar SHA256 only when cache data is missing."""

        if fingerprint.status is FingerprintStatus.READY:
            return fingerprint
        if sidecar.sha256 is None:
            return fingerprint
        if sidecar.modified_at is not None and sidecar.modified_at < model_modified_at:
            return Fingerprint(
                status=FingerprintStatus.STALE,
                sha256=sidecar.sha256.upper(),
                source=FingerprintSource.SIDECAR,
            )
        return Fingerprint(
            status=FingerprintStatus.READY,
            sha256=sidecar.sha256.upper(),
            source=FingerprintSource.SIDECAR,
            computed_at=sidecar.modified_at,
        )

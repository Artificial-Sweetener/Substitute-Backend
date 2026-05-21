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
"""Coordinate TAESD decoder status checks and preparation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from substitute_backend.features.preview_assets.domain import (
    PREVIEW_ASSETS_SCHEMA_VERSION,
    PreviewAssetDefinition,
    PreviewAssetRecord,
    PreviewAssetStatus,
    TaesdAssetStatus,
    taesd_asset_manifest,
)


class VaeApproxPathProvider(Protocol):
    """Resolve the writable ComfyUI root used for approximate VAE models."""

    def resolve_root(self) -> Path:
        """Return the destination root for TAESD decoder assets."""


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Describe one bounded preview asset download attempt."""

    succeeded: bool
    size_bytes: int | None = None
    error: str | None = None


class AssetDownloader(Protocol):
    """Download one allowlisted preview asset into a final destination path."""

    def download(self, url: str, destination: Path) -> DownloadResult:
        """Download the asset at ``url`` to ``destination``."""


class TaesdAssetService:
    """Prepare TAESD decoder files under ComfyUI's configured ``vae_approx`` root."""

    def __init__(
        self,
        *,
        path_provider: VaeApproxPathProvider,
        downloader: AssetDownloader,
        logger: logging.Logger,
        manifest: tuple[PreviewAssetDefinition, ...] | None = None,
    ) -> None:
        """Initialize the service with host-boundary adapters and manifest data."""

        self._path_provider = path_provider
        self._downloader = downloader
        self._logger = logger
        self._manifest = manifest or taesd_asset_manifest()

    def status(self) -> TaesdAssetStatus:
        """Return TAESD decoder readiness without touching the network."""

        root = self._path_provider.resolve_root()
        return self._build_status(root, downloads_attempted=False)

    def ensure(self) -> TaesdAssetStatus:
        """Download missing TAESD decoder files and return final readiness."""

        root = self._path_provider.resolve_root()
        assets: list[PreviewAssetRecord] = []
        for definition in self._manifest:
            destination = (root / definition.filename).resolve()
            existing = self._installed_record(definition, destination)
            if existing is not None:
                assets.append(existing)
                continue
            self._logger.info(
                "preparing TAESD preview asset",
                extra={
                    "operation": "prepare-taesd-preview-asset",
                    "asset_filename": definition.filename,
                    "destination_root": str(root),
                },
            )
            result = self._downloader.download(definition.url, destination)
            if result.succeeded:
                size_bytes = (
                    result.size_bytes
                    if result.size_bytes is not None
                    else self._file_size(destination)
                )
                assets.append(
                    PreviewAssetRecord(
                        asset_id=definition.asset_id,
                        filename=definition.filename,
                        url=definition.url,
                        status=PreviewAssetStatus.INSTALLED,
                        path=destination,
                        size_bytes=size_bytes,
                    )
                )
                continue
            self._logger.warning(
                "TAESD preview asset preparation failed",
                extra={
                    "operation": "prepare-taesd-preview-asset",
                    "asset_filename": definition.filename,
                    "destination_root": str(root),
                    "error": result.error,
                },
            )
            assets.append(
                PreviewAssetRecord(
                    asset_id=definition.asset_id,
                    filename=definition.filename,
                    url=definition.url,
                    status=PreviewAssetStatus.FAILED,
                    path=destination,
                    error=result.error or "Download failed.",
                )
            )
        return TaesdAssetStatus(
            schema_version=PREVIEW_ASSETS_SCHEMA_VERSION,
            destination_root=root,
            assets=tuple(assets),
            downloads_attempted=True,
        )

    def _build_status(
        self,
        root: Path,
        *,
        downloads_attempted: bool,
    ) -> TaesdAssetStatus:
        """Build a status snapshot from the current filesystem state."""

        assets = tuple(
            self._record_for_definition(root, definition) for definition in self._manifest
        )
        return TaesdAssetStatus(
            schema_version=PREVIEW_ASSETS_SCHEMA_VERSION,
            destination_root=root,
            assets=assets,
            downloads_attempted=downloads_attempted,
        )

    def _record_for_definition(
        self,
        root: Path,
        definition: PreviewAssetDefinition,
    ) -> PreviewAssetRecord:
        """Return one asset record from the current destination file state."""

        destination = (root / definition.filename).resolve()
        installed = self._installed_record(definition, destination)
        if installed is not None:
            return installed
        return PreviewAssetRecord(
            asset_id=definition.asset_id,
            filename=definition.filename,
            url=definition.url,
            status=PreviewAssetStatus.MISSING,
            path=destination,
        )

    @staticmethod
    def _installed_record(
        definition: PreviewAssetDefinition,
        destination: Path,
    ) -> PreviewAssetRecord | None:
        """Return an installed record when ``destination`` is an existing file."""

        if not destination.is_file():
            return None
        return PreviewAssetRecord(
            asset_id=definition.asset_id,
            filename=definition.filename,
            url=definition.url,
            status=PreviewAssetStatus.INSTALLED,
            path=destination,
            size_bytes=destination.stat().st_size,
        )

    @staticmethod
    def _file_size(path: Path) -> int | None:
        """Return the file size if a downloaded asset exists."""

        if not path.is_file():
            return None
        return path.stat().st_size

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
"""Define stable preview asset contracts exposed to SugarSubstitute."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from substitute_backend.api.serialization import JsonObject

PREVIEW_ASSETS_SCHEMA_VERSION = 1


class PreviewAssetStatus(StrEnum):
    """Identify the installation state for one preview asset."""

    INSTALLED = "installed"
    MISSING = "missing"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PreviewAssetError(Exception):
    """Describe a preview-asset failure that can become a structured API error."""

    message: str
    code: str = "preview-asset-error"
    status: int = 500


@dataclass(frozen=True, slots=True)
class PreviewAssetDefinition:
    """Describe one allowlisted upstream TAESD decoder asset."""

    asset_id: str
    filename: str
    url: str


@dataclass(frozen=True, slots=True)
class PreviewAssetRecord:
    """Describe one TAESD decoder file status for the public backend API."""

    asset_id: str
    filename: str
    url: str
    status: PreviewAssetStatus
    path: Path | None = None
    size_bytes: int | None = None
    error: str | None = None

    def to_payload(self) -> JsonObject:
        """Return the public API payload for one preview asset."""

        payload: JsonObject = {
            "id": self.asset_id,
            "filename": self.filename,
            "url": self.url,
            "status": self.status.value,
        }
        if self.path is not None:
            payload["path"] = str(self.path)
        if self.size_bytes is not None:
            payload["sizeBytes"] = self.size_bytes
        if self.error is not None:
            payload["error"] = self.error
        return payload


@dataclass(frozen=True, slots=True)
class TaesdAssetStatus:
    """Describe TAESD decoder readiness under the active ComfyUI model root."""

    schema_version: int
    destination_root: Path | None
    assets: tuple[PreviewAssetRecord, ...]
    downloads_attempted: bool = False

    @property
    def installed_count(self) -> int:
        """Return the number of installed assets."""

        return sum(1 for asset in self.assets if asset.status is PreviewAssetStatus.INSTALLED)

    @property
    def missing_count(self) -> int:
        """Return the number of assets that are not ready."""

        return len(self.assets) - self.installed_count

    @property
    def ready(self) -> bool:
        """Return whether all required TAESD decoder files are installed."""

        return bool(self.assets) and self.missing_count == 0

    def to_payload(self) -> JsonObject:
        """Return the public API payload for TAESD asset readiness."""

        payload: JsonObject = {
            "schemaVersion": self.schema_version,
            "ready": self.ready,
            "installedCount": self.installed_count,
            "missingCount": self.missing_count,
            "downloadsAttempted": self.downloads_attempted,
            "assets": [asset.to_payload() for asset in self.assets],
        }
        if self.destination_root is not None:
            payload["destinationRoot"] = str(self.destination_root)
        return payload


def taesd_asset_manifest() -> tuple[PreviewAssetDefinition, ...]:
    """Return ComfyUI's documented TAESD image preview decoder assets."""

    return (
        PreviewAssetDefinition(
            asset_id="taesd",
            filename="taesd_decoder.pth",
            url="https://github.com/madebyollin/taesd/raw/main/taesd_decoder.pth",
        ),
        PreviewAssetDefinition(
            asset_id="taesdxl",
            filename="taesdxl_decoder.pth",
            url="https://github.com/madebyollin/taesd/raw/main/taesdxl_decoder.pth",
        ),
        PreviewAssetDefinition(
            asset_id="taesd3",
            filename="taesd3_decoder.pth",
            url="https://github.com/madebyollin/taesd/raw/main/taesd3_decoder.pth",
        ),
        PreviewAssetDefinition(
            asset_id="taef1",
            filename="taef1_decoder.pth",
            url="https://github.com/madebyollin/taesd/raw/main/taef1_decoder.pth",
        ),
    )

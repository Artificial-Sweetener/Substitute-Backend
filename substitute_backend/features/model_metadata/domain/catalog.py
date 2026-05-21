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
"""Catalog contracts for ComfyUI-visible model files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from substitute_backend.api.serialization import JsonObject

from .fingerprints import Fingerprint
from .previews import LocalPreviewReference
from .sidecars import SidecarSummary
from .statuses import CatalogWarningCode


@dataclass(frozen=True)
class CatalogWarning:
    """Structured warning attached to a catalog entry."""

    code: CatalogWarningCode
    message: str

    def to_payload(self) -> JsonObject:
        """Return the public warning payload."""

        return {"code": self.code.value, "message": self.message}


@dataclass(frozen=True)
class ModelFile:
    """Internal resolved model file reference."""

    kind: str
    value: str
    display_name: str
    root_id: str
    relative_path: str
    path: Path


@dataclass(frozen=True)
class ModelFileStat:
    """Safe file stat data for a model catalog entry."""

    extension: str
    size_bytes: int
    modified_at: str
    created_at: str | None = None

    def to_payload(self) -> JsonObject:
        """Return the public file stat payload."""

        return {
            "extension": self.extension,
            "sizeBytes": self.size_bytes,
            "modifiedAt": self.modified_at,
            "createdAt": self.created_at,
        }


@dataclass(frozen=True)
class ModelSource:
    """Safe source reference for a model file."""

    root_id: str
    relative_path: str

    def to_payload(self) -> JsonObject:
        """Return the public model source payload."""

        return {"rootId": self.root_id, "relativePath": self.relative_path}


@dataclass(frozen=True)
class ModelCatalogEntry:
    """Public model catalog entry returned to SugarSubstitute."""

    schema_version: int
    target_id: str
    kind: str
    value: str
    display_name: str
    source: ModelSource
    file: ModelFileStat
    fingerprint: Fingerprint
    sidecar: SidecarSummary
    local_preview: LocalPreviewReference
    warnings: tuple[CatalogWarning, ...] = ()

    def to_payload(self) -> JsonObject:
        """Return the public catalog entry payload."""

        return {
            "schemaVersion": self.schema_version,
            "targetId": self.target_id,
            "kind": self.kind,
            "value": self.value,
            "displayName": self.display_name,
            "source": self.source.to_payload(),
            "file": self.file.to_payload(),
            "fingerprint": self.fingerprint.to_payload(),
            "sidecar": self.sidecar.to_payload(),
            "localPreview": self.local_preview.to_payload(),
            "warnings": [warning.to_payload() for warning in self.warnings],
        }

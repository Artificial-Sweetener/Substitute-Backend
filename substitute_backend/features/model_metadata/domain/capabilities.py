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
"""Capability contracts for Substitute BackEnd."""

from __future__ import annotations

from dataclasses import dataclass

from substitute_backend.api.serialization import JsonObject


@dataclass(frozen=True)
class ModelMetadataCapabilities:
    """Describe model metadata feature support for SugarSubstitute."""

    schema_version: int
    supported_model_kinds: tuple[str, ...]
    supported_hash_algorithms: tuple[str, ...]
    local_preview_serving: bool
    background_hashing: bool
    hash_lookup: bool
    sidecar_reading: bool
    sidecar_writing: bool

    def to_payload(self) -> JsonObject:
        """Return the model metadata capability payload."""

        return {
            "schemaVersion": self.schema_version,
            "supportedModelKinds": list(self.supported_model_kinds),
            "supportedHashAlgorithms": list(self.supported_hash_algorithms),
            "localPreviewServing": self.local_preview_serving,
            "backgroundHashing": self.background_hashing,
            "hashLookup": self.hash_lookup,
            "sidecarReading": self.sidecar_reading,
            "sidecarWriting": self.sidecar_writing,
        }


@dataclass(frozen=True)
class BackendCapabilities:
    """Describe Substitute BackEnd API and feature support."""

    extension_name: str
    extension_version: str
    api_version: int
    features: tuple[str, ...]
    model_metadata: ModelMetadataCapabilities

    def to_payload(self) -> JsonObject:
        """Return the backend capability payload."""

        return {
            "extensionName": self.extension_name,
            "extensionVersion": self.extension_version,
            "apiVersion": self.api_version,
            "features": list(self.features),
            "modelMetadata": self.model_metadata.to_payload(),
        }

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
"""Capability use case for the model metadata feature."""

from __future__ import annotations

from dataclasses import dataclass

from substitute_backend import (
    API_VERSION,
    EXTENSION_NAME,
    MODEL_METADATA_SCHEMA_VERSION,
    __version__,
)
from substitute_backend.features.model_metadata.domain.capabilities import (
    BackendCapabilities,
    ModelMetadataCapabilities,
)
from substitute_backend.features.model_metadata.infrastructure.comfy_model_roots import (
    ModelRootsProvider,
)


@dataclass(frozen=True)
class CapabilityService:
    """Build backend capability payloads from configured services."""

    model_roots: ModelRootsProvider

    def get_capabilities(self) -> BackendCapabilities:
        """Return backend and feature capability information."""

        model_metadata = ModelMetadataCapabilities(
            schema_version=MODEL_METADATA_SCHEMA_VERSION,
            supported_model_kinds=self.model_roots.supported_kinds(),
            supported_hash_algorithms=("sha256",),
            local_preview_serving=True,
            background_hashing=True,
            hash_lookup=True,
            sidecar_reading=True,
            sidecar_writing=False,
        )
        return BackendCapabilities(
            extension_name=EXTENSION_NAME,
            extension_version=__version__,
            api_version=API_VERSION,
            features=("model-metadata",),
            model_metadata=model_metadata,
        )

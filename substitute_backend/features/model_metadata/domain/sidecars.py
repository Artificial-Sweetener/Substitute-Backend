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
"""Sidecar metadata contracts for model catalog entries."""

from __future__ import annotations

from dataclasses import dataclass

from substitute_backend.api.serialization import JsonObject


@dataclass(frozen=True)
class SidecarSummary:
    """Known metadata parsed from a local model sidecar."""

    found: bool
    model_id: int | None = None
    model_version_id: int | None = None
    sha256: str | None = None
    activation_text: str | None = None
    description: str | None = None
    base_model: str | None = None
    modified_at: str | None = None

    def to_payload(self) -> JsonObject:
        """Return the public sidecar payload."""

        return {
            "found": self.found,
            "modelId": self.model_id,
            "modelVersionId": self.model_version_id,
            "sha256": self.sha256,
            "activationText": self.activation_text,
            "description": self.description,
            "baseModel": self.base_model,
            "modifiedAt": self.modified_at,
        }


MISSING_SIDECAR = SidecarSummary(found=False)

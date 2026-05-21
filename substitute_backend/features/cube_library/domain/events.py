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
"""Public websocket payload contracts for Cube Library changes."""

from __future__ import annotations

from dataclasses import dataclass

from substitute_backend.api.serialization import JsonObject

EVENT_TYPE = "substitute_cube_library_changed"


@dataclass(frozen=True)
class CubeLibraryChangedEvent:
    """Describe one Cube Library catalog change notification."""

    catalog_revision: str
    previous_catalog_revision: str
    generated_at: str
    reason: str
    schema_version: int = 1

    def to_payload(self) -> JsonObject:
        """Return the versioned public websocket event payload."""

        return {
            "schemaVersion": self.schema_version,
            "catalogRevision": self.catalog_revision,
            "previousCatalogRevision": self.previous_catalog_revision,
            "generatedAt": self.generated_at,
            "reason": self.reason,
        }

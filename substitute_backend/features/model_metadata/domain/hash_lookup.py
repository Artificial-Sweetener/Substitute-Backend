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
"""Hash lookup contracts for ComfyUI-visible model files."""

from __future__ import annotations

from dataclasses import dataclass

from substitute_backend import MODEL_METADATA_SCHEMA_VERSION
from substitute_backend.api.serialization import JsonObject

from .catalog import ModelFileStat, ModelSource
from .statuses import HashLookupStatus


@dataclass(frozen=True)
class HashLookupMatch:
    """Safe public reference to a local model matching a requested SHA256."""

    kind: str
    value: str
    display_name: str
    source: ModelSource
    file: ModelFileStat

    def to_payload(self) -> JsonObject:
        """Return the public match payload without exposing absolute paths."""

        return {
            "kind": self.kind,
            "value": self.value,
            "displayName": self.display_name,
            "source": self.source.to_payload(),
            "file": self.file.to_payload(),
        }


@dataclass(frozen=True)
class HashLookupResult:
    """Public result for a local model hash lookup."""

    status: HashLookupStatus
    kind: str
    sha256: str
    matches: tuple[HashLookupMatch, ...] = ()
    job_id: str | None = None

    def to_payload(self) -> JsonObject:
        """Return the public hash lookup payload."""

        return {
            "schemaVersion": MODEL_METADATA_SCHEMA_VERSION,
            "status": self.status.value,
            "kind": self.kind,
            "sha256": self.sha256,
            "matches": [match.to_payload() for match in self.matches],
            "jobId": self.job_id,
        }

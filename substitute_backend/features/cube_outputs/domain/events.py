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
"""Public websocket payload contracts for cube outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from substitute_backend.api.serialization import JsonObject, JsonValue

MediaKind = Literal["image", "audio", "video", "value", "unknown"]


@dataclass(frozen=True)
class CubeOutputArtifactEvent:
    """Describe one artifact produced for a Substitute cube output."""

    filename: str
    subfolder: str
    type: str
    media_kind: MediaKind
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None

    def to_payload(self) -> JsonObject:
        """Return the artifact payload sent over Comfy's websocket."""

        payload: JsonObject = {
            "filename": self.filename,
            "subfolder": self.subfolder,
            "type": self.type,
            "media_kind": self.media_kind,
        }
        optional_values: dict[str, JsonValue] = {
            "mime_type": self.mime_type,
            "width": self.width,
            "height": self.height,
            "duration_seconds": self.duration_seconds,
        }
        for key, value in optional_values.items():
            if value is not None:
                payload[key] = value
        return payload


@dataclass(frozen=True)
class CubeOutputWebsocketEvent:
    """Describe one Substitute cube output websocket event."""

    prompt_id: str | None
    node_id: str | None
    list_index: int | None
    cube_id: str
    default_alias: str
    instance_alias: str
    instance_id: str
    media_kind: MediaKind
    value_type: str
    artifacts: tuple[CubeOutputArtifactEvent, ...]
    version: int = 1

    def to_payload(self) -> JsonObject:
        """Return the versioned public websocket event payload."""

        payload: JsonObject = {
            "version": self.version,
            "prompt_id": self.prompt_id,
            "node_id": self.node_id,
            "list_index": self.list_index,
            "cube_id": self.cube_id,
            "default_alias": self.default_alias,
            "instance_alias": self.instance_alias,
            "instance_id": self.instance_id,
            "media_kind": self.media_kind,
            "value_type": self.value_type,
            "artifacts": [artifact.to_payload() for artifact in self.artifacts],
        }
        return payload

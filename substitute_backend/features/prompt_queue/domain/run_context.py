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
"""Domain models for Substitute visual routing run context."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from substitute_backend.api.serialization import JsonObject


@dataclass(frozen=True, slots=True)
class SubstituteSourceRoute:
    """Describe one node-to-source visual routing record."""

    source_key: str
    source_label: str
    cube_alias: str = ""

    def to_payload(self) -> JsonObject:
        """Return the public Substitute source identity payload."""

        return {
            "sourceKey": self.source_key,
            "sourceLabel": self.source_label,
            "cubeAlias": self.cube_alias,
        }


@dataclass(frozen=True, slots=True)
class SubstituteRunContext:
    """Capture Substitute visual routing facts for one queued prompt."""

    workflow_id: str
    generation_run_id: str
    client_id: str
    scene_run_id: str | None = None
    scene_key: str | None = None
    scene_title: str | None = None
    scene_order: int | None = None
    scene_count: int | None = None
    sources: Mapping[str, SubstituteSourceRoute] = field(default_factory=dict)

    def substitute_payload_for_source(self, source: SubstituteSourceRoute) -> JsonObject:
        """Return the Backend-enriched visual identity payload for one source."""

        payload: JsonObject = {
            "schemaVersion": 1,
            "workflowId": self.workflow_id,
            "generationRunId": self.generation_run_id,
            "clientId": self.client_id,
            "sourceKey": source.source_key,
            "sourceLabel": source.source_label,
        }
        if self.scene_run_id is not None:
            payload["sceneRunId"] = self.scene_run_id
        if self.scene_key is not None:
            payload["sceneKey"] = self.scene_key
        if self.scene_title is not None:
            payload["sceneTitle"] = self.scene_title
        if self.scene_order is not None:
            payload["sceneOrder"] = self.scene_order
        if self.scene_count is not None:
            payload["sceneCount"] = self.scene_count
        return payload


def parse_substitute_run_context(value: object) -> SubstituteRunContext | None:
    """Parse app-supplied queue metadata into a validated run context."""

    if not isinstance(value, Mapping) or value.get("schemaVersion") != 1:
        return None
    workflow_id = _required_string(value.get("workflowId"))
    generation_run_id = _required_string(value.get("generationRunId"))
    client_id = _required_string(value.get("clientId"))
    raw_sources = value.get("sources")
    if (
        workflow_id is None
        or generation_run_id is None
        or client_id is None
        or not isinstance(raw_sources, Mapping)
    ):
        return None
    sources = {
        str(node_id): source
        for node_id, source in (
            (node_id, _parse_source_route(route)) for node_id, route in raw_sources.items()
        )
        if source is not None
    }
    if not sources:
        return None
    scene = value.get("scene")
    scene_mapping = scene if isinstance(scene, Mapping) else {}
    return SubstituteRunContext(
        workflow_id=workflow_id,
        generation_run_id=generation_run_id,
        client_id=client_id,
        scene_run_id=_optional_string(scene_mapping.get("runId")),
        scene_key=_optional_string(scene_mapping.get("key")),
        scene_title=_optional_string(scene_mapping.get("title")),
        scene_order=_optional_int(scene_mapping.get("order")),
        scene_count=_optional_int(scene_mapping.get("count")),
        sources=sources,
    )


def _parse_source_route(value: object) -> SubstituteSourceRoute | None:
    """Parse one source route from queue metadata."""

    if not isinstance(value, Mapping):
        return None
    source_key = _required_string(value.get("sourceKey"))
    source_label = _required_string(value.get("sourceLabel"))
    if source_key is None or source_label is None:
        return None
    return SubstituteSourceRoute(
        source_key=source_key,
        source_label=source_label,
        cube_alias=_optional_string(value.get("cubeAlias")) or source_label,
    )


def _required_string(value: object) -> str | None:
    """Return a non-empty string value."""

    if isinstance(value, str) and value:
        return value
    return None


def _optional_string(value: object) -> str | None:
    """Return an optional string value."""

    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    """Return an optional integer value."""

    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


__all__ = [
    "SubstituteRunContext",
    "SubstituteSourceRoute",
    "parse_substitute_run_context",
]

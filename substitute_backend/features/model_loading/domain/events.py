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
"""Structured model-loading telemetry event contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from substitute_backend.api.serialization import JsonObject


class ModelLoadPhase(StrEnum):
    """Identify the model-loading phase described by a telemetry event."""

    REQUESTED = "requested"
    DYNAMIC_VRAM_STAGING = "dynamic_vram_staging"
    LOADED_PARTIALLY = "loaded_partially"
    LOADED_COMPLETELY = "loaded_completely"
    FAILED = "failed"


class ModelLoadState(StrEnum):
    """Identify whether a model-loading phase is active, complete, or unknown."""

    RUNNING = "running"
    FINISHED = "finished"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ModelLoadProgressEvent:
    """Represent one best-effort model-loading telemetry event."""

    phase: ModelLoadPhase
    state: ModelLoadState
    timestamp: float
    prompt_id: str | None = None
    node_id: str | None = None
    display_node_id: str | None = None
    percent: float | None = None
    value: float | None = None
    maximum: float | None = None
    unit: str | None = None
    model_class: str | None = None
    model_name: str | None = None
    source_node_id: str | None = None
    source_input_key: str | None = None
    detail: str | None = None
    version: int = 1

    def to_payload(self) -> JsonObject:
        """Return the public websocket event payload."""

        payload: JsonObject = {
            "version": self.version,
            "phase": self.phase.value,
            "state": self.state.value,
            "timestamp": self.timestamp,
        }
        optional_values: dict[str, str | int | float | None] = {
            "prompt_id": self.prompt_id,
            "node_id": self.node_id,
            "display_node_id": self.display_node_id,
            "unit": self.unit,
            "model_class": self.model_class,
            "model_name": self.model_name,
            "source_node_id": self.source_node_id,
            "source_input_key": self.source_input_key,
            "detail": self.detail,
        }
        for key, value in optional_values.items():
            if value is not None:
                payload[key] = value
        if self.value is not None and self.maximum is not None and self.maximum > 0:
            payload["value"] = self.value
            payload["max"] = self.maximum
            if self.percent is not None:
                payload["percent"] = _clamp_percent(self.percent)
        return payload


def _clamp_percent(value: float) -> float:
    """Clamp telemetry percentages to the UI progress range."""

    return min(100.0, max(0.0, value))

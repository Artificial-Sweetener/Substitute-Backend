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
"""Structured download telemetry event contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from substitute_backend.api.serialization import JsonObject


class DownloadProvider(StrEnum):
    """Identify the external download provider being observed."""

    HUGGINGFACE = "huggingface"


class DownloadState(StrEnum):
    """Identify the lifecycle state of one observed download operation."""

    STARTED = "started"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"


@dataclass(frozen=True)
class DownloadProgressEvent:
    """Represent one public download progress websocket event."""

    provider: DownloadProvider
    operation_id: str
    state: DownloadState
    timestamp: float
    prompt_id: str | None = None
    node_id: str | None = None
    display_node_id: str | None = None
    repo_id: str | None = None
    filename: str | None = None
    url: str | None = None
    value: float | None = None
    maximum: float | None = None
    percent: float | None = None
    unit: str | None = None
    detail: str | None = None
    version: int = 1

    def to_payload(self) -> JsonObject:
        """Return the versioned public websocket payload."""

        payload: JsonObject = {
            "version": self.version,
            "provider": self.provider.value,
            "operation_id": self.operation_id,
            "state": self.state.value,
            "timestamp": self.timestamp,
        }
        optional_strings = {
            "prompt_id": self.prompt_id,
            "node_id": self.node_id,
            "display_node_id": self.display_node_id,
            "repo_id": self.repo_id,
            "filename": self.filename,
            "url": self.url,
            "unit": self.unit,
            "detail": self.detail,
        }
        for key, value in optional_strings.items():
            if _has_text(value):
                payload[key] = value
        if self.value is not None:
            payload["value"] = self.value
        if self.value is not None and self.maximum is not None and self.maximum > 0:
            payload["max"] = self.maximum
            if self.percent is not None:
                payload["percent"] = _clamp_percent(self.percent)
        return payload


def _has_text(value: str | None) -> bool:
    """Return whether an optional text field is meaningful for public payloads."""

    return isinstance(value, str) and bool(value.strip())


def _clamp_percent(value: float) -> float:
    """Clamp telemetry percentages to the UI progress range."""

    return min(100.0, max(0.0, value))

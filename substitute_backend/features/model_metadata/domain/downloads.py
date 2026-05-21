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
"""Contracts for backend-managed model download jobs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from substitute_backend.api.serialization import JsonObject


class ModelDownloadStatus(StrEnum):
    """Describe lifecycle states for backend model downloads."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ModelDownloadResult:
    """Describe the verified local model produced by a download job."""

    kind: str
    value: str
    display_name: str
    root_id: str
    relative_path: str
    sha256: str
    extension: str
    size_bytes: int
    modified_at: str
    created_at: str | None

    def to_payload(self) -> JsonObject:
        """Return a public JSON payload without absolute paths."""

        return {
            "kind": self.kind,
            "value": self.value,
            "displayName": self.display_name,
            "source": {
                "rootId": self.root_id,
                "relativePath": self.relative_path,
            },
            "sha256": self.sha256,
            "file": {
                "extension": self.extension,
                "sizeBytes": self.size_bytes,
                "modifiedAt": self.modified_at,
                "createdAt": self.created_at,
            },
        }


@dataclass(frozen=True)
class ModelDownloadJob:
    """Represent one backend model download job."""

    job_id: str
    status: ModelDownloadStatus
    kind: str
    sha256: str
    value: str | None = None
    result: ModelDownloadResult | None = None
    error: str | None = None
    bytes_downloaded: int | None = None
    bytes_total: int | None = None
    detail: str | None = None

    def to_payload(self) -> JsonObject:
        """Return the public job payload."""

        payload: JsonObject = {
            "schemaVersion": 1,
            "jobId": self.job_id,
            "status": self.status.value,
            "kind": self.kind,
            "sha256": self.sha256,
        }
        if self.value is not None:
            payload["value"] = self.value
        if self.result is not None:
            payload["result"] = self.result.to_payload()
        if self.error:
            payload["error"] = self.error
        if self.bytes_downloaded is not None:
            payload["bytesDownloaded"] = self.bytes_downloaded
        if self.bytes_total is not None:
            payload["bytesTotal"] = self.bytes_total
        if self.detail:
            payload["detail"] = self.detail
        return payload

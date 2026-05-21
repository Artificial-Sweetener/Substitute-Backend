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
"""Fingerprint contracts for model files and background jobs."""

from __future__ import annotations

from dataclasses import dataclass

from substitute_backend.api.serialization import JsonObject

from .statuses import FingerprintSource, FingerprintStatus, JobStatus


@dataclass(frozen=True)
class Fingerprint:
    """Current fingerprint state for a model file."""

    status: FingerprintStatus
    sha256: str | None = None
    source: FingerprintSource | None = None
    computed_at: str | None = None
    error: str | None = None

    def to_payload(self) -> JsonObject:
        """Return the public fingerprint payload."""

        return {
            "status": self.status.value,
            "sha256": self.sha256,
            "source": self.source.value if self.source else None,
            "computedAt": self.computed_at,
            "error": self.error,
        }


@dataclass(frozen=True)
class FingerprintJobEntry:
    """Per-entry status in a background fingerprint job."""

    kind: str
    value: str
    status: JobStatus
    sha256: str | None = None
    error: str | None = None

    def to_payload(self) -> JsonObject:
        """Return the public job entry payload."""

        return {
            "kind": self.kind,
            "value": self.value,
            "status": self.status.value,
            "sha256": self.sha256,
            "error": self.error,
        }


@dataclass(frozen=True)
class FingerprintJob:
    """Public status for a background fingerprint job."""

    job_id: str
    status: JobStatus
    entries: tuple[FingerprintJobEntry, ...]

    def to_payload(self) -> JsonObject:
        """Return the public job payload."""

        return {
            "jobId": self.job_id,
            "status": self.status.value,
            "entries": [entry.to_payload() for entry in self.entries],
        }

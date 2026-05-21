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
"""Status enums for model metadata contracts."""

from __future__ import annotations

from enum import StrEnum


class FingerprintStatus(StrEnum):
    """Known states for model file fingerprint availability."""

    MISSING = "missing"
    QUEUED = "queued"
    HASHING = "hashing"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"


class FingerprintSource(StrEnum):
    """Known sources for a model file fingerprint."""

    BACKEND_CACHE = "backend-cache"
    COMPUTED = "computed"
    SIDECAR = "sidecar"


class PreviewSource(StrEnum):
    """Known sources for local preview candidates."""

    SAME_BASENAME_IMAGE = "same-basename-image"
    PREVIEW_SIDECAR = "preview-sidecar"
    EMBEDDED_METADATA = "embedded-metadata"
    BACKEND_CACHE = "backend-cache"


class JobStatus(StrEnum):
    """Known states for background fingerprint jobs."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HashLookupStatus(StrEnum):
    """Known states for locating local model files by SHA256."""

    COMPLETE = "complete"
    NOT_FOUND = "not-found"
    HASHING_REQUIRED = "hashing-required"
    HASHING_RUNNING = "hashing-running"
    UNAVAILABLE = "unavailable"


class CatalogWarningCode(StrEnum):
    """Structured warning codes returned with catalog entries."""

    MODEL_FILE_NOT_FOUND = "model-file-not-found"
    MODEL_FILE_UNREADABLE = "model-file-unreadable"
    UNSUPPORTED_EXTENSION = "unsupported-extension"
    HASH_MISSING = "hash-missing"
    HASH_QUEUED = "hash-queued"
    HASH_RUNNING = "hash-running"
    HASH_FAILED = "hash-failed"
    HASH_STALE = "hash-stale"
    SIDECAR_MISSING = "sidecar-missing"
    SIDECAR_PARSE_FAILED = "sidecar-parse-failed"
    PREVIEW_MISSING = "preview-missing"
    PREVIEW_READ_FAILED = "preview-read-failed"
    CATALOG_UNAVAILABLE = "catalog-unavailable"

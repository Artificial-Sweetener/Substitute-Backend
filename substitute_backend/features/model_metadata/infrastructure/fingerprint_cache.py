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
"""SQLite-backed cache for model metadata evidence."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from substitute_backend.features.model_metadata.domain.fingerprints import Fingerprint
from substitute_backend.features.model_metadata.domain.statuses import (
    FingerprintSource,
    FingerprintStatus,
)

CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FileFreshness:
    """File freshness values used to validate cached evidence."""

    root_id: str
    relative_path: str
    size_bytes: int
    modified_at: str


class FingerprintCache:
    """Persistent cache for file fingerprints."""

    def __init__(self, database_path: Path) -> None:
        """Open the cache database and ensure its schema exists."""

        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def get_sha256(self, freshness: FileFreshness) -> Fingerprint:
        """Return a cached SHA256 fingerprint or a missing status."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT sha256, computed_at
                FROM fingerprints
                WHERE schema_version = ?
                  AND root_id = ?
                  AND relative_path = ?
                  AND size_bytes = ?
                  AND modified_at = ?
                  AND algorithm = 'sha256'
                """,
                (
                    CACHE_SCHEMA_VERSION,
                    freshness.root_id,
                    freshness.relative_path,
                    freshness.size_bytes,
                    freshness.modified_at,
                ),
            ).fetchone()
        if row is None:
            return Fingerprint(status=FingerprintStatus.MISSING)
        sha256, computed_at = row
        return Fingerprint(
            status=FingerprintStatus.READY,
            sha256=str(sha256),
            source=FingerprintSource.BACKEND_CACHE,
            computed_at=str(computed_at),
        )

    def store_sha256(
        self,
        freshness: FileFreshness,
        sha256: str,
        computed_at: str,
    ) -> Fingerprint:
        """Persist and return a computed SHA256 fingerprint."""

        normalized_sha256 = sha256.upper()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO fingerprints (
                    schema_version,
                    root_id,
                    relative_path,
                    size_bytes,
                    modified_at,
                    algorithm,
                    sha256,
                    computed_at
                )
                VALUES (?, ?, ?, ?, ?, 'sha256', ?, ?)
                """,
                (
                    CACHE_SCHEMA_VERSION,
                    freshness.root_id,
                    freshness.relative_path,
                    freshness.size_bytes,
                    freshness.modified_at,
                    normalized_sha256,
                    computed_at,
                ),
            )
        return Fingerprint(
            status=FingerprintStatus.READY,
            sha256=normalized_sha256,
            source=FingerprintSource.COMPUTED,
            computed_at=computed_at,
        )

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection for the cache database."""

        return sqlite3.connect(self._database_path)

    def _initialize(self) -> None:
        """Create cache tables used by the backend."""

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fingerprints (
                    schema_version INTEGER NOT NULL,
                    root_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    modified_at TEXT NOT NULL,
                    algorithm TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    computed_at TEXT NOT NULL,
                    PRIMARY KEY (
                        schema_version,
                        root_id,
                        relative_path,
                        size_bytes,
                        modified_at,
                        algorithm
                    )
                )
                """
            )

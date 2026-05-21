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
"""Read-only parser for local model sidecar files."""

from __future__ import annotations

import json
from pathlib import Path

from substitute_backend.features.model_metadata.domain.catalog import CatalogWarning
from substitute_backend.features.model_metadata.domain.sidecars import (
    MISSING_SIDECAR,
    SidecarSummary,
)
from substitute_backend.features.model_metadata.domain.statuses import (
    CatalogWarningCode,
)

from .time_utils import format_timestamp


class SidecarReader:
    """Read known metadata fields from existing sidecar JSON files."""

    def read_sidecar(self, model_path: Path) -> tuple[SidecarSummary, tuple[CatalogWarning, ...]]:
        """Read an existing sidecar next to a model file without writing it."""

        sidecar_path = model_path.with_suffix(".json")
        if not sidecar_path.is_file():
            return MISSING_SIDECAR, ()
        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warning = CatalogWarning(
                code=CatalogWarningCode.SIDECAR_PARSE_FAILED,
                message=f"Failed to parse sidecar metadata: {exc}",
            )
            return MISSING_SIDECAR, (warning,)
        if not isinstance(data, dict):
            warning = CatalogWarning(
                code=CatalogWarningCode.SIDECAR_PARSE_FAILED,
                message="Sidecar metadata must be a JSON object.",
            )
            return MISSING_SIDECAR, (warning,)
        stat = sidecar_path.stat()
        return (
            SidecarSummary(
                found=True,
                model_id=self._read_int(data, "modelId"),
                model_version_id=self._read_int(data, "modelVersionId"),
                sha256=self._read_str(data, "sha256"),
                activation_text=self._read_first_str(
                    data,
                    ("activation text", "activationText", "trainedWords"),
                ),
                description=self._read_str(data, "description"),
                base_model=self._read_first_str(data, ("sd version", "sdVersion", "baseModel")),
                modified_at=format_timestamp(stat.st_mtime),
            ),
            (),
        )

    @staticmethod
    def _read_int(data: dict[object, object], key: str) -> int | None:
        """Read an integer value from sidecar metadata."""

        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    @staticmethod
    def _read_str(data: dict[object, object], key: str) -> str | None:
        """Read a non-empty string value from sidecar metadata."""

        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @classmethod
    def _read_first_str(
        cls,
        data: dict[object, object],
        keys: tuple[str, ...],
    ) -> str | None:
        """Read the first present string value from a set of sidecar keys."""

        for key in keys:
            value = cls._read_str(data, key)
            if value is not None:
                return value
        return None

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
"""Persist the Comfy installation's authoritative model-root selection."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

_CONFIG_DIRECTORY = ".substitute"
_CONFIG_FILE = "model_root.json"
_SCHEMA_VERSION = 1


class ModelRootStore:
    """Read and atomically replace model-root configuration for one Comfy root."""

    def __init__(self, comfy_root: Path) -> None:
        """Initialize persistence beneath the supplied Comfy installation."""

        self._comfy_root = comfy_root.resolve()
        self._config_path = self._comfy_root / _CONFIG_DIRECTORY / _CONFIG_FILE

    @property
    def config_path(self) -> Path:
        """Return the canonical persisted configuration path."""

        return self._config_path

    def load(self) -> Path | None:
        """Return the configured custom root, or ``None`` for Comfy's default."""

        if not self._config_path.exists():
            return None
        payload = json.loads(self._config_path.read_text(encoding="utf-8"))
        if payload.get("schemaVersion") != _SCHEMA_VERSION:
            raise ValueError("Unsupported model-root configuration schema.")
        value = payload.get("modelRoot")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Model-root configuration does not contain a path.")
        return self.resolve_custom_root(value)

    def save(self, model_root: Path | None) -> Path | None:
        """Persist a custom root, or remove configuration for Comfy's default."""

        if model_root is None:
            self._remove_config()
            return None
        resolved_root = self.resolve_custom_root(str(model_root))
        resolved_root.mkdir(parents=True, exist_ok=True)
        if not resolved_root.is_dir():
            raise ValueError("Model root must be a directory.")
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._config_path.with_name(f".{self._config_path.name}.{uuid4().hex}.tmp")
        try:
            temporary_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": _SCHEMA_VERSION,
                        "modelRoot": str(resolved_root),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporary_path, self._config_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        return resolved_root

    @staticmethod
    def resolve_custom_root(value: str) -> Path:
        """Validate and normalize one host-side custom model root."""

        expanded = Path(os.path.expandvars(value)).expanduser()
        if not expanded.is_absolute():
            raise ValueError("Model root must be an absolute path.")
        resolved = expanded.resolve()
        if resolved.exists() and not resolved.is_dir():
            raise ValueError("Model root must be a directory.")
        return resolved

    def _remove_config(self) -> None:
        """Remove the custom selection while preserving unrelated host state."""

        if self._config_path.exists():
            self._config_path.unlink()
        directory = self._config_path.parent
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()


__all__ = ["ModelRootStore"]

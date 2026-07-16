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
"""Model-root contracts owned by the Comfy environment."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from substitute_backend.api.serialization import JsonObject


class ModelRootMode(StrEnum):
    """Identify whether Comfy uses its default or a configured model root."""

    DEFAULT = "default"
    CUSTOM = "custom"


@dataclass(frozen=True)
class ModelRootStatus:
    """Describe persisted and active model-root state for one Comfy host."""

    schema_version: int
    default_model_root: Path
    configured_model_root: Path | None
    active_model_root: Path
    restart_required: bool

    @property
    def uses_default(self) -> bool:
        """Return whether the persisted configuration selects Comfy's default."""

        return self.configured_model_root is None

    def to_payload(self) -> JsonObject:
        """Return a stable API payload for external environment clients."""

        return {
            "schemaVersion": self.schema_version,
            "defaultModelRoot": str(self.default_model_root),
            "configuredModelRoot": (
                str(self.configured_model_root) if self.configured_model_root is not None else None
            ),
            "activeModelRoot": str(self.active_model_root),
            "usesDefault": self.uses_default,
            "restartRequired": self.restart_required,
        }


__all__ = ["ModelRootMode", "ModelRootStatus"]

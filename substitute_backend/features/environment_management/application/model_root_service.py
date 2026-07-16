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
"""Coordinate persisted and active Comfy model-root state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from substitute_backend.features.environment_management.domain.model_root import (
    ModelRootMode,
    ModelRootStatus,
)
from substitute_backend.features.environment_management.infrastructure.model_root_runtime import (
    ModelRootRuntime,
)
from substitute_backend.features.environment_management.infrastructure.model_root_store import (
    ModelRootStore,
)

_MODEL_ROOT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ModelRootService:
    """Own model-root queries and configuration changes for one Comfy host."""

    comfy_root: Path
    store: ModelRootStore
    runtime: ModelRootRuntime

    def get_status(self) -> ModelRootStatus:
        """Return the persisted selection alongside the running process state."""

        default_root = (self.comfy_root / "models").resolve()
        configured_root = self.store.load()
        active_root = self.runtime.active_model_root()
        desired_root = configured_root or default_root
        return ModelRootStatus(
            schema_version=_MODEL_ROOT_SCHEMA_VERSION,
            default_model_root=default_root,
            configured_model_root=configured_root,
            active_model_root=active_root,
            restart_required=desired_root != active_root,
        )

    def configure(self, mode: ModelRootMode, path: str | None) -> ModelRootStatus:
        """Persist an explicit default or custom selection for the next launch."""

        if mode is ModelRootMode.DEFAULT:
            if path is not None:
                raise ValueError("Default model-root mode does not accept a path.")
            self.store.save(None)
        else:
            if path is None or not path.strip():
                raise ValueError("Custom model-root mode requires a path.")
            self.store.save(ModelRootStore.resolve_custom_root(path))
        return self.get_status()


__all__ = ["ModelRootService"]

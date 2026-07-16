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
"""Read active model-root state from ComfyUI at the host boundary."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Protocol, cast


class ModelRootRuntime(Protocol):
    """Expose the model root active in the current Comfy process."""

    def active_model_root(self) -> Path:
        """Return the model root currently used by ComfyUI."""


class _FolderPathsModule(Protocol):
    """Describe the ComfyUI state required by the runtime adapter."""

    models_dir: str


class ComfyModelRootRuntime:
    """Read the active root from ComfyUI's initialized folder registry."""

    def active_model_root(self) -> Path:
        """Return ComfyUI's normalized active model root."""

        folder_paths = cast("_FolderPathsModule", importlib.import_module("folder_paths"))
        return Path(folder_paths.models_dir).resolve()


__all__ = ["ComfyModelRootRuntime", "ModelRootRuntime"]

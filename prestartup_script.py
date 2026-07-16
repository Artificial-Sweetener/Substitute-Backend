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
"""Run BackEnd model-root configuration in ComfyUI's prestartup phase."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType


def _load_prestartup_support(extension_root: Path) -> ModuleType:
    """Load the isolated support module without importing the node package."""

    module_path = extension_root / "substitute_backend_prestartup.py"
    spec = importlib.util.spec_from_file_location(
        "substitute_backend_prestartup_support", module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Substitute BackEnd prestartup support could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EXTENSION_ROOT = Path(__file__).resolve().parent
_SUPPORT = _load_prestartup_support(_EXTENSION_ROOT)
_SUPPORT.apply_model_root(
    _EXTENSION_ROOT.parents[1],
    importlib.import_module("folder_paths"),
)

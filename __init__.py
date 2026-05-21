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
"""ComfyUI extension entry point for Substitute BackEnd."""

from __future__ import annotations

import sys
from pathlib import Path

NODE_CLASS_MAPPINGS: dict[str, type[object]] = {}
NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {}
WEB_DIRECTORY = "web"

_EXTENSION_ROOT = Path(__file__).resolve().parent
_EXTENSION_ROOT_TEXT = str(_EXTENSION_ROOT)
if _EXTENSION_ROOT_TEXT not in sys.path:
    sys.path.insert(0, _EXTENSION_ROOT_TEXT)


def _register_with_comfy(extension_root: Path) -> None:
    """Register routes after ensuring the extension package is importable."""

    from substitute_backend.host.extension import register_extension

    register_extension(PromptServer, extension_root)


try:  # pragma: no cover - ComfyUI host module is unavailable in unit tests.
    from server import PromptServer
except (ImportError, ModuleNotFoundError):  # pragma: no cover - same as above.
    PromptServer = None
else:
    _register_with_comfy(_EXTENSION_ROOT)

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]

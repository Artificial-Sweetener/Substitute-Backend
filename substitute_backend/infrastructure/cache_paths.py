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
"""Cache path policy for Substitute BackEnd."""

from __future__ import annotations

from pathlib import Path


def get_cache_root(extension_root: Path) -> Path:
    """Return the backend-owned cache directory for this extension."""

    return extension_root / "cache"


def ensure_cache_root(extension_root: Path) -> Path:
    """Create and return the backend-owned cache directory."""

    cache_root = get_cache_root(extension_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root

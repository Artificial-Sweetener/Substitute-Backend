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
"""Shape public Cube Library icon descriptors for SugarSubstitute."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import quote

from substitute_backend.api.serialization import JsonObject

SUPPORTED_ICON_MEDIA_TYPES = frozenset({"image/png", "image/svg+xml"})


def build_cube_icon_url(cube_id: str) -> str:
    """Return the Substitute-BackEnd icon asset route for one cube id."""

    normalized_cube_id = cube_id.strip()
    if not normalized_cube_id:
        return ""
    encoded_cube_id = quote(normalized_cube_id, safe="")
    return f"/substitute/v1/cube-library/cubes/icon?cubeId={encoded_cube_id}"


def public_icon_descriptor(
    *,
    cube_id: str,
    icon: object,
) -> JsonObject | None:
    """Return a safe Substitute-facing icon descriptor or ``None``."""

    normalized_cube_id = cube_id.strip()
    if not normalized_cube_id or not isinstance(icon, Mapping):
        return None

    kind = _text_field(icon, "kind")
    media_type = _text_field(icon, "media_type") or _text_field(icon, "mediaType")
    if kind != "asset" or media_type not in SUPPORTED_ICON_MEDIA_TYPES:
        return None

    descriptor: JsonObject = {
        "kind": "asset",
        "media_type": media_type,
        "url": build_cube_icon_url(normalized_cube_id),
    }
    repo_relative_path = _text_field(icon, "repo_relative_path") or _text_field(
        icon,
        "repoRelativePath",
    )
    if repo_relative_path:
        descriptor["repo_relative_path"] = repo_relative_path
    return descriptor


def _text_field(data: Mapping[object, object], key: str) -> str:
    """Read one trimmed string field from a mapping."""

    value = data.get(key)
    return value.strip() if isinstance(value, str) else ""


__all__ = [
    "SUPPORTED_ICON_MEDIA_TYPES",
    "build_cube_icon_url",
    "public_icon_descriptor",
]

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
"""Application services for the Cube Library feature."""

from substitute_backend.features.cube_library.application.change_monitor import (
    CATALOG_REVISION_CHANGED_REASON,
    DEFAULT_POLL_INTERVAL_SECONDS,
    CubeLibraryChangeMonitor,
    CubeLibraryChangePublisher,
)
from substitute_backend.features.cube_library.application.icon_contract import (
    SUPPORTED_ICON_MEDIA_TYPES,
    build_cube_icon_url,
    public_icon_descriptor,
)
from substitute_backend.features.cube_library.application.services import (
    CubeLibraryGateway,
    CubeLibraryService,
    CubeLibraryServices,
)

__all__ = [
    "CATALOG_REVISION_CHANGED_REASON",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "SUPPORTED_ICON_MEDIA_TYPES",
    "CubeLibraryChangeMonitor",
    "CubeLibraryChangePublisher",
    "CubeLibraryGateway",
    "CubeLibraryService",
    "CubeLibraryServices",
    "build_cube_icon_url",
    "public_icon_descriptor",
]

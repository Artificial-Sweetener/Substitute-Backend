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
"""Inspect ComfyUI root requirement files for package attribution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from substitute_backend.features.environment_management.infrastructure.pip_inspector import (
    normalize_package_name,
)

from .custom_node_requirements import read_requirement_entries

_COMFY_REQUIREMENT_FILENAMES = ("requirements.txt", "requirements_versions.txt")


@dataclass(frozen=True)
class ComfyRequirement:
    """Describe one package requirement declared by ComfyUI itself."""

    package_name: str
    normalized_name: str
    requirement: str
    source_path: Path


class ComfyRequirementsScanner:
    """Scan ComfyUI-owned requirement files for direct package claims."""

    def __init__(self, comfy_root: Path) -> None:
        """Initialize the scanner with the active Comfy root."""

        self._comfy_root = comfy_root

    def scan(self) -> tuple[ComfyRequirement, ...]:
        """Return package requirements declared by ComfyUI root files."""

        requirements: list[ComfyRequirement] = []
        for requirements_file in self._requirement_files():
            for package_name, requirement in read_requirement_entries(requirements_file):
                requirements.append(
                    ComfyRequirement(
                        package_name=package_name,
                        normalized_name=normalize_package_name(package_name),
                        requirement=requirement,
                        source_path=requirements_file,
                    )
                )
        return tuple(requirements)

    def _requirement_files(self) -> tuple[Path, ...]:
        """Return existing ComfyUI root requirement files in stable order."""

        if not self._comfy_root.exists():
            return ()
        return tuple(
            path
            for filename in _COMFY_REQUIREMENT_FILENAMES
            if (path := self._comfy_root / filename).is_file()
        )

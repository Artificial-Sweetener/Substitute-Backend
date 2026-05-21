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
"""Inspect installed custom node requirements for package attribution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from substitute_backend.features.environment_management.infrastructure.pip_inspector import (
    normalize_package_name,
)

_REQUIREMENT_NAME_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.-]+)")


@dataclass(frozen=True)
class CustomNodeRequirement:
    """Describe one package requirement declared by an installed custom node."""

    package_name: str
    normalized_name: str
    requirement: str
    custom_node_name: str
    custom_node_path: Path
    source_path: Path


class CustomNodeRequirementsScanner:
    """Scan installed custom node folders for requirements files."""

    def __init__(self, custom_nodes_root: Path) -> None:
        """Initialize the scanner with a Comfy custom nodes root."""

        self._custom_nodes_root = custom_nodes_root

    def scan(self) -> tuple[CustomNodeRequirement, ...]:
        """Return package requirements declared by installed custom nodes."""

        if not self._custom_nodes_root.exists():
            return ()
        requirements: list[CustomNodeRequirement] = []
        for requirements_file in self._custom_nodes_root.glob("*/requirements.txt"):
            custom_node_path = requirements_file.parent
            for package_name, requirement in read_requirement_entries(requirements_file):
                requirements.append(
                    CustomNodeRequirement(
                        package_name=package_name,
                        normalized_name=normalize_package_name(package_name),
                        requirement=requirement,
                        custom_node_name=custom_node_path.name,
                        custom_node_path=custom_node_path,
                        source_path=requirements_file,
                    )
                )
        return tuple(requirements)


def read_requirement_entries(path: Path) -> tuple[tuple[str, str], ...]:
    """Read package names and original requirement specs from one file."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    requirements: list[tuple[str, str]] = []
    for line in lines:
        stripped = line.split("#", 1)[0].strip()
        if not stripped or stripped.startswith(("-", "http:", "https:", "git+")):
            continue
        match = _REQUIREMENT_NAME_PATTERN.match(stripped)
        if match is not None:
            requirements.append((match.group(1), stripped))
    return tuple(requirements)

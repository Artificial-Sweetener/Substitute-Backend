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
"""Inspect installed Python packages through the active interpreter's pip."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass

_NORMALIZE_PATTERN = re.compile(r"[-_.]+")


@dataclass(frozen=True)
class PipPackage:
    """Describe one raw package entry reported by pip."""

    name: str
    normalized_name: str
    version: str


class PipInspector:
    """Read installed package inventory from the active Python interpreter."""

    def __init__(
        self,
        *,
        python_executable: str = sys.executable,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Initialize pip execution policy."""

        self._python_executable = python_executable
        self._timeout_seconds = timeout_seconds

    def list_packages(self) -> tuple[PipPackage, ...]:
        """Return packages installed in the active interpreter environment."""

        completed = subprocess.run(
            [
                self._python_executable,
                "-m",
                "pip",
                "list",
                "--format=json",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=self._timeout_seconds,
        )
        payload = json.loads(completed.stdout)
        if not isinstance(payload, list):
            return ()
        packages: list[PipPackage] = []
        for raw_package in payload:
            if not isinstance(raw_package, dict):
                continue
            name = raw_package.get("name")
            version = raw_package.get("version")
            if not isinstance(name, str) or not isinstance(version, str):
                continue
            packages.append(
                PipPackage(
                    name=name,
                    normalized_name=normalize_package_name(name),
                    version=version,
                )
            )
        return tuple(packages)


def normalize_package_name(name: str) -> str:
    """Normalize one Python package name for dependency matching."""

    return _NORMALIZE_PATTERN.sub("-", name).lower().strip()

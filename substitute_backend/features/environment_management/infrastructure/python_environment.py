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
"""Read Python and Comfy host status from the running process."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from substitute_backend import ENVIRONMENT_MANAGEMENT_SCHEMA_VERSION
from substitute_backend.features.environment_management.domain.packages import (
    ComfyHostStatus,
    EnvironmentAvailability,
    EnvironmentStatus,
    PythonEnvironmentStatus,
)


@dataclass(frozen=True)
class PythonEnvironmentInspector:
    """Inspect the interpreter and process hosting Substitute BackEnd."""

    comfy_root: Path
    restart_supported: bool

    def get_status(self) -> EnvironmentStatus:
        """Return the active Python environment status."""

        return EnvironmentStatus(
            schema_version=ENVIRONMENT_MANAGEMENT_SCHEMA_VERSION,
            python=PythonEnvironmentStatus(
                executable=sys.executable,
                version=_python_version(),
                prefix=sys.prefix,
                base_prefix=sys.base_prefix,
                is_virtual_environment=sys.prefix != sys.base_prefix,
            ),
            comfy=ComfyHostStatus(
                root=str(self.comfy_root),
                process_id=os.getpid(),
                restart_supported=self.restart_supported,
            ),
            environment=EnvironmentAvailability(
                inventory_available=True,
                mutation_available=False,
            ),
        )


def _python_version() -> str:
    """Return a compact Python version string."""

    version = sys.version_info
    release = f"{version.major}.{version.minor}.{version.micro}"
    if version.releaselevel == "final":
        return release
    return f"{release}-{version.releaselevel}.{version.serial}"

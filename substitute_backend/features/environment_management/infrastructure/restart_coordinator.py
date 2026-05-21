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
"""Restart the current Comfy host process without accepting arbitrary commands."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class RestartSupport:
    """Describe whether this process can attempt a self restart."""

    supported: bool
    unavailable_reason: str | None = None


class RestartCoordinator:
    """Coordinate a host process restart using the current Python command."""

    def support(self) -> RestartSupport:
        """Return whether the current process has enough context to restart."""

        if not sys.executable:
            return RestartSupport(
                supported=False,
                unavailable_reason="The running Python executable could not be resolved.",
            )
        if not sys.argv:
            return RestartSupport(
                supported=False,
                unavailable_reason="The Comfy launch command could not be resolved.",
            )
        return RestartSupport(supported=True)

    def restart_process(self) -> None:
        """Replace this process with the current Python launch command."""

        command = _restart_command()
        os.execv(sys.executable, command)


def _restart_command() -> list[str]:
    """Return a Python exec command compatible with the current launch shape."""

    argv = sys.argv.copy()
    if not argv:
        return [sys.executable]
    if "--windows-standalone-build" in argv:
        argv.remove("--windows-standalone-build")
    if argv[0].endswith("__main__.py"):
        module_name = os.path.basename(os.path.dirname(argv[0]))
        return [sys.executable, "-m", module_name, *argv[1:]]
    return [sys.executable, *argv]

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
"""Coordinate BackEnd's complete liaison lifecycle with SugarCubes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


class RegistrationLike(Protocol):
    """Describe one idempotent SugarCubes observer registration."""

    def register(self) -> object:
        """Attempt observer registration without duplicating it."""


@dataclass(frozen=True)
class SugarCubesIntegrationServices:
    """Own BackEnd's output publication and queue-context liaison registrations."""

    cube_output_registration: RegistrationLike
    queue_context_registration: RegistrationLike

    def register(self) -> None:
        """Attempt every SugarCubes liaison registration."""

        self.cube_output_registration.register()
        self.queue_context_registration.register()

    def schedule_retry(self) -> None:
        """Retry after Comfy finishes the current asynchronous startup task."""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.call_soon(self.register)

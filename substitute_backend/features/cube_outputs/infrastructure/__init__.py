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
"""Infrastructure adapters for cube-output publishing."""

from substitute_backend.features.cube_outputs.infrastructure.prompt_server_publisher import (
    PromptServerCubeOutputPublisher,
)
from substitute_backend.features.cube_outputs.infrastructure.sugarcubes_observer import (
    SubstituteCubeOutputObserver,
)
from substitute_backend.features.cube_outputs.infrastructure.sugarcubes_observer_hook import (
    SugarCubesObserverHookResolver,
)
from substitute_backend.features.cube_outputs.infrastructure.sugarcubes_registration import (
    SugarCubesCubeOutputRegistration,
)

__all__ = [
    "PromptServerCubeOutputPublisher",
    "SubstituteCubeOutputObserver",
    "SugarCubesCubeOutputRegistration",
    "SugarCubesObserverHookResolver",
]

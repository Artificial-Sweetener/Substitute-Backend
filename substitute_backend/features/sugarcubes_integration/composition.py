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
"""Construct BackEnd's cohesive SugarCubes liaison service graph."""

from __future__ import annotations

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
from substitute_backend.features.prompt_queue.application.run_context_store import (
    SubstituteRunContextStore,
)
from substitute_backend.features.prompt_queue.infrastructure.sugarcubes_queue_context import (
    SugarCubesQueueContextObserver,
)
from substitute_backend.features.sugarcubes_integration.queue_context_registration import (
    SugarCubesQueueContextRegistration,
)
from substitute_backend.features.sugarcubes_integration.services import (
    SugarCubesIntegrationServices,
)
from substitute_backend.infrastructure.logging import get_logger


def build_sugarcubes_integration(
    *,
    prompt_server: object,
    run_context_store: SubstituteRunContextStore,
) -> SugarCubesIntegrationServices:
    """Build all BackEnd observers that participate in SugarCubes execution."""

    output_publisher = PromptServerCubeOutputPublisher(
        prompt_server=prompt_server,
        logger=get_logger("cube_outputs.publisher"),
    )
    output_observer = SubstituteCubeOutputObserver(
        publisher=output_publisher,
        logger=get_logger("cube_outputs.observer"),
        run_context_store=run_context_store,
    )
    return SugarCubesIntegrationServices(
        cube_output_registration=SugarCubesCubeOutputRegistration(
            hook_resolver=SugarCubesObserverHookResolver(
                logger=get_logger("cube_outputs.sugarcubes")
            ),
            observer=output_observer,
            logger=get_logger("cube_outputs.registration"),
        ),
        queue_context_registration=SugarCubesQueueContextRegistration(
            observer=SugarCubesQueueContextObserver(run_context_store=run_context_store),
            logger=get_logger("prompt_queue.sugarcubes_context"),
        ),
    )


__all__ = ["build_sugarcubes_integration"]

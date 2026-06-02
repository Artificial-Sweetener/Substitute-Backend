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
"""Domain models for the prompt queue facade."""

from substitute_backend.features.prompt_queue.domain.graph import (
    ApiPrompt,
    ComfyNode,
    InputMap,
    is_api_prompt,
    is_comfy_node_link,
)
from substitute_backend.features.prompt_queue.domain.optimization_report import (
    OptimizationReplacement,
    OptimizationReport,
)
from substitute_backend.features.prompt_queue.domain.queue_response import QueuePromptResult
from substitute_backend.features.prompt_queue.domain.run_context import (
    SubstituteRunContext,
    SubstituteSourceRoute,
    parse_substitute_run_context,
)

__all__ = [
    "ApiPrompt",
    "ComfyNode",
    "InputMap",
    "OptimizationReplacement",
    "OptimizationReport",
    "QueuePromptResult",
    "SubstituteRunContext",
    "SubstituteSourceRoute",
    "is_api_prompt",
    "is_comfy_node_link",
    "parse_substitute_run_context",
]

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
"""Infrastructure adapters for model-loading telemetry."""

from substitute_backend.features.model_loading.infrastructure.comfy_context import (
    ComfyExecutionContextReader,
    ComfyPromptGraphReader,
    ExecutionContextSnapshot,
)
from substitute_backend.features.model_loading.infrastructure.comfy_log_parser import (
    ComfyModelLoadLogObserver,
    ComfyModelLoadLogParser,
)
from substitute_backend.features.model_loading.infrastructure.comfy_model_patch import (
    ComfyModelLoadPatchInstaller,
)
from substitute_backend.features.model_loading.infrastructure.prompt_server_publisher import (
    PromptServerModelLoadPublisher,
)

__all__ = [
    "ComfyExecutionContextReader",
    "ComfyModelLoadLogObserver",
    "ComfyModelLoadLogParser",
    "ComfyModelLoadPatchInstaller",
    "ComfyPromptGraphReader",
    "ExecutionContextSnapshot",
    "PromptServerModelLoadPublisher",
]

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
"""Comfy execution-context adapter for model-loading telemetry."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from substitute_backend.features.model_loading.application.telemetry_service import (
    ModelLoadContext,
)


@dataclass(frozen=True)
class ExecutionContextSnapshot:
    """Capture the available Comfy execution context without Comfy imports."""

    prompt_id: str | None
    node_id: str | None

    def to_model_load_context(self) -> ModelLoadContext:
        """Return the application context equivalent."""

        return ModelLoadContext(
            prompt_id=self.prompt_id,
            node_id=self.node_id,
            display_node_id=self.node_id,
        )


class ComfyExecutionContextReader:
    """Read Comfy's current execution context when available."""

    def read(self) -> ModelLoadContext:
        """Return current prompt/node context, or an empty context outside execution."""

        try:
            utils_module = importlib.import_module("comfy_execution.utils")
        except ImportError:
            return ModelLoadContext(prompt_id=None, node_id=None)

        get_executing_context = getattr(utils_module, "get_executing_context", None)
        if not callable(get_executing_context):
            return ModelLoadContext(prompt_id=None, node_id=None)
        raw_context: Any = get_executing_context()
        if raw_context is None:
            return ModelLoadContext(prompt_id=None, node_id=None)
        prompt_id = getattr(raw_context, "prompt_id", None)
        node_id = getattr(raw_context, "node_id", None)
        return ExecutionContextSnapshot(
            prompt_id=prompt_id if isinstance(prompt_id, str) else None,
            node_id=node_id if isinstance(node_id, str) else None,
        ).to_model_load_context()


class ComfyPromptGraphReader:
    """Read the active Comfy prompt graph for one running prompt."""

    def read(self, prompt_id: str | None) -> Mapping[str, object] | None:
        """Return the active prompt graph for ``prompt_id`` when Comfy exposes it."""

        if prompt_id is None:
            return None
        try:
            server_module = importlib.import_module("server")
        except ImportError:
            return None

        prompt_server_class: Any = getattr(server_module, "PromptServer", None)
        prompt_server: Any = getattr(prompt_server_class, "instance", None)
        prompt_queue: Any = getattr(prompt_server, "prompt_queue", None)
        get_current_queue_volatile = getattr(prompt_queue, "get_current_queue_volatile", None)
        if not callable(get_current_queue_volatile):
            return None
        try:
            current_queue = get_current_queue_volatile()
        except Exception:
            return None
        if not isinstance(current_queue, tuple) or not current_queue:
            return None
        running_items = current_queue[0]
        if not isinstance(running_items, list | tuple):
            return None
        for item in running_items:
            graph = self._prompt_graph_from_queue_item(item, prompt_id)
            if graph is not None:
                return graph
        return None

    @staticmethod
    def _prompt_graph_from_queue_item(
        item: object,
        prompt_id: str,
    ) -> Mapping[str, object] | None:
        """Return the prompt graph from one Comfy queue item if it matches."""

        if not isinstance(item, list | tuple) or len(item) < 3:
            return None
        raw_prompt_id = item[1]
        prompt_graph = item[2]
        if raw_prompt_id != prompt_id or not isinstance(prompt_graph, Mapping):
            return None
        return prompt_graph

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
"""Adapter that mirrors Comfy's prompt queue semantics through Substitute BackEnd."""

from __future__ import annotations

import copy
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, runtime_checkable

from substitute_backend.features.prompt_queue.application.graph_optimizer import (
    PromptGraphOptimizer,
)
from substitute_backend.features.prompt_queue.domain.graph import is_api_prompt
from substitute_backend.features.prompt_queue.domain.optimization_report import (
    OptimizationReport,
)
from substitute_backend.features.prompt_queue.domain.queue_response import QueuePromptResult


class PromptQueueLike(Protocol):
    """Subset of Comfy prompt queue used by the backend queue facade."""

    def put(self, item: object) -> None:
        """Queue one validated Comfy prompt tuple."""


class NodeReplaceManagerLike(Protocol):
    """Subset of Comfy node replacement manager used before validation."""

    def apply_replacements(self, prompt: object) -> None:
        """Apply Comfy node replacements to the executable prompt."""


@runtime_checkable
class PromptServerRuntimeLike(Protocol):
    """PromptServer surface required to queue prompts like Comfy's `/prompt` route."""

    number: float
    prompt_queue: PromptQueueLike
    node_replace_manager: NodeReplaceManagerLike

    def trigger_on_prompt(self, json_data: dict[str, object]) -> dict[str, object]:
        """Run Comfy prompt hooks and return the mutated request payload."""


class ExecutionModuleLike(Protocol):
    """Subset of Comfy's execution module required for prompt validation."""

    SENSITIVE_EXTRA_DATA_KEYS: tuple[str, ...]

    def validate_prompt(
        self,
        prompt_id: str,
        prompt: object,
        partial_execution_list: object,
    ) -> Awaitable[tuple[bool, object, object, object]]:
        """Validate a prompt and return Comfy's validation tuple."""


class ComfyPromptQueueAdapter:
    """Queue prompts through Comfy while inserting backend graph optimization."""

    def __init__(
        self,
        *,
        prompt_server: PromptServerRuntimeLike,
        execution_module: ExecutionModuleLike,
        optimizer: PromptGraphOptimizer,
        logger: logging.Logger,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
        time_source: Callable[[], float] = time.time,
    ) -> None:
        """Initialize the adapter with Comfy runtime dependencies."""

        self._prompt_server = prompt_server
        self._execution = execution_module
        self._optimizer = optimizer
        self._logger = logger
        self._uuid_factory = uuid_factory
        self._time_source = time_source

    async def queue_prompt(self, request_payload: dict[str, object]) -> QueuePromptResult:
        """Queue one Comfy-compatible prompt request through Substitute BackEnd."""

        json_data = self._prompt_server.trigger_on_prompt(copy.deepcopy(request_payload))
        number = self._resolve_number(json_data)
        prompt = json_data.get("prompt")
        if prompt is None:
            return QueuePromptResult(
                payload={
                    "error": {
                        "type": "no_prompt",
                        "message": "No prompt provided",
                        "details": "No prompt provided",
                        "extra_info": {},
                    },
                    "node_errors": {},
                },
                status=400,
            )
        prompt_id = str(json_data.get("prompt_id", self._uuid_factory()))
        partial_execution_targets = json_data.get("partial_execution_targets")
        self._prompt_server.node_replace_manager.apply_replacements(prompt)
        prompt_for_queue, report = self._optimize_prompt(prompt)
        valid = await self._execution.validate_prompt(
            prompt_id,
            prompt_for_queue,
            partial_execution_targets,
        )
        if not valid[0]:
            self._logger.warning(
                "Invalid prompt rejected by Comfy validation.",
                extra={
                    "operation": "prompt_queue_validate",
                    "prompt_id": prompt_id,
                    "validation_error": str(valid[1]),
                },
            )
            return QueuePromptResult(
                payload={"error": valid[1], "node_errors": valid[3]},
                status=400,
            )
        extra_data = self._extra_data(json_data)
        client_id = json_data.get("client_id")
        if client_id is not None:
            extra_data["client_id"] = client_id
        sensitive: dict[str, object] = {}
        for sensitive_key in self._execution.SENSITIVE_EXTRA_DATA_KEYS:
            if sensitive_key in extra_data:
                sensitive[sensitive_key] = extra_data.pop(sensitive_key)
        extra_data["create_time"] = int(self._time_source() * 1000)
        self._prompt_server.prompt_queue.put(
            (number, prompt_id, prompt_for_queue, extra_data, valid[2], sensitive)
        )
        return QueuePromptResult(
            payload={
                "prompt_id": prompt_id,
                "number": number,
                "node_errors": valid[3],
                "substitute": {
                    "optimized": report.optimized,
                    "optimizationReport": report.to_payload(),
                },
            }
        )

    def _resolve_number(self, json_data: Mapping[str, object]) -> float:
        """Resolve Comfy queue number and preserve `front` behavior."""

        if "number" in json_data:
            return _number_from_value(json_data["number"])
        number = float(self._prompt_server.number)
        if json_data.get("front") is True:
            number = -number
        self._prompt_server.number = float(self._prompt_server.number) + 1
        return number

    def _optimize_prompt(self, prompt: object) -> tuple[object, OptimizationReport]:
        """Optimize a prompt if it has Comfy API prompt shape, otherwise preserve it."""

        if not is_api_prompt(prompt):
            return prompt, OptimizationReport.unchanged(0)
        try:
            return self._optimizer.optimize(prompt)
        except Exception as exc:
            self._logger.exception(
                "Prompt graph optimization failed; queueing original prompt.",
                extra={"operation": "prompt_queue_graph_optimize"},
            )
            return prompt, OptimizationReport.failed_open(len(prompt), str(exc))

    def _extra_data(self, json_data: Mapping[str, object]) -> dict[str, object]:
        """Return a mutable copy of Comfy extra data."""

        extra_data = json_data.get("extra_data")
        if not isinstance(extra_data, Mapping):
            return {}
        return {str(key): value for key, value in extra_data.items()}


def _number_from_value(value: object) -> float:
    """Convert Comfy queue number values into floats with explicit narrowing."""

    if isinstance(value, bool):
        msg = "Queue number must be numeric."
        raise TypeError(msg)
    if isinstance(value, int | float | str):
        return float(value)
    msg = "Queue number must be numeric."
    raise TypeError(msg)

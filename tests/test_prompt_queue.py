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
"""Tests for backend-owned Comfy prompt queueing and graph optimization."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import cast

from substitute_backend.features.prompt_queue.application import PromptGraphOptimizer
from substitute_backend.features.prompt_queue.domain.graph import ApiPrompt
from substitute_backend.features.prompt_queue.domain.optimization_report import OptimizationReport
from substitute_backend.features.prompt_queue.infrastructure.comfy_prompt_queue import (
    ComfyPromptQueueAdapter,
    ExecutionModuleLike,
    PromptServerRuntimeLike,
)


def test_graph_optimizer_dedupes_lora_schedule_branch_but_not_prompt_text() -> None:
    """Different prompt prose with the same extracted LoRA schedule should share LoRA nodes."""

    optimizer = PromptGraphOptimizer(logger=logging.getLogger("tests.prompt_queue.optimizer"))
    optimized, report = optimizer.optimize(_lora_prompt("cat", "dog"))

    assert report.optimized is True
    assert _node_ids_by_class(optimized, "PCLazyLoraLoader") == ["5"]
    assert _node_ids_by_class(optimized, "PCLazyTextEncode") == ["7", "8"]
    assert _inputs(optimized, "8")["clip"] == ["5", 1]
    assert _inputs(optimized, "8")["text"] == ["2", 0]


def test_graph_optimizer_dedupes_exact_text_conditioning() -> None:
    """Identical prompt prose should share both LoRA and text encode branches."""

    optimizer = PromptGraphOptimizer(logger=logging.getLogger("tests.prompt_queue.optimizer"))
    optimized, report = optimizer.optimize(_lora_prompt("cat", "cat"))

    assert report.optimized is True
    assert _node_ids_by_class(optimized, "PCLazyLoraLoader") == ["5"]
    assert _node_ids_by_class(optimized, "PCLazyTextEncode") == ["7"]
    assert _inputs(optimized, "9")["conditioning"] == ["7", 0]


def test_graph_optimizer_bypasses_empty_lora_scheduler_before_deduping_shared_prompt() -> None:
    """Shared positive prompts should leave one real LoRA scheduler, not one no-op branch."""

    optimizer = PromptGraphOptimizer(logger=logging.getLogger("tests.prompt_queue.optimizer"))
    optimized, report = optimizer.optimize(_shared_anima_prompt())

    assert report.optimized is True
    assert _node_ids_by_class(optimized, "PCLazyLoraLoader") == ["14"]
    assert set(_node_ids_by_class(optimized, "PCLazyTextEncode")) == {"7", "16"}
    assert {"8", "22", "43"}.isdisjoint(optimized)
    assert _inputs(optimized, "7")["clip"] == ["14", 1]
    assert _inputs(optimized, "16")["clip"] == ["14", 1]
    assert _inputs(optimized, "31")["negative"] == ["7", 0]
    assert _inputs(optimized, "31")["positive"] == ["16", 0]
    assert _inputs(optimized, "52")["negative"] == ["7", 0]
    assert _inputs(optimized, "52")["positive"] == ["16", 0]
    assert [replacement.kind for replacement in report.replacements].count(
        "empty_lora_passthrough"
    ) == 3


def test_comfy_queue_adapter_runs_hooks_and_replacements_before_optimization() -> None:
    """The backend facade should optimize the prompt Comfy will execute."""

    events: list[str] = []
    prompt_server = _PromptServer(events)
    execution = _Execution(events)
    adapter = ComfyPromptQueueAdapter(
        prompt_server=cast("PromptServerRuntimeLike", prompt_server),
        execution_module=cast("ExecutionModuleLike", execution),
        optimizer=PromptGraphOptimizer(logger=logging.getLogger("tests.prompt_queue.optimizer")),
        logger=logging.getLogger("tests.prompt_queue.adapter"),
        uuid_factory=lambda: uuid.UUID("12345678-1234-5678-1234-567812345678"),
        time_source=lambda: 123.456,
    )
    request = {
        "prompt": _lora_prompt("cat", "dog", second_lora_name="other"),
        "front": True,
        "client_id": "client-1",
        "extra_data": {
            "extra_pnginfo": {"workflow": {"nodes": []}, "sugar_script": "use cube"},
            "auth_token_comfy_org": "secret-token",
        },
    }

    result = asyncio.run(adapter.queue_prompt(request))

    assert events == ["trigger", "replace", "validate", "put"]
    assert result.status == 200
    assert result.payload["prompt_id"] == "12345678-1234-5678-1234-567812345678"
    assert result.payload["number"] == -10.0
    assert cast("dict[str, object]", result.payload["substitute"])["optimized"] is True
    queued = prompt_server.prompt_queue.items[0]
    assert queued[0] == -10.0
    assert queued[1] == "12345678-1234-5678-1234-567812345678"
    queued_prompt = cast("ApiPrompt", queued[2])
    assert _node_ids_by_class(queued_prompt, "PCLazyLoraLoader") == ["5"]
    queued_extra_data = cast("dict[str, object]", queued[3])
    queued_sensitive = cast("dict[str, object]", queued[5])
    assert queued_extra_data["client_id"] == "client-1"
    assert queued_extra_data["create_time"] == 123456
    assert "auth_token_comfy_org" not in queued_extra_data
    assert queued_sensitive == {"auth_token_comfy_org": "secret-token"}
    assert prompt_server.number == 11.0


def test_comfy_queue_adapter_preserves_comfy_validation_failure_shape() -> None:
    """Validation failures should keep Comfy's error and node error payload shape."""

    events: list[str] = []
    prompt_server = _PromptServer(events)
    execution = _Execution(events, valid=False)
    adapter = ComfyPromptQueueAdapter(
        prompt_server=cast("PromptServerRuntimeLike", prompt_server),
        execution_module=cast("ExecutionModuleLike", execution),
        optimizer=PromptGraphOptimizer(logger=logging.getLogger("tests.prompt_queue.optimizer")),
        logger=logging.getLogger("tests.prompt_queue.adapter"),
    )

    result = asyncio.run(adapter.queue_prompt({"prompt": _lora_prompt("cat", "dog")}))

    assert result.status == 400
    assert result.payload == {
        "error": {"type": "invalid_prompt", "message": "invalid"},
        "node_errors": {"1": "bad"},
    }
    assert prompt_server.prompt_queue.items == []


def test_comfy_queue_adapter_fails_open_after_optimizer_error() -> None:
    """Optimizer failures should queue the original post-replacement prompt."""

    events: list[str] = []
    prompt_server = _PromptServer(events)
    adapter = ComfyPromptQueueAdapter(
        prompt_server=cast("PromptServerRuntimeLike", prompt_server),
        execution_module=cast("ExecutionModuleLike", _Execution(events)),
        optimizer=_FailingOptimizer(),
        logger=logging.getLogger("tests.prompt_queue.adapter"),
    )

    result = asyncio.run(adapter.queue_prompt({"prompt": _lora_prompt("cat", "dog")}))

    substitute_payload = cast("dict[str, object]", result.payload["substitute"])
    report = cast("dict[str, object]", substitute_payload["optimizationReport"])
    assert substitute_payload["optimized"] is False
    assert report["failed"] is True
    queued_prompt = cast("ApiPrompt", prompt_server.prompt_queue.items[0][2])
    assert _node_ids_by_class(queued_prompt, "PCLazyLoraLoader") == [
        "5",
        "6",
    ]


def _lora_prompt(
    first_subject: str,
    second_subject: str,
    *,
    second_lora_name: str = "same",
) -> ApiPrompt:
    """Build a compact Prompt Control style API prompt fixture."""

    return {
        "0": {"class_type": "ModelAndClipProvider", "inputs": {"name": "base"}},
        "1": {
            "class_type": "PrimitiveStringMultiline",
            "inputs": {"value": f"{first_subject} <lora:same:1>"},
        },
        "2": {
            "class_type": "PrimitiveStringMultiline",
            "inputs": {"value": f"{second_subject} <lora:{second_lora_name}:1>"},
        },
        "3": {
            "class_type": "RegexExtract",
            "inputs": _regex_inputs(["1", 0], "<[^>]*>"),
        },
        "4": {
            "class_type": "RegexExtract",
            "inputs": _regex_inputs(["2", 0], "<[^>]*>"),
        },
        "5": {
            "class_type": "PCLazyLoraLoader",
            "inputs": {"model": ["0", 0], "clip": ["0", 1], "text": ["3", 0]},
        },
        "6": {
            "class_type": "PCLazyLoraLoader",
            "inputs": {"model": ["0", 0], "clip": ["0", 1], "text": ["4", 0]},
        },
        "7": {
            "class_type": "PCLazyTextEncode",
            "inputs": {"clip": ["5", 1], "text": ["1", 0]},
        },
        "8": {
            "class_type": "PCLazyTextEncode",
            "inputs": {"clip": ["6", 1], "text": ["2", 0]},
        },
        "9": {"class_type": "ConditioningSink", "inputs": {"conditioning": ["8", 0]}},
    }


def _shared_anima_prompt() -> ApiPrompt:
    """Build the observed Anima graph shape with three shared positive prompts."""

    return {
        "0": {"class_type": "ModelAndClipProvider", "inputs": {"name": "base"}},
        "1": {
            "class_type": "PrimitiveStringMultiline",
            "inputs": {"value": "low quality, bad anatomy"},
        },
        "2": {
            "class_type": "PrimitiveStringMultiline",
            "inputs": {"value": "1girl <lora:Anima\\anima-turbo-lora-v0.1:1.00>"},
        },
        "7": {
            "class_type": "PCLazyTextEncode",
            "inputs": {"clip": ["8", 1], "text": ["10", 0]},
        },
        "8": {
            "class_type": "PCLazyLoraLoader",
            "inputs": {"clip": ["14", 1], "model": ["14", 0], "text": ["9", 0]},
        },
        "9": {"class_type": "RegexExtract", "inputs": _regex_inputs(["1", 0], "<[^>]*>")},
        "10": {
            "class_type": "StringConcatenate",
            "inputs": {"delimiter": "", "string_a": "", "string_b": ["11", 0]},
        },
        "11": {
            "class_type": "RegexExtract",
            "inputs": _regex_inputs(["1", 0], "(?:^|>)([^<]+)(?=<|$)"),
        },
        "12": {
            "class_type": "RegexExtract",
            "inputs": _regex_inputs(["2", 0], "(?:^|>)([^<]+)(?=<|$)"),
        },
        "13": {"class_type": "RegexExtract", "inputs": _regex_inputs(["2", 0], "<[^>]*>")},
        "14": {
            "class_type": "PCLazyLoraLoader",
            "inputs": {"clip": ["0", 1], "model": ["0", 0], "text": ["13", 0]},
        },
        "15": {
            "class_type": "StringConcatenate",
            "inputs": {"delimiter": "", "string_a": "", "string_b": ["12", 0]},
        },
        "16": {
            "class_type": "PCLazyTextEncode",
            "inputs": {"clip": ["8", 1], "text": ["15", 0]},
        },
        "17": {
            "class_type": "SugarCubes.CubeOutput",
            "inputs": {"negative": ["7", 0], "positive": ["16", 0]},
        },
        "21": {
            "class_type": "PCLazyTextEncode",
            "inputs": {"clip": ["22", 1], "text": ["24", 0]},
        },
        "22": {
            "class_type": "PCLazyLoraLoader",
            "inputs": {"clip": ["28", 1], "model": ["28", 0], "text": ["23", 0]},
        },
        "23": {"class_type": "RegexExtract", "inputs": _regex_inputs(["1", 0], "<[^>]*>")},
        "24": {
            "class_type": "StringConcatenate",
            "inputs": {"delimiter": "", "string_a": "", "string_b": ["25", 0]},
        },
        "25": {
            "class_type": "RegexExtract",
            "inputs": _regex_inputs(["1", 0], "(?:^|>)([^<]+)(?=<|$)"),
        },
        "26": {
            "class_type": "RegexExtract",
            "inputs": _regex_inputs(["2", 0], "(?:^|>)([^<]+)(?=<|$)"),
        },
        "27": {"class_type": "RegexExtract", "inputs": _regex_inputs(["2", 0], "<[^>]*>")},
        "28": {
            "class_type": "PCLazyLoraLoader",
            "inputs": {"clip": ["0", 1], "model": ["0", 0], "text": ["27", 0]},
        },
        "29": {
            "class_type": "StringConcatenate",
            "inputs": {"delimiter": "", "string_a": "", "string_b": ["26", 0]},
        },
        "30": {
            "class_type": "PCLazyTextEncode",
            "inputs": {"clip": ["22", 1], "text": ["29", 0]},
        },
        "31": {
            "class_type": "SugarCubes.CubeOutput",
            "inputs": {"negative": ["21", 0], "positive": ["30", 0]},
        },
        "42": {
            "class_type": "PCLazyTextEncode",
            "inputs": {"clip": ["43", 1], "text": ["45", 0]},
        },
        "43": {
            "class_type": "PCLazyLoraLoader",
            "inputs": {"clip": ["49", 1], "model": ["49", 0], "text": ["44", 0]},
        },
        "44": {"class_type": "RegexExtract", "inputs": _regex_inputs(["1", 0], "<[^>]*>")},
        "45": {
            "class_type": "StringConcatenate",
            "inputs": {"delimiter": "", "string_a": "", "string_b": ["46", 0]},
        },
        "46": {
            "class_type": "RegexExtract",
            "inputs": _regex_inputs(["1", 0], "(?:^|>)([^<]+)(?=<|$)"),
        },
        "47": {
            "class_type": "RegexExtract",
            "inputs": _regex_inputs(["2", 0], "(?:^|>)([^<]+)(?=<|$)"),
        },
        "48": {"class_type": "RegexExtract", "inputs": _regex_inputs(["2", 0], "<[^>]*>")},
        "49": {
            "class_type": "PCLazyLoraLoader",
            "inputs": {"clip": ["0", 1], "model": ["0", 0], "text": ["48", 0]},
        },
        "50": {
            "class_type": "StringConcatenate",
            "inputs": {"delimiter": "", "string_a": "", "string_b": ["47", 0]},
        },
        "51": {
            "class_type": "PCLazyTextEncode",
            "inputs": {"clip": ["43", 1], "text": ["50", 0]},
        },
        "52": {
            "class_type": "SugarCubes.CubeOutput",
            "inputs": {"negative": ["42", 0], "positive": ["51", 0]},
        },
    }


def _regex_inputs(link: list[object], pattern: str) -> dict[str, object]:
    """Return observed RegexExtract inputs for optimizer fixtures."""

    return {
        "case_insensitive": True,
        "dotall": False,
        "group_index": 1,
        "mode": "All Matches",
        "multiline": False,
        "regex_pattern": pattern,
        "string": link,
    }


def _node_ids_by_class(prompt: ApiPrompt, class_type: str) -> list[str]:
    """Return sorted node ids for one class type."""

    return sorted(
        node_id for node_id, node in prompt.items() if node.get("class_type") == class_type
    )


def _inputs(prompt: ApiPrompt, node_id: str) -> dict[str, object]:
    """Return typed inputs for one test prompt node."""

    inputs = prompt[node_id]["inputs"]
    assert isinstance(inputs, dict)
    return inputs


class _PromptQueue:
    """Collect queued prompt tuples."""

    def __init__(self, events: list[str]) -> None:
        """Store event sink."""

        self.items: list[tuple[object, ...]] = []
        self._events = events

    def put(self, item: object) -> None:
        """Record one queue item."""

        self._events.append("put")
        self.items.append(cast("tuple[object, ...]", item))


class _NodeReplaceManager:
    """Mutate the prompt to prove replacements happen before optimization."""

    def __init__(self, events: list[str]) -> None:
        """Store event sink."""

        self._events = events

    def apply_replacements(self, prompt: object) -> None:
        """Replace the second LoRA token with the first token."""

        self._events.append("replace")
        api_prompt = cast("ApiPrompt", prompt)
        cast("dict[str, object]", api_prompt["2"]["inputs"])["value"] = "dog <lora:same:1>"


class _PromptServer:
    """PromptServer test double for queue adapter tests."""

    def __init__(self, events: list[str]) -> None:
        """Initialize PromptServer state."""

        self.number = 10.0
        self.prompt_queue = _PromptQueue(events)
        self.node_replace_manager = _NodeReplaceManager(events)
        self._events = events

    def trigger_on_prompt(self, json_data: dict[str, object]) -> dict[str, object]:
        """Record hook ordering and return the payload."""

        self._events.append("trigger")
        return json_data


class _Execution:
    """Execution module test double."""

    SENSITIVE_EXTRA_DATA_KEYS: tuple[str, ...] = ("auth_token_comfy_org",)

    def __init__(self, events: list[str], *, valid: bool = True) -> None:
        """Configure validation behavior."""

        self._events = events
        self._valid = valid

    async def validate_prompt(
        self,
        prompt_id: str,
        prompt: object,
        partial_execution_list: object,
    ) -> tuple[bool, object, object, object]:
        """Record validation and return a Comfy-shaped validation tuple."""

        _ = (prompt_id, prompt, partial_execution_list)
        self._events.append("validate")
        if not self._valid:
            return False, {"type": "invalid_prompt", "message": "invalid"}, [], {"1": "bad"}
        return True, None, ["9"], {}


class _FailingOptimizer(PromptGraphOptimizer):
    """Optimizer test double that always fails."""

    def __init__(self) -> None:
        """Skip normal logger initialization for the failing test double."""

    def optimize(self, prompt: ApiPrompt) -> tuple[ApiPrompt, OptimizationReport]:
        """Raise to exercise fail-open queueing."""

        _ = prompt
        msg = "boom"
        raise RuntimeError(msg)

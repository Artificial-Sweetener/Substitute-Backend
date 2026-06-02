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
from substitute_backend.features.prompt_queue.application.node_definitions import (
    NodeDefinition,
    NodeDefinitionProvider,
)
from substitute_backend.features.prompt_queue.application.run_context_store import (
    SubstituteRunContextStore,
)
from substitute_backend.features.prompt_queue.domain.graph import ApiPrompt
from substitute_backend.features.prompt_queue.domain.optimization_report import OptimizationReport
from substitute_backend.features.prompt_queue.domain.run_context import (
    SubstituteRunContext,
    SubstituteSourceRoute,
)
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


def test_graph_optimizer_collapses_parallel_identical_model_resource_streams() -> None:
    """Equivalent parallel model patch streams should share one canonical stream."""

    optimizer = _resource_optimizer()
    optimized, report = optimizer.optimize(
        {
            "1": _node("TestModelClipLoader", ckpt_name="base"),
            "2": _node("TestModelPatch", model=["1", 0], strength=0.7),
            "3": _node("TestModelClipLoader", ckpt_name="base"),
            "4": _node("TestModelPatch", model=["3", 0], strength=0.7),
            "5": _node("TestSampler", model=["2", 0]),
            "6": _node("TestSampler", model=["4", 0]),
        }
    )

    assert report.optimized is True
    assert _node_ids_by_class(optimized, "TestModelPatch") == ["2"]
    assert _node_ids_by_class(optimized, "TestModelClipLoader") == ["1"]
    assert _inputs(optimized, "6")["model"] == ["2", 0]
    assert [replacement.kind for replacement in report.replacements] == ["model_resource_stream"]


def test_graph_optimizer_collapses_parallel_identical_clip_resource_streams() -> None:
    """Equivalent parallel CLIP patch streams should share one canonical stream."""

    optimizer = _resource_optimizer()
    optimized, report = optimizer.optimize(
        {
            "1": _node("TestModelClipLoader", ckpt_name="base"),
            "2": _node("TestClipPatch", clip=["1", 1], layer=-2),
            "3": _node("TestModelClipLoader", ckpt_name="base"),
            "4": _node("TestClipPatch", clip=["3", 1], layer=-2),
            "5": _node("TestSampler", clip=["2", 0]),
            "6": _node("TestSampler", clip=["4", 0]),
        }
    )

    assert report.optimized is True
    assert _node_ids_by_class(optimized, "TestClipPatch") == ["2"]
    assert _node_ids_by_class(optimized, "TestModelClipLoader") == ["1"]
    assert _inputs(optimized, "6")["clip"] == ["2", 0]
    assert [replacement.kind for replacement in report.replacements] == ["clip_resource_stream"]


def test_graph_optimizer_collapses_parallel_identical_vae_resource_streams() -> None:
    """Equivalent parallel VAE patch streams should share one canonical stream."""

    optimizer = _resource_optimizer()
    optimized, report = optimizer.optimize(
        {
            "1": _node("TestVaeLoader", vae_name="base-vae"),
            "2": _node("TestVaePatch", vae=["1", 0], mode="tiled"),
            "3": _node("TestVaeLoader", vae_name="base-vae"),
            "4": _node("TestVaePatch", vae=["3", 0], mode="tiled"),
            "5": _node("TestVaeConsumer", vae=["2", 0]),
            "6": _node("TestVaeConsumer", vae=["4", 0]),
        }
    )

    assert report.optimized is True
    assert _node_ids_by_class(optimized, "TestVaePatch") == ["2"]
    assert _node_ids_by_class(optimized, "TestVaeLoader") == ["1"]
    assert _inputs(optimized, "6")["vae"] == ["2", 0]
    assert [replacement.kind for replacement in report.replacements] == ["vae_resource_stream"]


def test_graph_optimizer_keeps_resource_streams_with_different_loader_identity() -> None:
    """Matching patch literals should not collapse across different loaded resources."""

    optimizer = _resource_optimizer()
    optimized, report = optimizer.optimize(
        {
            "1": _node("TestModelClipLoader", ckpt_name="base-a"),
            "2": _node("TestModelPatch", model=["1", 0], strength=0.7),
            "3": _node("TestModelClipLoader", ckpt_name="base-b"),
            "4": _node("TestModelPatch", model=["3", 0], strength=0.7),
            "5": _node("TestSampler", model=["2", 0]),
            "6": _node("TestSampler", model=["4", 0]),
        }
    )

    assert report.optimized is False
    assert _node_ids_by_class(optimized, "TestModelPatch") == ["2", "4"]
    assert _inputs(optimized, "6")["model"] == ["4", 0]


def test_graph_optimizer_keeps_resource_streams_with_unknown_loader_roots() -> None:
    """Unknown roots should act as identity barriers even when downstream patches match."""

    optimizer = _resource_optimizer()
    optimized, report = optimizer.optimize(
        {
            "1": _node("TestUnknownLoader", ckpt_name="base"),
            "2": _node("TestModelPatch", model=["1", 0], strength=0.7),
            "3": _node("TestUnknownLoader", ckpt_name="base"),
            "4": _node("TestModelPatch", model=["3", 0], strength=0.7),
            "5": _node("TestSampler", model=["2", 0]),
            "6": _node("TestSampler", model=["4", 0]),
        }
    )

    assert report.optimized is False
    assert _node_ids_by_class(optimized, "TestModelPatch") == ["2", "4"]
    assert _inputs(optimized, "6")["model"] == ["4", 0]


def test_graph_optimizer_keeps_serial_duplicate_resource_patches() -> None:
    """A repeated authored patch chain should remain serial."""

    optimizer = _resource_optimizer()
    optimized, report = optimizer.optimize(
        {
            "1": _node("TestModelClipLoader", ckpt_name="base"),
            "2": _node("TestModelPatch", model=["1", 0], strength=0.7),
            "3": _node("TestModelPatch", model=["2", 0], strength=0.7),
            "4": _node("TestSampler", model=["3", 0]),
        }
    )

    assert report.optimized is False
    assert _node_ids_by_class(optimized, "TestModelPatch") == ["2", "3"]
    assert _inputs(optimized, "3")["model"] == ["2", 0]
    assert _inputs(optimized, "4")["model"] == ["3", 0]


def test_graph_optimizer_does_not_replace_duplicate_loader_only_branches() -> None:
    """Duplicate roots alone should not create an optimization replacement."""

    optimizer = _resource_optimizer()
    optimized, report = optimizer.optimize(
        {
            "1": _node("TestModelClipLoader", ckpt_name="base"),
            "2": _node("TestModelClipLoader", ckpt_name="base"),
            "3": _node("TestSampler", model=["1", 0]),
            "4": _node("TestSampler", model=["2", 0]),
        }
    )

    assert report.optimized is False
    assert _node_ids_by_class(optimized, "TestModelClipLoader") == ["1", "2"]
    assert _inputs(optimized, "4")["model"] == ["2", 0]


def test_graph_optimizer_does_not_replace_identical_work_nodes() -> None:
    """Sampler-like work nodes should not be deduped by the generic resource pass."""

    optimizer = _resource_optimizer()
    optimized, report = optimizer.optimize(
        {
            "1": _node("TestModelClipLoader", ckpt_name="base"),
            "2": _node("TestSampler", model=["1", 0], seed=123),
            "3": _node("TestSampler", model=["1", 0], seed=123),
            "4": _node("TestLatentSink", latent=["2", 0]),
            "5": _node("TestLatentSink", latent=["3", 0]),
        }
    )

    assert report.optimized is False
    assert _node_ids_by_class(optimized, "TestSampler") == ["2", "3"]
    assert _inputs(optimized, "5")["latent"] == ["3", 0]


def test_graph_optimizer_preserves_multi_output_resource_slot_indexes() -> None:
    """Multi-output resource nodes should rewrite each duplicate slot to the same slot."""

    optimizer = _resource_optimizer()
    optimized, report = optimizer.optimize(
        {
            "1": _node("TestModelClipLoader", ckpt_name="base"),
            "2": _node("TestLoraResource", model=["1", 0], clip=["1", 1], lora_name="same"),
            "3": _node("TestModelClipLoader", ckpt_name="base"),
            "4": _node("TestLoraResource", model=["3", 0], clip=["3", 1], lora_name="same"),
            "5": _node("TestSampler", model=["4", 0], clip=["4", 1]),
        }
    )

    assert report.optimized is True
    assert _node_ids_by_class(optimized, "TestLoraResource") == ["2"]
    assert _node_ids_by_class(optimized, "TestModelClipLoader") == ["1"]
    assert _inputs(optimized, "5")["model"] == ["2", 0]
    assert _inputs(optimized, "5")["clip"] == ["2", 1]
    assert [replacement.kind for replacement in report.replacements] == [
        "model_resource_stream",
        "clip_resource_stream",
    ]


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


def test_comfy_queue_adapter_stores_substitute_run_context_by_prompt_id() -> None:
    """Queue adapter should retain visual routing context for the returned prompt id."""

    events: list[str] = []
    prompt_server = _PromptServer(events)
    run_context_store = SubstituteRunContextStore(time_source=lambda: 123.0)
    adapter = ComfyPromptQueueAdapter(
        prompt_server=cast("PromptServerRuntimeLike", prompt_server),
        execution_module=cast("ExecutionModuleLike", _Execution(events)),
        optimizer=PromptGraphOptimizer(logger=logging.getLogger("tests.prompt_queue.optimizer")),
        logger=logging.getLogger("tests.prompt_queue.adapter"),
        run_context_store=run_context_store,
        uuid_factory=lambda: uuid.UUID("12345678-1234-5678-1234-567812345678"),
        time_source=lambda: 123.456,
    )

    asyncio.run(
        adapter.queue_prompt(
            {
                "prompt": _lora_prompt("cat", "dog"),
                "client_id": "client-1",
                "extra_data": {
                    "substitute": {
                        "schemaVersion": 1,
                        "workflowId": "wf-1",
                        "generationRunId": "run-1",
                        "clientId": "client-1",
                        "sources": {
                            "5": {
                                "sourceKey": "wf-1:5",
                                "sourceLabel": "CubeA",
                                "cubeAlias": "CubeA",
                            }
                        },
                    }
                },
            }
        )
    )

    context = run_context_store.resolve("12345678-1234-5678-1234-567812345678")
    assert context is not None
    assert context.workflow_id == "wf-1"
    assert context.generation_run_id == "run-1"
    assert context.client_id == "client-1"
    assert context.sources["5"].source_key == "wf-1:5"


def test_substitute_run_context_store_prunes_expired_and_bounded_contexts() -> None:
    """Run-context store should stay bounded and drop expired prompt state."""

    now = 100.0

    def time_source() -> float:
        return now

    store = SubstituteRunContextStore(
        max_contexts=1,
        expiry_seconds=10.0,
        time_source=time_source,
    )
    first_context = SubstituteRunContext(
        workflow_id="wf-1",
        generation_run_id="run-1",
        client_id="client-1",
        sources={
            "node-1": SubstituteSourceRoute(
                source_key="wf-1:node-1",
                source_label="Node 1",
                cube_alias="Node 1",
            )
        },
    )
    second_context = SubstituteRunContext(
        workflow_id="wf-2",
        generation_run_id="run-2",
        client_id="client-2",
        sources={
            "node-2": SubstituteSourceRoute(
                source_key="wf-2:node-2",
                source_label="Node 2",
                cube_alias="Node 2",
            )
        },
    )

    store.store(prompt_id="prompt-1", context=first_context, executable_prompt={})
    now = 101.0
    store.store(prompt_id="prompt-2", context=second_context, executable_prompt={})

    assert store.resolve("prompt-1") is None
    assert store.resolve("prompt-2") is second_context

    now = 112.0
    assert store.resolve("prompt-2") is None


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


def _resource_optimizer() -> PromptGraphOptimizer:
    """Return an optimizer with compact fake resource node definitions."""

    return PromptGraphOptimizer(
        logger=logging.getLogger("tests.prompt_queue.optimizer"),
        node_definitions=NodeDefinitionProvider(
            (
                NodeDefinition(
                    class_type="TestModelClipLoader",
                    output_types=("MODEL", "CLIP"),
                    input_types=(("ckpt_name", "STRING"),),
                ),
                NodeDefinition(
                    class_type="TestVaeLoader",
                    output_types=("VAE",),
                    input_types=(("vae_name", "STRING"),),
                ),
                NodeDefinition(
                    class_type="TestModelPatch",
                    output_types=("MODEL",),
                    input_types=(("model", "MODEL"), ("strength", "FLOAT")),
                ),
                NodeDefinition(
                    class_type="TestClipPatch",
                    output_types=("CLIP",),
                    input_types=(("clip", "CLIP"), ("layer", "INT")),
                ),
                NodeDefinition(
                    class_type="TestVaePatch",
                    output_types=("VAE",),
                    input_types=(("vae", "VAE"), ("mode", "STRING")),
                ),
                NodeDefinition(
                    class_type="TestLoraResource",
                    output_types=("MODEL", "CLIP"),
                    input_types=(
                        ("model", "MODEL"),
                        ("clip", "CLIP"),
                        ("lora_name", "STRING"),
                    ),
                ),
                NodeDefinition(
                    class_type="TestSampler",
                    output_types=("LATENT",),
                    input_types=(("model", "MODEL"), ("clip", "CLIP")),
                ),
                NodeDefinition(
                    class_type="TestVaeConsumer",
                    output_types=("IMAGE",),
                    input_types=(("vae", "VAE"),),
                ),
                NodeDefinition(
                    class_type="TestLatentSink",
                    output_types=("IMAGE",),
                    input_types=(("latent", "LATENT"),),
                ),
            )
        ),
    )


def _node(class_type: str, **inputs: object) -> dict[str, object]:
    """Return a compact API prompt node."""

    return {"class_type": class_type, "inputs": inputs}


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

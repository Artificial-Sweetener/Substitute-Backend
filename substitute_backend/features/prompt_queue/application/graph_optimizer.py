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
"""Conservative executable Comfy API prompt graph optimizer."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from collections.abc import Mapping

from substitute_backend.features.prompt_queue.domain.graph import (
    ApiPrompt,
    ComfyNode,
    InputMap,
    is_comfy_node_link,
)
from substitute_backend.features.prompt_queue.domain.optimization_report import (
    OptimizationReplacement,
    OptimizationReport,
)
from substitute_backend.features.prompt_queue.infrastructure.node_signature_registry import (
    evaluate_string_output,
    is_allowlisted_node_class,
    optimization_kind,
    should_preserve_when_string_eval_fails,
)

type FrozenJson = (
    str
    | int
    | float
    | bool
    | None
    | tuple["FrozenJson", ...]
    | tuple[tuple[str, "FrozenJson"], ...]
)
type NodeSignature = tuple[object, ...]


class PromptGraphOptimizer:
    """Deduplicate allowlisted pure structures in executable Comfy API prompts."""

    def __init__(self, logger: logging.Logger) -> None:
        """Initialize the optimizer with diagnostic logging."""

        self._logger = logger

    def optimize(self, prompt: ApiPrompt) -> tuple[ApiPrompt, OptimizationReport]:
        """Return an optimized prompt copy and a report of graph rewrites."""

        optimized_prompt: ApiPrompt = copy.deepcopy(prompt)
        original_node_count = len(optimized_prompt)
        replacements: list[OptimizationReplacement] = []
        self._bypass_empty_lora_loaders(optimized_prompt, replacements)
        canonical_by_signature: dict[NodeSignature, str] = {}
        memo: dict[str, NodeSignature | None] = {}
        for node_id in _ordered_node_ids(optimized_prompt):
            if node_id not in optimized_prompt:
                continue
            signature = self._signature_for_node(
                optimized_prompt,
                node_id,
                memo=memo,
                visiting=set(),
            )
            if signature is None:
                continue
            canonical_node_id = canonical_by_signature.get(signature)
            if canonical_node_id is None or canonical_node_id not in optimized_prompt:
                canonical_by_signature[signature] = node_id
                continue
            node = optimized_prompt[node_id]
            class_type = str(node.get("class_type", ""))
            self._replace_links(
                optimized_prompt,
                duplicate_node_id=node_id,
                canonical_node_id=canonical_node_id,
            )
            if _has_remaining_references(optimized_prompt, node_id):
                continue
            del optimized_prompt[node_id]
            replacement = OptimizationReplacement(
                kind=optimization_kind(class_type),
                class_type=class_type,
                duplicate_node_id=node_id,
                canonical_node_id=canonical_node_id,
                signature_hash=_signature_hash(signature),
            )
            replacements.append(replacement)
            self._logger.debug(
                "Interned duplicate executable prompt node.",
                extra={
                    "operation": "prompt_queue_graph_optimize",
                    "optimization_kind": replacement.kind,
                    "duplicate_node_id": node_id,
                    "canonical_node_id": canonical_node_id,
                    "class_type": class_type,
                    "signature_hash": replacement.signature_hash,
                },
            )
        return optimized_prompt, OptimizationReport(
            optimized=bool(replacements),
            original_node_count=original_node_count,
            optimized_node_count=len(optimized_prompt),
            replacements=tuple(replacements),
        )

    def _bypass_empty_lora_loaders(
        self,
        prompt: ApiPrompt,
        replacements: list[OptimizationReplacement],
    ) -> None:
        """Remove Prompt Control LoRA schedulers whose schedule text is empty.

        ``PCLazyLoraLoader`` expands to a pass-through model/clip pair when its
        parsed schedule contains no LoRA tags. Rewiring those nodes before the
        duplicate pass lets the real positive LoRA branch dedupe across graph
        segments instead of preserving one no-op negative branch.
        """

        for node_id in _ordered_node_ids(prompt):
            node = prompt.get(node_id)
            if node is None or node.get("class_type") not in {
                "PCLazyLoraLoader",
                "PCLazyLoraLoaderAdvanced",
            }:
                continue
            inputs = _node_inputs(node)
            if self._resolve_string_value(prompt, inputs.get("text"), visiting={node_id}) != "":
                continue
            model_input = inputs.get("model")
            clip_input = inputs.get("clip")
            if model_input is None or clip_input is None:
                continue
            if not _has_only_bypassable_lora_references(prompt, node_id):
                continue
            self._replace_output_links(
                prompt,
                duplicate_node_id=node_id,
                output_replacements={0: model_input, 1: clip_input},
            )
            if _has_remaining_references(prompt, node_id):
                continue
            class_type = str(node["class_type"])
            del prompt[node_id]
            replacement = OptimizationReplacement(
                kind="empty_lora_passthrough",
                class_type=class_type,
                duplicate_node_id=node_id,
                canonical_node_id=_passthrough_target_label(model_input, clip_input),
                signature_hash=_signature_hash(
                    (
                        "empty_lora_passthrough",
                        class_type,
                        _freeze_json(model_input),
                        _freeze_json(clip_input),
                    )
                ),
            )
            replacements.append(replacement)
            self._logger.debug(
                "Bypassed empty executable prompt LoRA scheduler.",
                extra={
                    "operation": "prompt_queue_graph_optimize",
                    "optimization_kind": replacement.kind,
                    "duplicate_node_id": node_id,
                    "canonical_node_id": replacement.canonical_node_id,
                    "class_type": class_type,
                    "signature_hash": replacement.signature_hash,
                },
            )

    def _signature_for_node(
        self,
        prompt: ApiPrompt,
        node_id: str,
        *,
        memo: dict[str, NodeSignature | None],
        visiting: set[str],
    ) -> NodeSignature | None:
        """Return a recursive signature for one allowlisted node."""

        if node_id in memo:
            return memo[node_id]
        if node_id in visiting:
            return None
        node = prompt.get(node_id)
        if node is None:
            memo[node_id] = None
            return None
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or not is_allowlisted_node_class(class_type):
            memo[node_id] = None
            return None
        visiting.add(node_id)
        evaluated = self._evaluated_string_output(
            prompt,
            node_id,
            memo=memo,
            visiting=visiting,
        )
        if evaluated is None and should_preserve_when_string_eval_fails(node):
            visiting.remove(node_id)
            memo[node_id] = None
            return None
        inputs = _node_inputs(node)
        if evaluated is not None and class_type in {
            "PrimitiveString",
            "PrimitiveStringMultiline",
            "RegexExtract",
            "StringConcatenate",
        }:
            literal_inputs: tuple[tuple[str, FrozenJson], ...] = ()
            linked_inputs: tuple[tuple[str, tuple[object, ...]], ...] = ()
        else:
            literal_inputs = _literal_inputs(inputs)
            linked_inputs = self._linked_inputs(prompt, inputs, memo=memo, visiting=visiting)
        visiting.remove(node_id)
        signature: NodeSignature = (
            "node",
            class_type,
            ("options", _node_options(node)),
            ("evaluatedOutput", evaluated),
            ("literals", literal_inputs),
            ("links", linked_inputs),
        )
        memo[node_id] = signature
        return signature

    def _evaluated_string_output(
        self,
        prompt: ApiPrompt,
        node_id: str,
        *,
        memo: dict[str, NodeSignature | None],
        visiting: set[str],
    ) -> str | None:
        """Evaluate one supported string node output for stronger dedupe."""

        node = prompt[node_id]

        def resolve_link(source_node_id: str, output_slot: int) -> str | None:
            if output_slot != 0 or source_node_id in visiting:
                return None
            source_node = prompt.get(source_node_id)
            if source_node is None:
                return None
            return evaluate_string_output(
                source_node,
                lambda nested_id, nested_slot: resolve_nested_link(
                    nested_id,
                    nested_slot,
                    source_node_id,
                ),
            )

        def resolve_nested_link(
            nested_id: str,
            nested_slot: int,
            owner_id: str,
        ) -> str | None:
            if nested_slot != 0 or nested_id in visiting or nested_id == owner_id:
                return None
            nested_node = prompt.get(nested_id)
            if nested_node is None:
                return None
            return evaluate_string_output(nested_node, resolve_link)

        _ = memo
        return evaluate_string_output(node, resolve_link)

    def _resolve_string_value(
        self,
        prompt: ApiPrompt,
        value: object,
        *,
        visiting: set[str],
    ) -> str | None:
        """Resolve a supported literal or linked string value."""

        if isinstance(value, str):
            return value
        if not is_comfy_node_link(value):
            return None
        source_node_id = value[0]
        output_slot = value[1]
        if not isinstance(source_node_id, str) or output_slot != 0 or source_node_id in visiting:
            return None
        source_node = prompt.get(source_node_id)
        if source_node is None:
            return None

        def resolve_link(nested_id: str, nested_slot: int) -> str | None:
            return self._resolve_string_value(
                prompt,
                [nested_id, nested_slot],
                visiting=visiting | {source_node_id},
            )

        return evaluate_string_output(source_node, resolve_link)

    def _linked_inputs(
        self,
        prompt: ApiPrompt,
        inputs: InputMap,
        *,
        memo: dict[str, NodeSignature | None],
        visiting: set[str],
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        """Return canonical signatures for linked inputs."""

        links: list[tuple[str, tuple[object, ...]]] = []
        for input_name, value in inputs.items():
            if not is_comfy_node_link(value):
                continue
            source_node_id = value[0]
            output_slot = value[1]
            if not isinstance(source_node_id, str) or not isinstance(output_slot, int):
                continue
            upstream_signature = self._signature_for_node(
                prompt,
                source_node_id,
                memo=memo,
                visiting=visiting,
            )
            if upstream_signature is None:
                links.append((input_name, ("identity", source_node_id, output_slot)))
            else:
                links.append((input_name, ("signature", upstream_signature, output_slot)))
        return tuple(sorted(links, key=lambda item: item[0]))

    def _replace_links(
        self,
        prompt: ApiPrompt,
        *,
        duplicate_node_id: str,
        canonical_node_id: str,
    ) -> None:
        """Replace every input link to one duplicate node."""

        for node in prompt.values():
            for input_name, value in list(_node_inputs(node).items()):
                if is_comfy_node_link(value) and value[0] == duplicate_node_id:
                    output_slot = value[1]
                    if isinstance(output_slot, int):
                        _node_inputs(node)[input_name] = [canonical_node_id, output_slot]

    def _replace_output_links(
        self,
        prompt: ApiPrompt,
        *,
        duplicate_node_id: str,
        output_replacements: Mapping[int, object],
    ) -> None:
        """Replace links to one node with slot-specific replacement inputs."""

        for node in prompt.values():
            for input_name, value in list(_node_inputs(node).items()):
                if is_comfy_node_link(value) and value[0] == duplicate_node_id:
                    output_slot = value[1]
                    if not isinstance(output_slot, int):
                        continue
                    replacement = output_replacements.get(output_slot)
                    if replacement is not None:
                        _node_inputs(node)[input_name] = copy.deepcopy(replacement)


def _node_inputs(node: ComfyNode) -> InputMap:
    """Return a mutable node input mapping."""

    inputs = node.setdefault("inputs", {})
    if not isinstance(inputs, dict):
        msg = "Comfy API prompt node has invalid inputs."
        raise TypeError(msg)
    return inputs


def _literal_inputs(inputs: Mapping[str, object]) -> tuple[tuple[str, FrozenJson], ...]:
    """Return normalized literal input values."""

    return tuple(
        sorted(
            (name, _freeze_json(value))
            for name, value in inputs.items()
            if not is_comfy_node_link(value)
        )
    )


def _node_options(node: Mapping[str, object]) -> FrozenJson:
    """Return non-metadata node options that affect execution identity."""

    return _freeze_json(
        {key: value for key, value in node.items() if key not in {"class_type", "inputs", "_meta"}}
    )


def _freeze_json(value: object) -> FrozenJson:
    """Convert JSON-like values into hashable signature data."""

    if isinstance(value, Mapping):
        return tuple(
            sorted((str(key), _freeze_json(item_value)) for key, item_value in value.items())
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _ordered_node_ids(prompt: ApiPrompt) -> tuple[str, ...]:
    """Return prompt node ids in Comfy-stable numeric order where possible."""

    return tuple(sorted(prompt, key=_node_sort_key))


def _node_sort_key(node_id: str) -> tuple[int, int | str]:
    """Sort numeric Comfy ids before lexical non-numeric ids."""

    try:
        return (0, int(node_id))
    except ValueError:
        return (1, node_id)


def _has_remaining_references(prompt: ApiPrompt, node_id: str) -> bool:
    """Return whether any prompt input still references one node id."""

    return any(
        is_comfy_node_link(value) and value[0] == node_id
        for node in prompt.values()
        for value in _node_inputs(node).values()
    )


def _has_only_bypassable_lora_references(prompt: ApiPrompt, node_id: str) -> bool:
    """Return whether all references to a LoRA scheduler are model/clip outputs."""

    for node in prompt.values():
        for value in _node_inputs(node).values():
            if is_comfy_node_link(value) and value[0] == node_id and value[1] not in {0, 1}:
                return False
    return True


def _passthrough_target_label(model_input: object, clip_input: object) -> str:
    """Return a compact report target for one pass-through rewrite."""

    if (
        is_comfy_node_link(model_input)
        and is_comfy_node_link(clip_input)
        and model_input[0] == clip_input[0]
        and isinstance(model_input[0], str)
    ):
        return model_input[0]
    return "<passthrough>"


def _signature_hash(signature: NodeSignature) -> str:
    """Return a short deterministic hash for diagnostics."""

    return hashlib.sha256(repr(signature).encode("utf-8")).hexdigest()[:12]

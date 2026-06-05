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
import logging
import time

from substitute_backend.features.prompt_queue.application.graph_signature_builder import (
    GraphSignatureBuilder,
)
from substitute_backend.features.prompt_queue.application.node_definitions import (
    NodeDefinitionProvider,
)
from substitute_backend.features.prompt_queue.application.optimization_context import (
    FrozenJson,
    NodeSignature,
    PromptOptimizationContext,
    freeze_json,
    literal_inputs,
    node_inputs,
    node_options,
    signature_hash,
)
from substitute_backend.features.prompt_queue.application.resource_policy import (
    ResourceOptimizationPolicy,
)
from substitute_backend.features.prompt_queue.domain.graph import (
    ApiPrompt,
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


class PromptGraphOptimizer:
    """Deduplicate safe structures in executable Comfy API prompts."""

    def __init__(
        self,
        logger: logging.Logger,
        node_definitions: NodeDefinitionProvider | None = None,
        resource_policy: ResourceOptimizationPolicy | None = None,
    ) -> None:
        """Initialize the optimizer with cached metadata and diagnostic logging."""

        self._logger = logger
        self._node_definitions = node_definitions or NodeDefinitionProvider()
        self._resource_policy = resource_policy or ResourceOptimizationPolicy()

    def optimize(self, prompt: ApiPrompt) -> tuple[ApiPrompt, OptimizationReport]:
        """Return an optimized prompt copy and a report of graph rewrites."""

        started_at = time.perf_counter()
        optimized_prompt: ApiPrompt = copy.deepcopy(prompt)
        original_node_count = len(optimized_prompt)
        replacements: list[OptimizationReplacement] = []
        context = PromptOptimizationContext(
            optimized_prompt,
            node_definitions=self._node_definitions,
        )
        try:
            self._bypass_empty_lora_loaders(context, replacements)
            self._intern_prompt_control_nodes(context, replacements)
            self._intern_resource_streams(context, replacements)
            return optimized_prompt, OptimizationReport(
                optimized=bool(replacements),
                original_node_count=original_node_count,
                optimized_node_count=len(optimized_prompt),
                replacements=tuple(replacements),
            )
        finally:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            self._logger.debug(
                "Executable prompt graph optimization finished.",
                extra={
                    "operation": "prompt_queue_graph_optimize",
                    "original_node_count": original_node_count,
                    "optimized_node_count": len(optimized_prompt),
                    "replacement_count": len(replacements),
                    "elapsed_ms": round(elapsed_ms, 3),
                },
            )

    def _bypass_empty_lora_loaders(
        self,
        context: PromptOptimizationContext,
        replacements: list[OptimizationReplacement],
    ) -> None:
        """Remove Prompt Control LoRA schedulers whose schedule text is empty."""

        for node_id in context.ordered_node_ids():
            node = context.node(node_id)
            if node is None or node.get("class_type") not in {
                "PCLazyLoraLoader",
                "PCLazyLoraLoaderAdvanced",
            }:
                continue
            inputs = node_inputs(node)
            if self._resolve_string_value(context, inputs.get("text"), visiting={node_id}) != "":
                continue
            model_input = inputs.get("model")
            clip_input = inputs.get("clip")
            if model_input is None or clip_input is None:
                continue
            if not self._has_only_bypassable_lora_references(context, node_id):
                continue
            context.replace_output_links(
                duplicate_node_id=node_id,
                output_replacements={0: model_input, 1: clip_input},
            )
            if context.has_remaining_references(node_id):
                continue
            class_type = str(node["class_type"])
            context.remove_node(node_id)
            replacement = OptimizationReplacement(
                kind="empty_lora_passthrough",
                class_type=class_type,
                duplicate_node_id=node_id,
                canonical_node_id=_passthrough_target_label(model_input, clip_input),
                signature_hash=signature_hash(
                    (
                        "empty_lora_passthrough",
                        class_type,
                        freeze_json(model_input),
                        freeze_json(clip_input),
                    )
                ),
            )
            replacements.append(replacement)
            self._log_replacement("Bypassed empty executable prompt LoRA scheduler.", replacement)

    def _intern_prompt_control_nodes(
        self,
        context: PromptOptimizationContext,
        replacements: list[OptimizationReplacement],
    ) -> None:
        """Intern existing Prompt-Control and pure string allowlisted nodes."""

        canonical_by_signature: dict[NodeSignature, str] = {}
        memo: dict[str, NodeSignature | None] = {}
        for node_id in context.ordered_node_ids():
            if context.node(node_id) is None:
                continue
            signature = self._signature_for_prompt_control_node(
                context,
                node_id,
                memo=memo,
                visiting=set(),
            )
            if signature is None:
                continue
            canonical_node_id = canonical_by_signature.get(signature)
            if canonical_node_id is None or context.node(canonical_node_id) is None:
                canonical_by_signature[signature] = node_id
                continue
            node = context.node(node_id)
            if node is None:
                continue
            class_type = str(node.get("class_type", ""))
            context.replace_node_links(
                duplicate_node_id=node_id,
                canonical_node_id=canonical_node_id,
            )
            if context.has_remaining_references(node_id):
                continue
            context.remove_node(node_id)
            replacement = OptimizationReplacement(
                kind=optimization_kind(class_type),
                class_type=class_type,
                duplicate_node_id=node_id,
                canonical_node_id=canonical_node_id,
                signature_hash=signature_hash(signature),
            )
            replacements.append(replacement)
            self._log_replacement("Interned duplicate executable prompt node.", replacement)

    def _intern_resource_streams(
        self,
        context: PromptOptimizationContext,
        replacements: list[OptimizationReplacement],
    ) -> None:
        """Intern duplicate parallel model, CLIP, VAE, and conditioning streams."""

        builder = GraphSignatureBuilder(context, self._resource_policy)
        canonical_by_signature: dict[NodeSignature, tuple[str, int]] = {}
        for node_id in context.ordered_node_ids():
            if context.node(node_id) is None:
                continue
            for output_slot in context.output_slots(node_id):
                if context.node(node_id) is None:
                    break
                eligible, reason = self._resource_policy.intern_output_decision(
                    context,
                    node_id,
                    output_slot,
                )
                _ = reason
                if not eligible:
                    continue
                resource_signature = builder.signature_for_output(node_id, output_slot)
                if resource_signature.is_barrier:
                    continue
                if resource_signature.is_root:
                    continue
                canonical = canonical_by_signature.get(resource_signature.value)
                if canonical is None or context.node(canonical[0]) is None:
                    canonical_by_signature[resource_signature.value] = (node_id, output_slot)
                    continue
                canonical_node_id, canonical_output_slot = canonical
                if not context.has_output_references(node_id, output_slot):
                    continue
                rewritten = context.replace_output_slot_links(
                    duplicate_node_id=node_id,
                    duplicate_output_slot=output_slot,
                    canonical_node_id=canonical_node_id,
                    canonical_output_slot=canonical_output_slot,
                )
                if rewritten == 0:
                    continue
                node = context.node(node_id)
                if node is None:
                    continue
                class_type = str(node.get("class_type", ""))
                replacement = OptimizationReplacement(
                    kind=self._resource_policy.replacement_kind(resource_signature.output_type),
                    class_type=class_type,
                    duplicate_node_id=node_id,
                    canonical_node_id=canonical_node_id,
                    signature_hash=signature_hash(resource_signature.value),
                )
                replacements.append(replacement)
                self._log_replacement("Interned duplicate resource stream output.", replacement)
                if not context.has_remaining_references(node_id):
                    upstream_node_ids = tuple(
                        source_node_id
                        for _, source_node_id, _ in context.linked_input_sources(node_id)
                    )
                    context.remove_node(node_id)
                    for upstream_node_id in upstream_node_ids:
                        self._remove_unreferenced_resource_node(context, upstream_node_id)

    def _remove_unreferenced_resource_node(
        self,
        context: PromptOptimizationContext,
        node_id: str,
    ) -> None:
        """Remove unreferenced safe resource ancestors after stream interning."""

        if context.node(node_id) is None or context.has_remaining_references(node_id):
            return
        if not self._resource_policy.can_remove_unreferenced_node(context, node_id):
            return
        upstream_node_ids = tuple(
            source_node_id for _, source_node_id, _ in context.linked_input_sources(node_id)
        )
        context.remove_node(node_id)
        for upstream_node_id in upstream_node_ids:
            self._remove_unreferenced_resource_node(context, upstream_node_id)

    def _signature_for_prompt_control_node(
        self,
        context: PromptOptimizationContext,
        node_id: str,
        *,
        memo: dict[str, NodeSignature | None],
        visiting: set[str],
    ) -> NodeSignature | None:
        """Return a recursive signature for one allowlisted Prompt-Control node."""

        if node_id in memo:
            return memo[node_id]
        if node_id in visiting:
            return None
        node = context.node(node_id)
        if node is None:
            memo[node_id] = None
            return None
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or not is_allowlisted_node_class(class_type):
            memo[node_id] = None
            return None
        visiting.add(node_id)
        evaluated = self._evaluated_string_output(
            context,
            node_id,
            memo=memo,
            visiting=visiting,
        )
        if evaluated is None and should_preserve_when_string_eval_fails(node):
            visiting.remove(node_id)
            memo[node_id] = None
            return None
        inputs = node_inputs(node)
        if evaluated is not None and class_type in {
            "PrimitiveString",
            "PrimitiveStringMultiline",
            "RegexExtract",
            "StringConcatenate",
        }:
            literal_input_values: tuple[tuple[str, FrozenJson], ...] = ()
            linked_input_values: tuple[tuple[str, tuple[object, ...]], ...] = ()
        else:
            literal_input_values = literal_inputs(inputs)
            linked_input_values = self._linked_prompt_control_inputs(
                context,
                inputs,
                memo=memo,
                visiting=visiting,
            )
        visiting.remove(node_id)
        signature: NodeSignature = (
            "node",
            class_type,
            ("options", node_options(node)),
            ("evaluatedOutput", evaluated),
            ("literals", literal_input_values),
            ("links", linked_input_values),
        )
        memo[node_id] = signature
        return signature

    def _evaluated_string_output(
        self,
        context: PromptOptimizationContext,
        node_id: str,
        *,
        memo: dict[str, NodeSignature | None],
        visiting: set[str],
    ) -> str | None:
        """Evaluate one supported string node output for stronger dedupe."""

        node = context.prompt[node_id]

        def resolve_link(source_node_id: str, output_slot: int) -> str | None:
            if output_slot != 0 or source_node_id in visiting:
                return None
            source_node = context.node(source_node_id)
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
            nested_node = context.node(nested_id)
            if nested_node is None:
                return None
            return evaluate_string_output(nested_node, resolve_link)

        _ = memo
        return evaluate_string_output(node, resolve_link)

    def _resolve_string_value(
        self,
        context: PromptOptimizationContext,
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
        if (
            not isinstance(source_node_id, str)
            or not isinstance(output_slot, int)
            or output_slot != 0
            or source_node_id in visiting
        ):
            return None
        source_node = context.node(source_node_id)
        if source_node is None:
            return None

        def resolve_link(nested_id: str, nested_slot: int) -> str | None:
            return self._resolve_string_value(
                context,
                [nested_id, nested_slot],
                visiting=visiting | {source_node_id},
            )

        return evaluate_string_output(source_node, resolve_link)

    def _linked_prompt_control_inputs(
        self,
        context: PromptOptimizationContext,
        inputs: dict[str, object],
        *,
        memo: dict[str, NodeSignature | None],
        visiting: set[str],
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        """Return canonical signatures for linked Prompt-Control inputs."""

        links: list[tuple[str, tuple[object, ...]]] = []
        for input_name, value in inputs.items():
            if not is_comfy_node_link(value):
                continue
            source_node_id = value[0]
            output_slot = value[1]
            if not isinstance(source_node_id, str) or not isinstance(output_slot, int):
                continue
            upstream_signature = self._signature_for_prompt_control_node(
                context,
                source_node_id,
                memo=memo,
                visiting=visiting,
            )
            if upstream_signature is None:
                links.append((input_name, ("identity", source_node_id, output_slot)))
            else:
                links.append((input_name, ("signature", upstream_signature, output_slot)))
        return tuple(sorted(links, key=lambda item: item[0]))

    def _has_only_bypassable_lora_references(
        self,
        context: PromptOptimizationContext,
        node_id: str,
    ) -> bool:
        """Return whether all references to a LoRA scheduler are model/clip outputs."""

        for node in context.prompt.values():
            for value in node_inputs(node).values():
                if is_comfy_node_link(value) and value[0] == node_id and value[1] not in {0, 1}:
                    return False
        return True

    def _log_replacement(self, message: str, replacement: OptimizationReplacement) -> None:
        """Log one graph rewrite with stable diagnostic fields."""

        self._logger.debug(
            message,
            extra={
                "operation": "prompt_queue_graph_optimize",
                "optimization_kind": replacement.kind,
                "duplicate_node_id": replacement.duplicate_node_id,
                "canonical_node_id": replacement.canonical_node_id,
                "class_type": replacement.class_type,
                "signature_hash": replacement.signature_hash,
            },
        )


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

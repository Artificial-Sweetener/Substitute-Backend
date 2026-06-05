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
"""Recursive signatures for safe resource stream outputs."""

from __future__ import annotations

from substitute_backend.features.prompt_queue.application.optimization_context import (
    NodeSignature,
    OutputAddress,
    PromptOptimizationContext,
    ResourceSignature,
    literal_inputs,
    node_options,
)
from substitute_backend.features.prompt_queue.application.resource_policy import (
    PromptTypeClass,
    ResourceOptimizationPolicy,
)
from substitute_backend.features.prompt_queue.domain.graph import is_comfy_node_link


class GraphSignatureBuilder:
    """Build memoized resource output signatures for one optimized prompt."""

    def __init__(
        self,
        context: PromptOptimizationContext,
        policy: ResourceOptimizationPolicy,
    ) -> None:
        """Store collaborators for recursive signature construction."""

        self._context = context
        self._policy = policy

    def signature_for_output(
        self,
        node_id: str,
        output_slot: int,
        *,
        visiting: set[OutputAddress] | None = None,
    ) -> ResourceSignature:
        """Return a deterministic signature for one node output."""

        address = (node_id, output_slot)
        cached = self._context.resource_signature_memo.get(address)
        if cached is not None:
            return cached
        active = visiting if visiting is not None else set()
        if address in active:
            msg = f"Cycle detected while signing prompt output {node_id}:{output_slot}."
            raise ValueError(msg)
        active.add(address)
        signature = self._build_signature(node_id, output_slot, visiting=active)
        active.remove(address)
        self._context.resource_signature_memo[address] = signature
        return signature

    def _build_signature(
        self,
        node_id: str,
        output_slot: int,
        *,
        visiting: set[OutputAddress],
    ) -> ResourceSignature:
        """Build one uncached output signature."""

        node = self._context.node(node_id)
        class_type = self._context.class_type(node_id)
        output_type = self._context.output_type(node_id, output_slot)
        if node is None or class_type is None:
            return self._barrier_signature(node_id, output_slot, output_type)
        output_class = self._policy.output_type_class(output_type)
        if output_class not in {PromptTypeClass.RESOURCE, PromptTypeClass.PURE_VALUE}:
            return self._barrier_signature(node_id, output_slot, output_type)
        if not self._policy.can_sign_output(self._context, node_id, output_slot):
            return self._barrier_signature(node_id, output_slot, output_type)
        linked_inputs = self._context.linked_input_sources(node_id)
        if not linked_inputs:
            if not self._policy.root_identity_is_visible(self._context, node_id):
                return self._barrier_signature(node_id, output_slot, output_type)
            root_signature_value = (
                self._signature_kind(output_class, is_root=True),
                class_type,
                ("outputSlot", output_slot),
                ("outputType", output_type),
                ("options", node_options(node)),
                ("literals", literal_inputs(self._context.inputs_for_node(node_id))),
            )
            return ResourceSignature(
                value=root_signature_value,
                output_type=output_type,
                is_root=output_class is PromptTypeClass.RESOURCE,
            )
        transformer_signature_value: NodeSignature = (
            self._signature_kind(output_class, is_root=False),
            class_type,
            ("outputSlot", output_slot),
            ("outputType", output_type),
            ("options", node_options(node)),
            ("literals", literal_inputs(self._context.inputs_for_node(node_id))),
            ("links", self._linked_input_signatures(node_id, visiting=visiting)),
        )
        return ResourceSignature(value=transformer_signature_value, output_type=output_type)

    def _signature_kind(self, output_class: PromptTypeClass, *, is_root: bool) -> str:
        """Return a signature namespace for one safe output class."""

        if output_class is PromptTypeClass.PURE_VALUE:
            return "pure_value_root_output" if is_root else "pure_value_output"
        return "resource_root_output" if is_root else "resource_output"

    def _linked_input_signatures(
        self,
        node_id: str,
        *,
        visiting: set[OutputAddress],
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        """Return recursive signatures for linked resource inputs."""

        linked_inputs: list[tuple[str, tuple[object, ...]]] = []
        for input_name, value in self._context.inputs_for_node(node_id).items():
            if not is_comfy_node_link(value):
                continue
            source_node_id = value[0]
            output_slot = value[1]
            if not isinstance(source_node_id, str) or not isinstance(output_slot, int):
                continue
            upstream = self.signature_for_output(
                source_node_id,
                output_slot,
                visiting=visiting,
            )
            if upstream.is_barrier:
                linked_inputs.append(
                    (input_name, ("identity", source_node_id, output_slot, upstream.output_type))
                )
            else:
                linked_inputs.append((input_name, ("signature", upstream.value)))
        return tuple(sorted(linked_inputs, key=lambda item: item[0]))

    def _barrier_signature(
        self,
        node_id: str,
        output_slot: int,
        output_type: str | None,
    ) -> ResourceSignature:
        """Return an identity signature that prevents cross-stream collapse."""

        return ResourceSignature(
            value=("barrier_output", node_id, output_slot, output_type),
            output_type=output_type,
            is_barrier=True,
        )

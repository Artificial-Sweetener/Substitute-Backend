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
"""Conservative safety policy for generic resource stream optimization."""

from __future__ import annotations

from enum import StrEnum

from substitute_backend.features.prompt_queue.application.optimization_context import (
    PromptOptimizationContext,
    literal_inputs,
    node_options,
)
from substitute_backend.features.prompt_queue.domain.graph import is_comfy_node_link


class ResourceOptimizationPolicy:
    """Classify prompt nodes for safe queue-time resource stream interning."""

    _RESOURCE_OUTPUT_TYPES = frozenset(
        {"MODEL", "CLIP", "VAE", "CONDITIONING", "CONDITIONING_BATCH", "HOOKS"}
    )
    _PURE_VALUE_OUTPUT_TYPES = frozenset(
        {
            "STRING",
            "INT",
            "INTEGER",
            "FLOAT",
            "NUMBER",
            "BOOLEAN",
            "BOOL",
            "COMBO",
            "CHOICE",
        }
    )
    _WORK_OUTPUT_TYPES = frozenset(
        {
            "IMAGE",
            "LATENT",
            "MASK",
            "AUDIO",
            "VIDEO",
            "VIDEO_FRAMES",
            "PREVIEW",
            "UI",
        }
    )

    def is_resource_output_type(self, output_type: str | None) -> bool:
        """Return whether an output type is a reusable resource object."""

        tokens = normalized_type_tokens(output_type)
        return bool(tokens) and tokens <= self._RESOURCE_OUTPUT_TYPES

    def is_pure_value_output_type(self, output_type: str | None) -> bool:
        """Return whether an output type is pure prompt/config data."""

        tokens = normalized_type_tokens(output_type)
        return bool(tokens) and tokens <= self._PURE_VALUE_OUTPUT_TYPES

    def is_work_output_type(self, output_type: str | None) -> bool:
        """Return whether an output type represents generated work or side effects."""

        tokens = normalized_type_tokens(output_type)
        return bool(tokens) and bool(tokens & self._WORK_OUTPUT_TYPES)

    def output_type_class(self, output_type: str | None) -> PromptTypeClass:
        """Classify one Comfy type string for graph-signature policy decisions."""

        tokens = normalized_type_tokens(output_type)
        if not tokens:
            return PromptTypeClass.UNKNOWN
        if tokens & self._WORK_OUTPUT_TYPES:
            return PromptTypeClass.WORK
        if tokens <= self._RESOURCE_OUTPUT_TYPES:
            return PromptTypeClass.RESOURCE
        if tokens <= self._PURE_VALUE_OUTPUT_TYPES:
            return PromptTypeClass.PURE_VALUE
        return PromptTypeClass.UNKNOWN

    def replacement_kind(self, output_type: str | None) -> str:
        """Return the report kind for one optimized resource output."""

        tokens = normalized_type_tokens(output_type)
        if tokens == frozenset({"MODEL"}):
            return "model_resource_stream"
        if tokens == frozenset({"CLIP"}):
            return "clip_resource_stream"
        if tokens == frozenset({"VAE"}):
            return "vae_resource_stream"
        if tokens <= frozenset({"CONDITIONING", "CONDITIONING_BATCH"}):
            return "conditioning_resource_stream"
        return "resource_stream"

    def has_safe_signature_surface(self, context: PromptOptimizationContext, node_id: str) -> bool:
        """Return whether one node can safely appear in a structural signature."""

        definition = context.definition_for_node(node_id)
        class_type = context.class_type(node_id)
        if definition is None or class_type is None:
            return False
        if definition.output_node or definition.hidden_inputs:
            return False
        if not definition.output_types:
            return False
        return all(
            self.output_type_class(output_type)
            in {PromptTypeClass.RESOURCE, PromptTypeClass.PURE_VALUE}
            for output_type in definition.output_types
        )

    def can_sign_output(
        self,
        context: PromptOptimizationContext,
        node_id: str,
        output_slot: int,
    ) -> bool:
        """Return whether one output may contribute a structural identity."""

        if not self.has_safe_signature_surface(context, node_id):
            return False
        output_class = self.output_type_class(context.output_type(node_id, output_slot))
        if output_class not in {PromptTypeClass.RESOURCE, PromptTypeClass.PURE_VALUE}:
            return False
        return all(
            self.output_type_class(context.output_type(source_node_id, source_output_slot))
            in {PromptTypeClass.RESOURCE, PromptTypeClass.PURE_VALUE}
            for _, source_node_id, source_output_slot in context.linked_input_sources(node_id)
        )

    def can_participate(self, context: PromptOptimizationContext, node_id: str) -> bool:
        """Return whether one node has a safe resource-only type surface."""

        definition = context.definition_for_node(node_id)
        if definition is None or not self.has_safe_signature_surface(context, node_id):
            return False
        return all(
            self.output_type_class(output_type) is PromptTypeClass.RESOURCE
            for output_type in definition.output_types
        )

    def is_resource_root(self, context: PromptOptimizationContext, node_id: str) -> bool:
        """Return whether one safe resource node starts a stream."""

        if not self.can_participate(context, node_id):
            return False
        return not context.linked_input_sources(node_id)

    def root_identity_is_visible(self, context: PromptOptimizationContext, node_id: str) -> bool:
        """Return whether a root exposes prompt literals that identify the loaded resource."""

        node = context.node(node_id)
        if node is None:
            return False
        inputs = context.inputs_for_node(node_id)
        if any(is_comfy_node_link(value) for value in inputs.values()):
            return False
        return bool(literal_inputs(inputs)) or node_options(node) != ()

    def is_resource_transformer(self, context: PromptOptimizationContext, node_id: str) -> bool:
        """Return whether one node transforms resources plus pure config inputs."""

        if not self.can_participate(context, node_id):
            return False
        links = context.linked_input_sources(node_id)
        if not links:
            return False
        return all(
            self.output_type_class(context.output_type(source_node_id, output_slot))
            in {PromptTypeClass.RESOURCE, PromptTypeClass.PURE_VALUE}
            for _, source_node_id, output_slot in links
        )

    def can_intern_output(
        self,
        context: PromptOptimizationContext,
        node_id: str,
        output_slot: int,
    ) -> bool:
        """Return whether a node output can be a duplicate stream replacement target."""

        eligible, _reason = self.intern_output_decision(context, node_id, output_slot)
        return eligible

    def intern_output_decision(
        self,
        context: PromptOptimizationContext,
        node_id: str,
        output_slot: int,
    ) -> tuple[bool, str]:
        """Return rewrite eligibility and a trace-friendly decision reason."""

        definition = context.definition_for_node(node_id)
        class_type = context.class_type(node_id)
        if definition is None or class_type is None:
            return False, "missing_definition"
        if definition.output_node:
            return False, "output_node"
        if definition.hidden_inputs:
            return False, "hidden_inputs"
        if not definition.output_types:
            return False, "missing_output_types"
        output_type = context.output_type(node_id, output_slot)
        output_class = self.output_type_class(output_type)
        if output_class is PromptTypeClass.WORK:
            return False, "work_output"
        if output_class is PromptTypeClass.UNKNOWN:
            return False, "unknown_output_type"
        if output_class is PromptTypeClass.PURE_VALUE:
            return False, "pure_value_not_rewrite_target"
        links = context.linked_input_sources(node_id)
        if not links:
            return False, "resource_root_not_rewrite_target"
        for _input_name, source_node_id, source_output_slot in links:
            source_class = self.output_type_class(
                context.output_type(source_node_id, source_output_slot)
            )
            if source_class is PromptTypeClass.WORK:
                return False, "linked_work_input"
            if source_class is PromptTypeClass.UNKNOWN:
                return False, "linked_unknown_input"
        return True, "eligible"

    def can_remove_unreferenced_node(
        self,
        context: PromptOptimizationContext,
        node_id: str,
    ) -> bool:
        """Return whether one unreferenced node is safe resource/config cleanup."""

        if not self.has_safe_signature_surface(context, node_id):
            return False
        return all(
            self.output_type_class(context.output_type(source_node_id, output_slot))
            in {PromptTypeClass.RESOURCE, PromptTypeClass.PURE_VALUE}
            for _, source_node_id, output_slot in context.linked_input_sources(node_id)
        )


class PromptTypeClass(StrEnum):
    """Classify normalized Comfy value types for graph optimization safety."""

    RESOURCE = "resource"
    PURE_VALUE = "pure_value"
    WORK = "work"
    UNKNOWN = "unknown"


def normalized_type_tokens(type_name: str | None) -> frozenset[str]:
    """Return normalized tokens from Comfy's comma-separated type strings."""

    if type_name is None:
        return frozenset()
    return frozenset(token.strip().upper() for token in type_name.split(",") if token.strip())

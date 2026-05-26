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

from substitute_backend.features.prompt_queue.application.optimization_context import (
    PromptOptimizationContext,
    literal_inputs,
    node_options,
)
from substitute_backend.features.prompt_queue.domain.graph import is_comfy_node_link


class ResourceOptimizationPolicy:
    """Classify prompt nodes for safe queue-time resource stream interning."""

    _RESOURCE_OUTPUT_TYPES = frozenset({"MODEL", "CLIP", "VAE", "CONDITIONING", "HOOKS"})
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
    _UNSAFE_CLASS_TOKENS = frozenset(
        {
            "sampler",
            "sample",
            "detailer",
            "detector",
            "segment",
            "preview",
            "save",
            "display",
            "output",
            "image",
            "latent",
            "mask",
            "decode",
            "encode",
            "download",
            "upload",
            "webcam",
            "video",
            "audio",
        }
    )

    def is_resource_output_type(self, output_type: str | None) -> bool:
        """Return whether an output type is a reusable resource object."""

        return output_type in self._RESOURCE_OUTPUT_TYPES

    def replacement_kind(self, output_type: str | None) -> str:
        """Return the report kind for one optimized resource output."""

        if output_type == "MODEL":
            return "model_resource_stream"
        if output_type == "CLIP":
            return "clip_resource_stream"
        if output_type == "VAE":
            return "vae_resource_stream"
        if output_type == "CONDITIONING":
            return "conditioning_resource_stream"
        return "resource_stream"

    def can_participate(self, context: PromptOptimizationContext, node_id: str) -> bool:
        """Return whether one node has a safe resource-only type surface."""

        definition = context.definition_for_node(node_id)
        class_type = context.class_type(node_id)
        if definition is None or class_type is None:
            return False
        if definition.output_node or definition.hidden_inputs:
            return False
        if not definition.output_types:
            return False
        normalized_outputs = tuple(output_type.upper() for output_type in definition.output_types)
        if any(output_type in self._WORK_OUTPUT_TYPES for output_type in normalized_outputs):
            return False
        if not all(
            output_type in self._RESOURCE_OUTPUT_TYPES for output_type in normalized_outputs
        ):
            return False
        lowered_class_type = class_type.lower()
        return not any(token in lowered_class_type for token in self._UNSAFE_CLASS_TOKENS)

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
        """Return whether one node transforms only linked resources plus literals."""

        if not self.can_participate(context, node_id):
            return False
        links = context.linked_input_sources(node_id)
        if not links:
            return False
        return all(
            self.is_resource_output_type(context.output_type(source_node_id, output_slot))
            for _, source_node_id, output_slot in links
        )

    def can_intern_output(
        self,
        context: PromptOptimizationContext,
        node_id: str,
        output_slot: int,
    ) -> bool:
        """Return whether a node output can be a duplicate stream replacement target."""

        output_type = context.output_type(node_id, output_slot)
        return self.is_resource_output_type(output_type) and self.is_resource_transformer(
            context, node_id
        )

    def can_remove_unreferenced_node(
        self,
        context: PromptOptimizationContext,
        node_id: str,
    ) -> bool:
        """Return whether one unreferenced node is safe to remove as resource cleanup."""

        return self.can_participate(context, node_id)

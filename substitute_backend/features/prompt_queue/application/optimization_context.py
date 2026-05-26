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
"""Mutable prompt graph context used by optimizer passes."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from substitute_backend.features.prompt_queue.application.node_definitions import (
    NodeDefinition,
    NodeDefinitionProvider,
)
from substitute_backend.features.prompt_queue.domain.graph import (
    ApiPrompt,
    ComfyNode,
    InputMap,
    is_comfy_node_link,
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
type OutputAddress = tuple[str, int]


@dataclass(frozen=True)
class ResourceSignature:
    """Store one output signature and its safety classification."""

    value: NodeSignature
    output_type: str | None
    is_barrier: bool = False
    is_root: bool = False


class PromptOptimizationContext:
    """Own prompt graph indexes and mutation helpers for one optimization run."""

    def __init__(
        self,
        prompt: ApiPrompt,
        node_definitions: NodeDefinitionProvider,
    ) -> None:
        """Initialize context around a mutable optimized prompt."""

        self.prompt = prompt
        self.node_definitions = node_definitions
        self.resource_signature_memo: dict[OutputAddress, ResourceSignature] = {}

    def ordered_node_ids(self) -> tuple[str, ...]:
        """Return prompt node ids in Comfy-stable numeric order where possible."""

        return tuple(sorted(self.prompt, key=_node_sort_key))

    def node(self, node_id: str) -> ComfyNode | None:
        """Return one prompt node if it still exists."""

        return self.prompt.get(node_id)

    def class_type(self, node_id: str) -> str | None:
        """Return one node's class type."""

        node = self.node(node_id)
        if node is None:
            return None
        class_type = node.get("class_type")
        return class_type if isinstance(class_type, str) else None

    def inputs_for_node(self, node_id: str) -> InputMap:
        """Return a mutable input map for one node id."""

        node = self.prompt[node_id]
        return node_inputs(node)

    def definition_for_node(self, node_id: str) -> NodeDefinition | None:
        """Return cached type metadata for one node."""

        class_type = self.class_type(node_id)
        if class_type is None:
            return None
        return self.node_definitions.definition_for_class(class_type)

    def output_type(self, node_id: str, output_slot: int) -> str | None:
        """Return the declared output type for a node output slot."""

        definition = self.definition_for_node(node_id)
        if definition is None or output_slot < 0 or output_slot >= len(definition.output_types):
            return None
        return definition.output_types[output_slot]

    def output_slots(self, node_id: str) -> tuple[int, ...]:
        """Return known output slots for one node."""

        definition = self.definition_for_node(node_id)
        if definition is not None and definition.output_types:
            return tuple(range(len(definition.output_types)))
        referenced_slots: set[int] = set()
        for node in self.prompt.values():
            for value in node_inputs(node).values():
                if not is_comfy_node_link(value) or value[0] != node_id:
                    continue
                output_slot = value[1]
                if isinstance(output_slot, int):
                    referenced_slots.add(output_slot)
        return tuple(sorted(referenced_slots))

    def linked_input_sources(self, node_id: str) -> tuple[tuple[str, str, int], ...]:
        """Return linked input names and source output addresses for one node."""

        links: list[tuple[str, str, int]] = []
        for input_name, value in self.inputs_for_node(node_id).items():
            if not is_comfy_node_link(value):
                continue
            source_node_id = value[0]
            output_slot = value[1]
            if isinstance(source_node_id, str) and isinstance(output_slot, int):
                links.append((input_name, source_node_id, output_slot))
        return tuple(sorted(links, key=lambda item: item[0]))

    def has_remaining_references(self, node_id: str) -> bool:
        """Return whether any prompt input still references one node id."""

        return any(
            is_comfy_node_link(value) and value[0] == node_id
            for node in self.prompt.values()
            for value in node_inputs(node).values()
        )

    def has_output_references(self, node_id: str, output_slot: int) -> bool:
        """Return whether any prompt input references one exact output slot."""

        return any(
            is_comfy_node_link(value) and value[0] == node_id and value[1] == output_slot
            for node in self.prompt.values()
            for value in node_inputs(node).values()
        )

    def replace_node_links(self, *, duplicate_node_id: str, canonical_node_id: str) -> int:
        """Replace every input link to one duplicate node and return the rewrite count."""

        rewrite_count = 0
        for node in self.prompt.values():
            for input_name, value in list(node_inputs(node).items()):
                if is_comfy_node_link(value) and value[0] == duplicate_node_id:
                    node_inputs(node)[input_name] = [canonical_node_id, value[1]]
                    rewrite_count += 1
        return rewrite_count

    def replace_output_links(
        self,
        *,
        duplicate_node_id: str,
        output_replacements: Mapping[int, object],
    ) -> int:
        """Replace links to one node with slot-specific replacement inputs."""

        rewrite_count = 0
        for node in self.prompt.values():
            for input_name, value in list(node_inputs(node).items()):
                if not is_comfy_node_link(value) or value[0] != duplicate_node_id:
                    continue
                output_slot = value[1]
                if not isinstance(output_slot, int):
                    continue
                replacement = output_replacements.get(output_slot)
                if replacement is None:
                    continue
                node_inputs(node)[input_name] = copy.deepcopy(replacement)
                rewrite_count += 1
        return rewrite_count

    def replace_output_slot_links(
        self,
        *,
        duplicate_node_id: str,
        duplicate_output_slot: int,
        canonical_node_id: str,
        canonical_output_slot: int,
    ) -> int:
        """Rewrite consumers of one duplicate output slot to the canonical slot."""

        rewrite_count = 0
        for node in self.prompt.values():
            for input_name, value in list(node_inputs(node).items()):
                if (
                    is_comfy_node_link(value)
                    and value[0] == duplicate_node_id
                    and value[1] == duplicate_output_slot
                ):
                    node_inputs(node)[input_name] = [canonical_node_id, canonical_output_slot]
                    rewrite_count += 1
        return rewrite_count

    def remove_node(self, node_id: str) -> None:
        """Remove one node from the optimized prompt and clear stale signature cache entries."""

        del self.prompt[node_id]
        stale_addresses = [
            address for address in self.resource_signature_memo if address[0] == node_id
        ]
        for address in stale_addresses:
            del self.resource_signature_memo[address]


def node_inputs(node: ComfyNode) -> InputMap:
    """Return a mutable node input mapping."""

    inputs = node.setdefault("inputs", {})
    if not isinstance(inputs, dict):
        msg = "Comfy API prompt node has invalid inputs."
        raise TypeError(msg)
    return inputs


def literal_inputs(inputs: Mapping[str, object]) -> tuple[tuple[str, FrozenJson], ...]:
    """Return normalized literal input values."""

    return tuple(
        sorted(
            (name, freeze_json(value))
            for name, value in inputs.items()
            if not is_comfy_node_link(value)
        )
    )


def node_options(node: Mapping[str, object]) -> FrozenJson:
    """Return non-metadata node options that affect execution identity."""

    return freeze_json(
        {
            key: value
            for key, value in node.items()
            if key
            not in {
                "class_type",
                "inputs",
                "_meta",
                "outputs",
                "output",
                "output_types",
                "input_types",
                "definitions",
            }
        }
    )


def freeze_json(value: object) -> FrozenJson:
    """Convert JSON-like values into hashable signature data."""

    if isinstance(value, Mapping):
        return tuple(
            sorted((str(key), freeze_json(item_value)) for key, item_value in value.items())
        )
    if isinstance(value, list | tuple):
        return tuple(freeze_json(item) for item in value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return json.dumps(value, sort_keys=True, default=str)


def signature_hash(signature: NodeSignature) -> str:
    """Return a short deterministic hash for diagnostics and report payloads."""

    return hashlib.sha256(repr(signature).encode("utf-8")).hexdigest()[:12]


def _node_sort_key(node_id: str) -> tuple[int, int | str]:
    """Sort numeric Comfy ids before lexical non-numeric ids."""

    try:
        return (0, int(node_id))
    except ValueError:
        return (1, node_id)

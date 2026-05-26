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
"""Best-effort cached Comfy node definitions for prompt queue optimization."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import cast

from substitute_backend.features.prompt_queue.application.node_definitions import (
    NodeDefinition,
    NodeDefinitionProvider,
)


def load_comfy_node_definitions(logger: logging.Logger) -> NodeDefinitionProvider:
    """Load cached node type metadata from Comfy's already-registered node classes."""

    try:
        import nodes  # type: ignore[import-not-found]
    except ImportError:
        return NodeDefinitionProvider()
    node_class_mappings = getattr(nodes, "NODE_CLASS_MAPPINGS", {})
    if not isinstance(node_class_mappings, Mapping):
        return NodeDefinitionProvider()
    definitions = [
        _definition_from_node_class(class_type, node_class, logger)
        for class_type, node_class in node_class_mappings.items()
        if isinstance(class_type, str)
    ]
    logger.debug(
        "Cached Comfy node definitions for prompt optimization.",
        extra={
            "operation": "prompt_queue_node_definitions_cache",
            "definition_count": len(definitions),
        },
    )
    return NodeDefinitionProvider(definitions)


def _definition_from_node_class(
    class_type: str,
    node_class: object,
    logger: logging.Logger,
) -> NodeDefinition:
    """Return cached metadata for one Comfy node class."""

    input_types, hidden_inputs = _input_metadata(class_type, node_class, logger)
    category_value = getattr(node_class, "CATEGORY", None)
    category = category_value if isinstance(category_value, str) else None
    return NodeDefinition(
        class_type=class_type,
        output_types=_output_types(node_class),
        input_types=input_types,
        hidden_inputs=hidden_inputs,
        category=category,
        output_node=bool(getattr(node_class, "OUTPUT_NODE", False)),
    )


def _output_types(node_class: object) -> tuple[str, ...]:
    """Return normalized Comfy return types from a node class."""

    return_types = getattr(node_class, "RETURN_TYPES", ())
    if not isinstance(return_types, tuple | list):
        return ()
    return tuple(str(output_type).upper() for output_type in return_types)


def _input_metadata(
    class_type: str,
    node_class: object,
    logger: logging.Logger,
) -> tuple[tuple[tuple[str, str], ...], frozenset[str]]:
    """Return visible input type metadata and hidden input names for one node class."""

    input_types_attr = getattr(node_class, "INPUT_TYPES", None)
    if not callable(input_types_attr):
        return (), frozenset()
    input_types_callable = cast("Callable[[], object]", input_types_attr)
    try:
        raw_input_types = input_types_callable()
    except Exception:
        logger.debug(
            "Could not cache Comfy node input metadata.",
            exc_info=True,
            extra={
                "operation": "prompt_queue_node_definitions_cache",
                "class_type": class_type,
            },
        )
        return (), frozenset()
    if not isinstance(raw_input_types, Mapping):
        return (), frozenset()
    visible_inputs: list[tuple[str, str]] = []
    hidden_inputs: set[str] = set()
    for section_name in ("required", "optional", "hidden"):
        section = raw_input_types.get(section_name)
        if not isinstance(section, Mapping):
            continue
        for input_name, specification in section.items():
            if not isinstance(input_name, str):
                continue
            if section_name == "hidden":
                hidden_inputs.add(input_name)
                continue
            visible_inputs.append((input_name, _input_type_name(specification)))
    return tuple(visible_inputs), frozenset(hidden_inputs)


def _input_type_name(specification: object) -> str:
    """Return a compact type label from Comfy's flexible input specification shape."""

    if isinstance(specification, str):
        return specification.upper()
    if isinstance(specification, list | tuple) and specification:
        first_item = specification[0]
        if isinstance(first_item, str):
            return first_item.upper()
        if isinstance(first_item, list | tuple):
            return "CHOICE"
    return "UNKNOWN"

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
"""Cached node definition metadata for prompt graph optimization."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NodeDefinition:
    """Describe the prompt-visible type surface of one Comfy node class."""

    class_type: str
    output_types: tuple[str, ...] = ()
    input_types: tuple[tuple[str, str], ...] = ()
    hidden_inputs: frozenset[str] = field(default_factory=frozenset)
    category: str | None = None
    output_node: bool = False

    def input_type(self, input_name: str) -> str | None:
        """Return the declared type for one visible input when metadata has it."""

        for candidate_name, type_name in self.input_types:
            if candidate_name == input_name:
                return type_name
        return None


class NodeDefinitionProvider:
    """Provide cached node definition metadata without querying Comfy at optimize time."""

    def __init__(self, definitions: Iterable[NodeDefinition] = ()) -> None:
        """Index definition records by class type."""

        self._definitions = {definition.class_type: definition for definition in definitions}

    def definition_for_class(self, class_type: str) -> NodeDefinition | None:
        """Return cached metadata for one node class."""

        return self._definitions.get(class_type)

    def definition_count(self) -> int:
        """Return the number of cached node definitions."""

        return len(self._definitions)

    def class_types(self) -> tuple[str, ...]:
        """Return cached class names in deterministic order."""

        return tuple(sorted(self._definitions))

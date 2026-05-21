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
"""Resolve model-load source fields from prompt graphs without node maps."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePath

JsonMapping = Mapping[str, object]


@dataclass(frozen=True)
class ModelLoadSource:
    """Identify the prompt node input that selected a loading model."""

    node_id: str
    input_key: str


class ModelLoadSourceResolver:
    """Resolve model field ownership from generic graph links and model identity."""

    def resolve(
        self,
        *,
        prompt_graph: Mapping[str, object],
        executing_node_id: str | None,
        model_name: str | None,
    ) -> ModelLoadSource | None:
        """Return one confident source input match, or ``None`` when ambiguous."""

        model_token = _normalize_model_token(model_name)
        if executing_node_id is None or model_token is None:
            return None

        visited: set[str] = set()
        pending: deque[str] = deque([executing_node_id])
        matches: set[ModelLoadSource] = set()
        while pending:
            node_id = pending.popleft()
            if node_id in visited:
                continue
            visited.add(node_id)

            node = prompt_graph.get(node_id)
            if not isinstance(node, Mapping):
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, Mapping):
                continue
            for input_key, input_value in inputs.items():
                if not isinstance(input_key, str):
                    continue
                if _matches_model_value(input_value, model_token):
                    matches.add(ModelLoadSource(node_id=node_id, input_key=input_key))
                upstream_node_id = _linked_node_id(input_value)
                if upstream_node_id is not None and upstream_node_id not in visited:
                    pending.append(upstream_node_id)

        if len(matches) == 1:
            return next(iter(matches))
        return None


def _matches_model_value(value: object, model_token: str) -> bool:
    """Return whether one prompt input value names the loading model."""

    if not isinstance(value, str):
        return False
    value_token = _normalize_model_token(value)
    return value_token == model_token


def _linked_node_id(value: object) -> str | None:
    """Return the upstream prompt node id from a Comfy link input."""

    if not isinstance(value, list | tuple) or not value:
        return None
    raw_node_id = value[0]
    if isinstance(raw_node_id, str | int):
        return str(raw_node_id)
    return None


def _normalize_model_token(value: str | None) -> str | None:
    """Normalize a model name or path into a comparable basename token."""

    if value is None:
        return None
    stripped_value = value.strip()
    if not stripped_value:
        return None
    normalized_path = stripped_value.replace("\\", "/")
    basename = PurePath(normalized_path).name
    return basename.casefold()

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
"""Typed helpers for Comfy API prompt graph payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeGuard

type InputMap = dict[str, object]
type ComfyNode = dict[str, object]
type ApiPrompt = dict[str, ComfyNode]


def is_comfy_node_link(value: object) -> TypeGuard[list[object]]:
    """Return whether a value has Comfy's ``[node_id, output_slot]`` link shape."""

    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )


def is_api_prompt(value: object) -> TypeGuard[ApiPrompt]:
    """Return whether a dynamic value looks like a Comfy API prompt mapping."""

    if not isinstance(value, dict):
        return False
    for node_id, node in value.items():
        if not isinstance(node_id, str) or not isinstance(node, dict):
            return False
        class_type = node.get("class_type")
        inputs = node.get("inputs", {})
        if not isinstance(class_type, str) or not isinstance(inputs, Mapping):
            return False
    return True

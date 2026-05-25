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
"""Allowlist and pure string evaluation rules for prompt graph optimization."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from substitute_backend.features.prompt_queue.domain.graph import is_comfy_node_link

ALLOWLISTED_NODE_CLASSES = frozenset(
    {
        "PrimitiveString",
        "PrimitiveStringMultiline",
        "RegexExtract",
        "StringConcatenate",
        "PCLazyLoraLoader",
        "PCLazyLoraLoaderAdvanced",
        "PCLazyTextEncode",
        "PCLazyTextEncodeAdvanced",
    }
)

_STRING_NODE_CLASSES = frozenset(
    {"PrimitiveString", "PrimitiveStringMultiline", "RegexExtract", "StringConcatenate"}
)
_SUPPORTED_REGEX_PATTERNS = frozenset({"<[^>]*>", "(?:^|>)([^<]+)(?=<|$)"})


def is_allowlisted_node_class(class_type: str) -> bool:
    """Return whether the optimizer may consider one node class."""

    return class_type in ALLOWLISTED_NODE_CLASSES


def optimization_kind(class_type: str) -> str:
    """Return a stable report category for one optimized node class."""

    if class_type in {"PCLazyLoraLoader", "PCLazyLoraLoaderAdvanced"}:
        return "lora_schedule_branch"
    if class_type in {"PCLazyTextEncode", "PCLazyTextEncodeAdvanced"}:
        return "text_conditioning"
    if class_type in _STRING_NODE_CLASSES:
        return "string_resource"
    return "pure_node"


def evaluate_string_output(
    node: Mapping[str, object],
    resolve_link: Callable[[str, int], str | None],
) -> str | None:
    """Evaluate supported pure string nodes without importing Comfy node classes.

    Only the first-pass shapes captured in the plan are evaluated. Unsupported
    regex patterns return ``None`` so the optimizer preserves the graph.
    """

    class_type = node.get("class_type")
    inputs = node.get("inputs")
    if not isinstance(class_type, str) or not isinstance(inputs, Mapping):
        return None
    if class_type in {"PrimitiveString", "PrimitiveStringMultiline"}:
        value = inputs.get("value")
        return value if isinstance(value, str) else None
    if class_type == "StringConcatenate":
        string_a = _resolve_string_input(inputs.get("string_a"), resolve_link)
        string_b = _resolve_string_input(inputs.get("string_b"), resolve_link)
        delimiter = _resolve_string_input(inputs.get("delimiter"), resolve_link)
        if string_a is None or string_b is None or delimiter is None:
            return None
        return delimiter.join((string_a, string_b))
    if class_type == "RegexExtract":
        return _evaluate_regex_extract(inputs, resolve_link)
    return None


def should_preserve_when_string_eval_fails(node: Mapping[str, object]) -> bool:
    """Return whether a node should not be interned without string evaluation."""

    return node.get("class_type") == "RegexExtract"


def _evaluate_regex_extract(
    inputs: Mapping[str, object],
    resolve_link: Callable[[str, int], str | None],
) -> str | None:
    """Evaluate the supported ``RegexExtract`` v1 input shape."""

    source = _resolve_string_input(inputs.get("string"), resolve_link)
    pattern = _resolve_string_input(inputs.get("regex_pattern"), resolve_link)
    mode = _resolve_string_input(inputs.get("mode"), resolve_link)
    group_index = inputs.get("group_index")
    if (
        source is None
        or pattern not in _SUPPORTED_REGEX_PATTERNS
        or mode not in {"First Match", "All Matches", "First Group", "All Groups"}
        or not isinstance(group_index, int)
    ):
        return None
    flags = 0
    if inputs.get("case_insensitive") is True:
        flags |= re.IGNORECASE
    if inputs.get("multiline") is True:
        flags |= re.MULTILINE
    if inputs.get("dotall") is True:
        flags |= re.DOTALL
    try:
        return _extract_regex_result(
            source=source,
            pattern=pattern,
            mode=mode,
            group_index=group_index,
            flags=flags,
        )
    except re.error:
        return ""


def _extract_regex_result(
    *,
    source: str,
    pattern: str,
    mode: str,
    group_index: int,
    flags: int,
) -> str:
    """Mirror Comfy's supported ``RegexExtract`` result semantics."""

    join_delimiter = "\n"
    if mode == "First Match":
        match = re.search(pattern, source, flags)
        return match.group(0) if match else ""
    if mode == "All Matches":
        matches = re.findall(pattern, source, flags)
        if not matches:
            return ""
        first = matches[0]
        if isinstance(first, tuple):
            return join_delimiter.join(str(match[0]) for match in matches)
        return join_delimiter.join(str(match) for match in matches)
    if mode == "First Group":
        match = re.search(pattern, source, flags)
        if match and len(match.groups()) >= group_index:
            return match.group(group_index)
        return ""
    group_matches = re.finditer(pattern, source, flags)
    results = [
        match.group(group_index)
        for match in group_matches
        if match.groups() and len(match.groups()) >= group_index
    ]
    return join_delimiter.join(results)


def _resolve_string_input(
    value: object,
    resolve_link: Callable[[str, int], str | None],
) -> str | None:
    """Resolve a literal or linked string input."""

    if isinstance(value, str):
        return value
    if is_comfy_node_link(value):
        node_id = value[0]
        output_slot = value[1]
        if isinstance(node_id, str) and isinstance(output_slot, int):
            return resolve_link(node_id, output_slot)
    return None

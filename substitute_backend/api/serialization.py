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
"""JSON serialization primitives for typed backend payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import is_dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | dict[str, JsonValue] | list[JsonValue]
type JsonObject = dict[str, JsonValue]


@runtime_checkable
class JsonSerializable(Protocol):
    """Protocol for domain objects that own their JSON representation."""

    def to_payload(self) -> JsonObject:
        """Return a JSON-compatible object representation."""


def serialize_value(value: object) -> JsonValue:
    """Convert supported typed values into JSON-compatible structures."""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return serialize_value(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, JsonSerializable):
        return value.to_payload()
    if isinstance(value, Mapping):
        return {
            str(key): serialize_value(item) for key, item in value.items() if isinstance(key, str)
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [serialize_value(item) for item in value]
    if is_dataclass(value):
        msg = "Dataclasses must implement to_payload to control public API shape"
        raise TypeError(msg)
    msg = f"Unsupported JSON payload value: {type(value).__name__}"
    raise TypeError(msg)


def require_json_object(value: object) -> JsonObject:
    """Validate that a serialized value is a JSON object."""

    serialized = serialize_value(value)
    if not isinstance(serialized, dict):
        msg = f"Expected JSON object, got {type(serialized).__name__}"
        raise TypeError(msg)
    return serialized

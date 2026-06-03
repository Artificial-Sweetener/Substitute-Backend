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
"""Domain contracts for the Sugar compile route."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from substitute_backend.api.serialization import JsonObject

SUGAR_COMPILE_ROUTE = "/substitute/v1/sugar/compile"
SUGAR_COMPILE_SCHEMA_VERSION = 1


class SugarCompileError(RuntimeError):
    """Carry expected Sugar compilation failures across backend layers."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 400,
        code: str = "sugar-compile-failed",
    ) -> None:
        """Create a typed compile failure with public HTTP error metadata."""

        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class SugarCompileUnavailableError(SugarCompileError):
    """Report a missing Sugar-DSL runtime dependency."""

    def __init__(self, message: str) -> None:
        """Create an unavailable compile failure."""

        super().__init__(
            message,
            status=503,
            code="sugar-compile-unavailable",
        )


@dataclass(frozen=True)
class SugarCompileRequest:
    """Describe one Sugar script compile request from SugarSubstitute."""

    sugar_script_text: str
    output_dir: Path
    schema_version: int = SUGAR_COMPILE_SCHEMA_VERSION

    @classmethod
    def from_payload(cls, payload: JsonObject) -> SugarCompileRequest:
        """Validate and construct a compile request from public JSON data."""

        schema_version = payload.get("schemaVersion")
        if schema_version != SUGAR_COMPILE_SCHEMA_VERSION:
            raise SugarCompileError(
                "Sugar compile request schemaVersion must be 1.",
                status=400,
                code="sugar-compile-invalid-request",
            )
        script_text = payload.get("sugarScriptText")
        if not isinstance(script_text, str) or not script_text.strip():
            raise SugarCompileError(
                "Sugar compile request requires non-empty sugarScriptText.",
                status=400,
                code="sugar-compile-invalid-request",
            )
        output_dir = payload.get("outputDir")
        if not isinstance(output_dir, str) or not output_dir.strip():
            raise SugarCompileError(
                "Sugar compile request requires non-empty outputDir.",
                status=400,
                code="sugar-compile-invalid-request",
            )
        if "\x00" in output_dir:
            raise SugarCompileError(
                "Sugar compile request outputDir contains an invalid character.",
                status=400,
                code="sugar-compile-invalid-request",
            )
        windows_path = PureWindowsPath(output_dir)
        if not windows_path.is_absolute():
            raise SugarCompileError(
                "Sugar compile request outputDir must be an absolute Windows path.",
                status=400,
                code="sugar-compile-invalid-request",
            )
        return cls(
            sugar_script_text=script_text,
            output_dir=Path(output_dir),
        )


@dataclass(frozen=True)
class SugarCompileResult:
    """Hold compiled Comfy prompt and UI workflow artifacts."""

    prompt: JsonObject
    workflow: JsonObject

    def to_payload(self) -> JsonObject:
        """Return the public route response shape."""

        return {
            "prompt": self.prompt,
            "workflow": self.workflow,
        }


@dataclass(frozen=True)
class SugarCompileCapabilities:
    """Describe Sugar compilation support in the active backend runtime."""

    available: bool
    unavailable_reason: str = ""
    live_node_definitions: bool = False
    sugar_dsl_version: str = ""
    schema_version: int = SUGAR_COMPILE_SCHEMA_VERSION
    compile_route: str = SUGAR_COMPILE_ROUTE

    def to_payload(self) -> JsonObject:
        """Return the public capability payload."""

        payload: JsonObject = {
            "schemaVersion": self.schema_version,
            "available": self.available,
        }
        if self.available:
            payload["compileRoute"] = self.compile_route
            payload["liveNodeDefinitions"] = self.live_node_definitions
            payload["sugarDslVersion"] = self.sugar_dsl_version
        else:
            payload["unavailableReason"] = self.unavailable_reason
        return payload

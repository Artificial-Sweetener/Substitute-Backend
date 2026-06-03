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
"""Use-case service for backend-owned Sugar compilation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from substitute_backend.api.errors import BackendHttpError
from substitute_backend.features.sugar_compile.domain import (
    SugarCompileCapabilities,
    SugarCompileError,
    SugarCompileRequest,
    SugarCompileResult,
    SugarCompileUnavailableError,
)


class SugarWorkflowCompiler(Protocol):
    """Describe the infrastructure adapter that invokes Sugar-DSL."""

    def is_available(self) -> bool:
        """Return whether Sugar-DSL can be imported in this backend runtime."""

    def unavailable_reason(self) -> str:
        """Return a setup-oriented reason when Sugar-DSL is unavailable."""

    def sugar_dsl_version(self) -> str:
        """Return the installed Sugar-DSL package version or an empty string."""

    def compile(self, *, script_text: str, output_dir: Path) -> SugarCompileResult:
        """Compile Sugar text into Comfy artifacts."""


@dataclass(frozen=True)
class SugarCompileService:
    """Coordinate one Sugar compile request without owning Sugar-DSL details."""

    compiler: SugarWorkflowCompiler
    logger: logging.Logger

    def capabilities(self) -> SugarCompileCapabilities:
        """Return the backend capability payload for Sugar compilation."""

        if self.compiler.is_available():
            return SugarCompileCapabilities(
                available=True,
                live_node_definitions=True,
                sugar_dsl_version=self.compiler.sugar_dsl_version(),
            )
        return SugarCompileCapabilities(
            available=False,
            unavailable_reason=self.compiler.unavailable_reason(),
        )

    def compile(self, request: SugarCompileRequest) -> SugarCompileResult:
        """Compile one validated Sugar request through the injected compiler."""

        self.logger.info(
            "Sugar compile requested.",
            extra={
                "operation": "sugar-compile",
                "output_path": str(request.output_dir),
                "script_length": len(request.sugar_script_text),
            },
        )
        try:
            return self.compiler.compile(
                script_text=request.sugar_script_text,
                output_dir=request.output_dir,
            )
        except SugarCompileUnavailableError as exc:
            self.logger.warning(
                "Sugar compile unavailable.",
                extra={
                    "operation": "sugar-compile",
                    "output_path": str(request.output_dir),
                    "script_length": len(request.sugar_script_text),
                    "error_category": exc.code,
                },
            )
            raise _http_error(exc) from exc
        except SugarCompileError as exc:
            self.logger.warning(
                "Sugar compile failed.",
                extra={
                    "operation": "sugar-compile",
                    "output_path": str(request.output_dir),
                    "script_length": len(request.sugar_script_text),
                    "error_category": exc.code,
                },
            )
            raise _http_error(exc) from exc
        except Exception as exc:
            self.logger.exception(
                "Unexpected Sugar compile failure.",
                extra={
                    "operation": "sugar-compile",
                    "output_path": str(request.output_dir),
                    "script_length": len(request.sugar_script_text),
                    "error_category": "unexpected",
                },
            )
            raise BackendHttpError(
                message=f"Sugar compile failed: {exc}",
                status=500,
                code="sugar-compile-failed",
            ) from exc


@dataclass(frozen=True)
class SugarCompileServices:
    """Group Sugar compile feature services for host route registration."""

    compile: SugarCompileService


def _http_error(error: SugarCompileError) -> BackendHttpError:
    """Convert a domain compile error into the backend HTTP error contract."""

    return BackendHttpError(
        message=error.message,
        status=error.status,
        code=error.code,
    )

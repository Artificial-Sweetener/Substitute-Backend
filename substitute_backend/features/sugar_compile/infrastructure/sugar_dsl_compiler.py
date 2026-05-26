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
"""Sugar-DSL compiler adapter for the ComfyUI backend runtime."""

from __future__ import annotations

import copy
import importlib.util
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from substitute_backend.api.errors import BackendHttpError
from substitute_backend.api.serialization import JsonObject
from substitute_backend.features.cube_library.application import CubeLibraryService
from substitute_backend.features.sugar_compile.domain import (
    SugarCompileError,
    SugarCompileResult,
    SugarCompileUnavailableError,
)

_LATEST_VERSION_MEMO_KEY = "__latest__"
_UNAVAILABLE_REASON = "Sugar-DSL is not installed in the ComfyUI environment."


class SugarDslWorkflowCompiler:
    """Invoke Sugar-DSL while isolating optional Sugar imports."""

    def __init__(
        self,
        *,
        cube_library: CubeLibraryService,
        logger: logging.Logger,
    ) -> None:
        """Store backend services needed by Sugar-DSL compilation."""

        self._cube_library = cube_library
        self._logger = logger

    def is_available(self) -> bool:
        """Return whether Sugar-DSL's public builder can be imported."""

        try:
            return importlib.util.find_spec("sugar.api.builder") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def unavailable_reason(self) -> str:
        """Return the setup message for a missing Sugar-DSL install."""

        return _UNAVAILABLE_REASON

    def compile(self, *, script_text: str, output_dir: Path) -> SugarCompileResult:
        """Compile Sugar script text through Sugar-DSL."""

        try:
            from sugar.api.builder import (
                build_comfy_artifacts_from_text,
            )
            from sugar.compiler.errors import (
                SugarCompilerError as SugarDslCompilerError,
            )
            from sugar.runtime.live_definitions import (
                ComfyRegistryLiveNodeDefinitionProvider,
            )
        except ImportError as exc:
            raise SugarCompileUnavailableError(_UNAVAILABLE_REASON) from exc

        try:
            payload = cast(
                Mapping[str, object],
                build_comfy_artifacts_from_text(
                    script_text,
                    output_dir=output_dir,
                    cube_artifact_resolver=BackendCubeArtifactResolver(
                        cube_library=self._cube_library,
                        logger=self._logger,
                    ),
                    live_node_definition_provider=ComfyRegistryLiveNodeDefinitionProvider(
                        logger=self._logger,
                    ),
                ),
            )
        except SugarDslCompilerError as exc:
            raise SugarCompileError(
                exc.message,
                status=400,
                code=exc.code,
            ) from exc
        except SugarCompileError:
            raise
        except Exception as exc:
            raise SugarCompileError(
                f"Sugar-DSL compile failed: {exc}",
                status=500,
                code="sugar-compile-failed",
            ) from exc

        prompt = payload.get("prompt")
        workflow = payload.get("workflow")
        if not isinstance(prompt, dict) or not isinstance(workflow, dict):
            raise SugarCompileError(
                "Sugar-DSL did not return prompt/workflow artifacts.",
                status=500,
                code="sugar-compile-failed",
            )
        return SugarCompileResult(
            prompt=cast(JsonObject, prompt),
            workflow=cast(JsonObject, workflow),
        )


class BackendCubeArtifactResolver:
    """Resolve Sugar cube artifacts through the backend Cube Library service."""

    def __init__(
        self,
        *,
        cube_library: CubeLibraryService,
        logger: logging.Logger,
    ) -> None:
        """Create a resolver for one Sugar compile operation."""

        self._cube_library = cube_library
        self._logger = logger
        self._memo: dict[tuple[str, str], Any] = {}

    def resolve(
        self,
        *,
        alias: str,
        cube_id: str,
        requested_version: str | None,
    ) -> Any:
        """Return one Sugar-DSL ``ResolvedCubeArtifact`` for a use statement."""

        memo_key = (cube_id, requested_version or _LATEST_VERSION_MEMO_KEY)
        resolved = self._memo.get(memo_key)
        if resolved is None:
            artifact = self._load_artifact(cube_id, requested_version)
            resolved = self._resolved_artifact(
                alias=alias,
                cube_id=cube_id,
                requested_version=requested_version,
                artifact=artifact,
            )
            self._memo[memo_key] = resolved
        return resolved

    def _load_artifact(
        self,
        cube_id: str,
        requested_version: str | None,
    ) -> JsonObject:
        """Load a raw cube artifact payload from the backend Cube Library."""

        try:
            if requested_version is None:
                artifact = self._cube_library.load_cube(cube_id)
            else:
                artifact = self._cube_library.load_cube_version(
                    cube_id=cube_id,
                    version=requested_version,
                )
        except BackendHttpError as exc:
            raise SugarCompileError(
                f"Cube '{cube_id}' is not available in the active Cube Library.",
                status=exc.status,
                code="sugar-cube-artifact-unavailable",
            ) from exc
        except Exception as exc:
            self._logger.warning(
                "Backend cube artifact load failed during Sugar compile.",
                extra={
                    "operation": "sugar-cube-artifact-resolve",
                    "cube_id": cube_id,
                    "cube_version": requested_version or "",
                    "error": repr(exc),
                },
            )
            raise SugarCompileError(
                f"Cube '{cube_id}' could not be loaded from the active Cube Library.",
                status=503,
                code="sugar-cube-artifact-unavailable",
            ) from exc
        return artifact

    def _resolved_artifact(
        self,
        *,
        alias: str,
        cube_id: str,
        requested_version: str | None,
        artifact: Mapping[str, object],
    ) -> Any:
        """Validate and convert a Cube Library payload into Sugar-DSL's model."""

        declared_cube_id = _required_text(artifact, "cubeId", cube_id=cube_id)
        if declared_cube_id != cube_id:
            raise SugarCompileError(
                f"Cube '{cube_id}' returned artifact '{declared_cube_id}'.",
                status=502,
                code="sugar-cube-artifact-invalid",
            )
        resolved_version = _required_text(artifact, "version", cube_id=cube_id)
        if requested_version is not None and resolved_version != requested_version:
            raise SugarCompileError(
                f"Cube '{cube_id}' version mismatch: expected "
                f"'{requested_version}', got '{resolved_version}'.",
                status=502,
                code="sugar-cube-artifact-invalid",
            )
        cube_payload = artifact.get("cube")
        if not isinstance(cube_payload, Mapping):
            raise SugarCompileError(
                f"Cube '{cube_id}' returned an invalid artifact payload.",
                status=502,
                code="sugar-cube-artifact-invalid",
            )

        try:
            from sugar.catalog.artifacts import (
                CubeArtifactIdentity,
                ResolvedCubeArtifact,
            )
            from sugar.catalog.models import (
                validate_cube_document,
            )
        except ImportError as exc:
            raise SugarCompileUnavailableError(_UNAVAILABLE_REASON) from exc

        try:
            cube = validate_cube_document(dict(cube_payload))
        except (RuntimeError, TypeError, ValueError) as exc:
            raise SugarCompileError(
                f"Cube '{cube_id}' returned an invalid artifact payload: {exc}",
                status=502,
                code="sugar-cube-artifact-invalid",
            ) from exc
        self._logger.debug(
            "Resolved Sugar cube artifact.",
            extra={
                "operation": "sugar-cube-artifact-resolve",
                "cube_alias": alias,
                "cube_id": cube_id,
                "cube_version": resolved_version,
            },
        )
        return ResolvedCubeArtifact(
            cube=copy.deepcopy(cube),
            identity=CubeArtifactIdentity(
                cube_id=cube_id,
                requested_version=requested_version,
                resolved_version=resolved_version,
            ),
        )


def _required_text(
    payload: Mapping[str, object],
    key: str,
    *,
    cube_id: str,
) -> str:
    """Read one required non-empty string from a Cube Library artifact."""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise SugarCompileError(
        f"Cube '{cube_id}' returned an invalid artifact {key}.",
        status=502,
        code="sugar-cube-artifact-invalid",
    )

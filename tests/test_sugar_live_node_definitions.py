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
"""Tests for backend orchestration of Sugar-owned live definitions."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, cast

import pytest

from substitute_backend.api.serialization import JsonObject
from substitute_backend.features.cube_library.application import CubeLibraryService
from substitute_backend.features.sugar_compile.domain import SugarCompileError
from substitute_backend.features.sugar_compile.infrastructure import (
    SugarDslWorkflowCompiler,
)


def test_backend_compiler_passes_live_provider_to_sugar_dsl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backend compile calls should receive Sugar-DSL's runtime live provider."""

    builder = importlib.import_module("sugar.api.builder")

    calls: list[dict[str, Any]] = []

    def fake_build_comfy_artifacts_from_text(
        script_text: str,
        *,
        output_dir: Path,
        cube_artifact_resolver: object,
        live_node_definition_provider: object,
    ) -> JsonObject:
        """Record Sugar-DSL compile keyword arguments."""

        calls.append(
            {
                "script_text": script_text,
                "output_dir": output_dir,
                "cube_artifact_resolver": cube_artifact_resolver,
                "live_node_definition_provider": live_node_definition_provider,
            }
        )
        return {"prompt": {}, "workflow": {}}

    monkeypatch.setattr(
        builder,
        "build_comfy_artifacts_from_text",
        fake_build_comfy_artifacts_from_text,
    )
    compiler = SugarDslWorkflowCompiler(
        cube_library=_unused_cube_library(),
        logger=logging.getLogger("tests.sugar.compiler"),
    )

    compiler.compile(script_text='use "demo" as Demo', output_dir=Path("E:\\outputs"))

    [call] = calls
    assert call["script_text"] == 'use "demo" as Demo'
    assert call["output_dir"] == Path("E:\\outputs")
    provider = call["live_node_definition_provider"]
    assert type(provider).__name__ == "ComfyRegistryLiveNodeDefinitionProvider"
    assert type(provider).__module__ == "sugar.runtime.live_definitions"


def test_backend_compiler_maps_live_definition_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sugar-DSL live-definition failures should keep their structured code."""

    builder = importlib.import_module("sugar.api.builder")
    errors = importlib.import_module("sugar.compiler.errors")
    sugar_compiler_error = cast(Any, errors).SugarCompilerError

    def fake_build_comfy_artifacts_from_text(
        script_text: str,
        *,
        output_dir: Path,
        cube_artifact_resolver: object,
        live_node_definition_provider: object,
    ) -> JsonObject:
        """Raise the typed Sugar-DSL error from the compile boundary."""

        _ = script_text, output_dir, cube_artifact_resolver, live_node_definition_provider
        raise sugar_compiler_error(
            "Required live input has no default.",
            code="sugar-live-default-missing",
            cube_alias="Demo",
            cube_id="demo",
            node_key="Demo.node",
            node_class_type="SimpleNode",
            input_name="new_widget",
        )

    monkeypatch.setattr(
        builder,
        "build_comfy_artifacts_from_text",
        fake_build_comfy_artifacts_from_text,
    )
    compiler = SugarDslWorkflowCompiler(
        cube_library=_unused_cube_library(),
        logger=logging.getLogger("tests.sugar.compiler"),
    )

    with pytest.raises(SugarCompileError) as error_info:
        compiler.compile(script_text='use "demo" as Demo', output_dir=Path("E:\\outputs"))

    assert error_info.value.code == "sugar-live-default-missing"
    assert error_info.value.status == 400


def _unused_cube_library() -> CubeLibraryService:
    """Return a cube library placeholder for compile calls that do not resolve cubes."""

    return CubeLibraryService(gateway=cast(Any, object()))

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
"""Tests for backend Cube Library workflow compilation."""

from __future__ import annotations

import re
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from substitute_backend.api.errors import BackendHttpError
from substitute_backend.features.cube_library.infrastructure import sugarcubes_adapter
from substitute_backend.features.cube_library.infrastructure.sugarcubes_adapter import (
    SugarCubesLibraryAdapter,
)

_USE_PATTERN = re.compile(
    r'^use\s+"(?P<cube_id>[^"]+)"'
    r"(?:@(?P<version_pin>[^\s]+))?"
    r"(?:\s+as\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?"
    r"(?:\s+repeat\s+(?P<repeat>\d+))?$"
)


@dataclass(frozen=True)
class _FakeUseStmt:
    """Represent the Sugar use statement fields consumed by the adapter."""

    cube_id: str
    alias: str | None
    version_pin: str | None
    repeat: int | None


@dataclass(frozen=True)
class _FakeScript:
    """Represent the parsed Sugar script surface consumed by the adapter."""

    statements: tuple[object, ...]


@pytest.fixture(autouse=True)
def fake_sugar_parser_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide deterministic Sugar parser modules for isolated adapter tests."""

    def parse_script(sugar_script_text: str) -> _FakeScript:
        statements: list[object] = []
        for raw_line in sugar_script_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = _USE_PATTERN.fullmatch(line)
            if match is None:
                raise ValueError(f"Unsupported fake Sugar statement: {line}")
            repeat = match.group("repeat")
            statements.append(
                _FakeUseStmt(
                    cube_id=match.group("cube_id"),
                    alias=match.group("alias"),
                    version_pin=match.group("version_pin"),
                    repeat=int(repeat) if repeat is not None else None,
                )
            )
        return _FakeScript(statements=tuple(statements))

    sugar_module = types.ModuleType("sugar")
    dsl_module = types.ModuleType("sugar.dsl")
    ast_module = types.ModuleType("sugar.dsl.ast")
    parser_module = types.ModuleType("sugar.dsl.parser")
    cast(Any, ast_module).UseStmt = _FakeUseStmt
    cast(Any, parser_module).parse_script = parse_script
    monkeypatch.setitem(sys.modules, "sugar", sugar_module)
    monkeypatch.setitem(sys.modules, "sugar.dsl", dsl_module)
    monkeypatch.setitem(sys.modules, "sugar.dsl.ast", ast_module)
    monkeypatch.setitem(sys.modules, "sugar.dsl.parser", parser_module)


class _SugarCubesBackendError(Exception):
    """Provide SugarCubes-like status and message attributes."""

    status = 404
    message = "Cube missing."


class _Library:
    """Provide Cube Library artifacts for workflow compile adapter tests."""

    def __init__(self) -> None:
        """Initialize deterministic artifact records."""

        self.loaded_latest: list[str] = []
        self.loaded_versions: list[tuple[str, str]] = []

    def load_library_cube(self, cube_id: str) -> dict[str, object]:
        """Return the latest cube artifact or raise a typed missing error."""

        self.loaded_latest.append(cube_id)
        if cube_id == "Owner/Repo/missing.cube":
            raise _SugarCubesBackendError("missing")
        return _artifact(cube_id=cube_id, version="latest")

    def load_library_cube_version(
        self,
        *,
        cube_id: str,
        version: str,
    ) -> dict[str, object]:
        """Return a version-selected cube artifact or raise a typed missing error."""

        self.loaded_versions.append((cube_id, version))
        if cube_id == "Owner/Repo/missing.cube":
            raise _SugarCubesBackendError("missing")
        return _artifact(cube_id=cube_id, version=version)

    def catalog_revision(self) -> str:
        """Return a deterministic catalog revision."""

        return "sha256:catalog"


def test_compile_workflow_passes_alias_artifacts_to_compiler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compile should pass version-selected alias artifacts to sugarpackage."""

    library = _Library()
    custom_nodes_root = _custom_nodes_root(tmp_path)
    observed_artifacts: dict[str, object] = {}

    def build_comfy_artifacts_from_text(
        *,
        sugar_script_text: str,
        output_dir: Path,
        cube_artifacts_by_alias: dict[str, object],
    ) -> dict[str, object]:
        """Inspect alias artifacts before returning fake artifacts."""

        assert sugar_script_text == 'use "Owner/Repo/demo.cube"@1.0.0 as Demo'
        assert output_dir == Path("E:/outputs")
        observed_artifacts.update(cube_artifacts_by_alias)
        return {
            "prompt": {"1": {"class_type": "Demo"}},
            "workflow": {"nodes": [], "links": [], "groups": []},
        }

    monkeypatch.setattr(
        sugarcubes_adapter,
        "_build_comfy_artifacts_from_text",
        build_comfy_artifacts_from_text,
    )
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "Substitute-BackEnd",
        custom_nodes_root=custom_nodes_root,
        services_factory=lambda _root: SimpleNamespace(library=library),
    )

    payload = adapter.compile_workflow(
        sugar_script_text='use "Owner/Repo/demo.cube"@1.0.0 as Demo',
        output_dir="E:/outputs",
    )

    assert payload["schemaVersion"] == 1
    assert payload["prompt"] == {"1": {"class_type": "Demo"}}
    assert payload["workflow"] == {"nodes": [], "links": [], "groups": []}
    assert payload["catalogRevision"] == "sha256:catalog"
    assert payload["usedCubes"] == [
        {
            "alias": "Demo",
            "cubeId": "Owner/Repo/demo.cube",
            "version": "1.0.0",
            "source": {"kind": "github", "repoRef": "Owner/Repo"},
        }
    ]
    assert library.loaded_versions == [("Owner/Repo/demo.cube", "1.0.0")]
    assert library.loaded_latest == []
    demo_artifact = cast(dict[str, object], observed_artifacts["Demo"])
    assert demo_artifact["cubeId"] == "Owner/Repo/demo.cube"
    assert demo_artifact["version"] == "1.0.0"


def test_compile_workflow_maps_missing_cube_to_not_found(tmp_path: Path) -> None:
    """Missing active library artifacts should return compile-specific 404 errors."""

    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "Substitute-BackEnd",
        custom_nodes_root=_custom_nodes_root(tmp_path),
        services_factory=lambda _root: SimpleNamespace(library=_Library()),
    )

    with pytest.raises(BackendHttpError) as error:
        adapter.compile_workflow(
            sugar_script_text='use "Owner/Repo/missing.cube"@1.0.0 as Missing',
            output_dir=None,
        )

    assert error.value.status == 404
    assert error.value.code == "cube-not-found"


def test_compile_workflow_rejects_traversal_cube_ids(tmp_path: Path) -> None:
    """Unsafe cube ids should be rejected before artifact materialization."""

    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "Substitute-BackEnd",
        custom_nodes_root=_custom_nodes_root(tmp_path),
        services_factory=lambda _root: SimpleNamespace(library=_Library()),
    )

    with pytest.raises(BackendHttpError) as error:
        adapter.compile_workflow(
            sugar_script_text='use "../bad.cube" as Bad',
            output_dir=None,
        )

    assert error.value.status == 400
    assert error.value.code == "invalid-request"


def test_compile_workflow_uses_latest_for_versionless_sugar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Versionless Sugar should load the current latest cube artifact."""

    library = _Library()
    custom_nodes_root = _custom_nodes_root(tmp_path)

    def build_comfy_artifacts_from_text(
        *,
        sugar_script_text: str,
        output_dir: Path,
        cube_artifacts_by_alias: dict[str, object],
    ) -> dict[str, object]:
        """Return fake artifacts after the adapter materializes the cube."""

        _ = sugar_script_text, output_dir, cube_artifacts_by_alias
        return {"prompt": {}, "workflow": {"nodes": []}}

    monkeypatch.setattr(
        sugarcubes_adapter,
        "_build_comfy_artifacts_from_text",
        build_comfy_artifacts_from_text,
    )
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "Substitute-BackEnd",
        custom_nodes_root=custom_nodes_root,
        services_factory=lambda _root: SimpleNamespace(library=library),
    )

    payload = adapter.compile_workflow(
        sugar_script_text='use "Owner/Repo/demo.cube" as Demo',
        output_dir=None,
    )

    assert payload["usedCubes"] == [
        {
            "alias": "Demo",
            "cubeId": "Owner/Repo/demo.cube",
            "version": "latest",
            "source": {"kind": "github", "repoRef": "Owner/Repo"},
        }
    ]
    assert library.loaded_latest == ["Owner/Repo/demo.cube"]
    assert library.loaded_versions == []


def test_compile_workflow_loads_distinct_pinned_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two aliases of one cube id should load their own Sugar-pinned versions."""

    library = _Library()

    def build_comfy_artifacts_from_text(
        *,
        sugar_script_text: str,
        output_dir: Path,
        cube_artifacts_by_alias: dict[str, object],
    ) -> dict[str, object]:
        """Verify artifacts remain keyed by alias before returning payload."""

        _ = sugar_script_text, output_dir
        assert set(cube_artifacts_by_alias) == {"Old", "New"}
        return {"prompt": {}, "workflow": {"nodes": []}}

    monkeypatch.setattr(
        sugarcubes_adapter,
        "_build_comfy_artifacts_from_text",
        build_comfy_artifacts_from_text,
    )

    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "Substitute-BackEnd",
        custom_nodes_root=_custom_nodes_root(tmp_path),
        services_factory=lambda _root: SimpleNamespace(library=library),
    )

    adapter.compile_workflow(
        sugar_script_text="\n".join(
            [
                'use "Owner/Repo/demo.cube"@1.0.0 as Old',
                'use "Owner/Repo/demo.cube"@2.0.0 as New',
            ]
        ),
        output_dir=None,
    )

    assert library.loaded_versions == [
        ("Owner/Repo/demo.cube", "1.0.0"),
        ("Owner/Repo/demo.cube", "2.0.0"),
    ]


def test_compile_workflow_repeats_pinned_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated Sugar uses should preserve the parsed version pin."""

    library = _Library()

    monkeypatch.setattr(
        sugarcubes_adapter,
        "_build_comfy_artifacts_from_text",
        lambda **_kwargs: {"prompt": {}, "workflow": {"nodes": []}},
    )
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "Substitute-BackEnd",
        custom_nodes_root=_custom_nodes_root(tmp_path),
        services_factory=lambda _root: SimpleNamespace(library=library),
    )

    adapter.compile_workflow(
        sugar_script_text='use "Owner/Repo/demo.cube"@1.2.3 as Demo repeat 2',
        output_dir=None,
    )

    assert library.loaded_versions == [("Owner/Repo/demo.cube", "1.2.3")]


def test_compile_workflow_memoizes_same_latest_cube(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same cube/latest aliases should load the target artifact once."""

    library = _Library()
    monkeypatch.setattr(
        sugarcubes_adapter,
        "_build_comfy_artifacts_from_text",
        lambda **_kwargs: {"prompt": {}, "workflow": {"nodes": []}},
    )
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "Substitute-BackEnd",
        custom_nodes_root=_custom_nodes_root(tmp_path),
        services_factory=lambda _root: SimpleNamespace(library=library),
    )

    adapter.compile_workflow(
        sugar_script_text="\n".join(
            [
                'use "Owner/Repo/demo.cube" as First',
                'use "Owner/Repo/demo.cube" as Second',
            ]
        ),
        output_dir=None,
    )

    assert library.loaded_latest == ["Owner/Repo/demo.cube"]


def test_compile_workflow_separates_latest_and_pinned_memo_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Latest and pinned aliases of one cube should load distinct artifacts."""

    library = _Library()
    monkeypatch.setattr(
        sugarcubes_adapter,
        "_build_comfy_artifacts_from_text",
        lambda **_kwargs: {"prompt": {}, "workflow": {"nodes": []}},
    )
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "Substitute-BackEnd",
        custom_nodes_root=_custom_nodes_root(tmp_path),
        services_factory=lambda _root: SimpleNamespace(library=library),
    )

    adapter.compile_workflow(
        sugar_script_text="\n".join(
            [
                'use "Owner/Repo/demo.cube" as Latest',
                'use "Owner/Repo/demo.cube"@1.0.0 as Pinned',
            ]
        ),
        output_dir=None,
    )

    assert library.loaded_latest == ["Owner/Repo/demo.cube"]
    assert library.loaded_versions == [("Owner/Repo/demo.cube", "1.0.0")]


def _artifact(*, cube_id: str, version: str) -> dict[str, object]:
    """Return a valid SugarCubes artifact payload for adapter tests."""

    return {
        "schemaVersion": 1,
        "cubeId": cube_id,
        "version": version,
        "contentHash": "sha256:artifact",
        "source": {"kind": "github", "repoRef": "Owner/Repo"},
        "cube": {
            "cube_id": cube_id,
            "version": version,
            "nodes": {},
            "edges": [],
        },
    }


def test_status_ignores_old_prefixed_sugarcubes_folder(tmp_path: Path) -> None:
    """The unreleased folder rename should require the clean SugarCubes directory."""

    custom_nodes_root = tmp_path / "custom_nodes"
    (custom_nodes_root / "ComfyUI-SugarCubes").mkdir(parents=True)
    adapter = SugarCubesLibraryAdapter(
        extension_root=tmp_path / "Substitute-BackEnd",
        custom_nodes_root=custom_nodes_root,
        services_factory=lambda _root: SimpleNamespace(library=_Library()),
    )

    payload = adapter.status()

    assert payload["available"] is False
    assert payload["source"] == "sugarcubes"
    assert payload["errors"] == [
        {
            "code": "sugarcubes-unavailable",
            "message": "SugarCubes is not available on this target.",
        }
    ]


def _custom_nodes_root(tmp_path: Path) -> Path:
    """Create a custom nodes root containing a SugarCubes extension folder."""

    custom_nodes_root = tmp_path / "custom_nodes"
    (custom_nodes_root / "SugarCubes").mkdir(parents=True)
    return custom_nodes_root

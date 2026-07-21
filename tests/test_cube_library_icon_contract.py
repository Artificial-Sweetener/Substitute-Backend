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
"""Tests for Substitute-facing Cube Library icon contracts."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from substitute_backend.api.errors import BackendHttpError
from substitute_backend.features.cube_library.application import (
    build_cube_icon_url,
    public_icon_descriptor,
)
from substitute_backend.features.cube_library.infrastructure import SugarCubesLibraryAdapter
from substitute_backend.infrastructure.diagnostics import (
    CUBE_LIBRARY_DIAGNOSTICS,
    DIAGNOSTICS_ENV_VAR,
    DiagnosticContext,
    DiagnosticLogger,
    diagnostics_from_environment,
)


def test_public_icon_descriptor_rewrites_png_descriptor_url() -> None:
    """PNG descriptors should use the Substitute-BackEnd icon route."""

    descriptor = public_icon_descriptor(
        cube_id="Artificial-Sweetener/Base-Cubes/Text to Image.cube",
        icon={
            "kind": "asset",
            "media_type": "image/png",
            "url": "/sugarcubes/assets/icon?cube_id=ignored",
            "repo_relative_path": "assets/icons/Text to Image.png",
        },
    )

    assert descriptor == {
        "kind": "asset",
        "media_type": "image/png",
        "url": (
            "/substitute/v1/cube-library/cubes/icon?"
            "cubeId=Artificial-Sweetener%2FBase-Cubes%2FText%20to%20Image.cube"
        ),
        "repo_relative_path": "assets/icons/Text to Image.png",
    }


def test_public_icon_descriptor_accepts_svg_and_camel_case_fields() -> None:
    """SVG descriptors should accept backend variants and emit snake-case fields."""

    descriptor = public_icon_descriptor(
        cube_id="Owner/Repo/Demo.cube",
        icon={
            "kind": "asset",
            "mediaType": "image/svg+xml",
            "repoRelativePath": "assets/icons/Demo.svg",
        },
    )

    assert descriptor == {
        "kind": "asset",
        "media_type": "image/svg+xml",
        "url": "/substitute/v1/cube-library/cubes/icon?cubeId=Owner%2FRepo%2FDemo.cube",
        "repo_relative_path": "assets/icons/Demo.svg",
    }


@pytest.mark.parametrize(
    "icon",
    [
        None,
        "not-a-mapping",
        {"kind": "generated", "media_type": "image/png"},
        {"kind": "asset", "media_type": "image/gif"},
    ],
)
def test_public_icon_descriptor_rejects_unsupported_shapes(icon: object) -> None:
    """Invalid icon descriptors should be omitted from public payloads."""

    assert public_icon_descriptor(cube_id="Owner/Repo/Demo.cube", icon=icon) is None


def test_build_cube_icon_url_returns_empty_for_empty_cube_ids() -> None:
    """Empty cube ids should not produce fetchable public URLs."""

    assert build_cube_icon_url("   ") == ""


def test_adapter_catalog_rewrites_icon_descriptors(tmp_path: Path) -> None:
    """Catalog payloads should expose backend-owned icon URLs."""

    library = _Library(tmp_path)
    adapter = _adapter(tmp_path, library)

    payload = adapter.catalog(include_disabled=False)

    cubes = cast(list[dict[str, object]], payload["cubes"])
    assert isinstance(cubes, list)
    icon = cubes[0]["icon"]
    assert icon == {
        "kind": "asset",
        "media_type": "image/png",
        "url": "/substitute/v1/cube-library/cubes/icon?cubeId=Owner%2FRepo%2FIcon.cube",
        "repo_relative_path": "assets/icons/Icon.png",
    }
    assert "icon" not in cubes[1]


def test_adapter_diagnostics_are_silent_without_context(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adapter diagnostics should require a request-provided diagnostic context."""

    monkeypatch.setenv(DIAGNOSTICS_ENV_VAR, "cube-library")
    library = _Library(tmp_path)
    adapter = _adapter(
        tmp_path,
        library,
        diagnostics=diagnostics_from_environment(logging.getLogger("test.adapter.diagnostics")),
    )

    with caplog.at_level(logging.DEBUG):
        adapter.catalog(include_disabled=False)

    assert [
        record
        for record in caplog.records
        if getattr(record, "diagnostic_feature", "") == CUBE_LIBRARY_DIAGNOSTICS
    ] == []


def test_adapter_diagnostics_emit_with_context(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adapter diagnostics should emit structured details for traced requests."""

    monkeypatch.setenv(DIAGNOSTICS_ENV_VAR, "cube-library")
    library = _Library(tmp_path)
    adapter = _adapter(
        tmp_path,
        library,
        diagnostics=diagnostics_from_environment(logging.getLogger("test.adapter.diagnostics")),
    )

    with caplog.at_level(logging.DEBUG):
        adapter.catalog(
            include_disabled=False,
            diagnostic_context=DiagnosticContext(
                feature=CUBE_LIBRARY_DIAGNOSTICS,
                trace_id="trace-1",
            ),
        )

    records = [
        record
        for record in caplog.records
        if getattr(record, "diagnostic_feature", "") == CUBE_LIBRARY_DIAGNOSTICS
    ]
    assert [getattr(record, "diagnostic_event", "") for record in records] == [
        "backend_adapter_catalog_return"
    ]
    assert getattr(records[0], "trace_id", "") == "trace-1"
    assert getattr(records[0], "cube_count", "") == 2


def test_adapter_load_adds_top_level_icon_from_summary(tmp_path: Path) -> None:
    """Loaded artifacts should include icon descriptors even when SugarCubes omits them."""

    library = _Library(tmp_path)
    adapter = _adapter(tmp_path, library)

    payload = adapter.load_cube("Owner/Repo/Icon.cube")

    assert payload["icon"] == {
        "kind": "asset",
        "media_type": "image/png",
        "url": "/substitute/v1/cube-library/cubes/icon?cubeId=Owner%2FRepo%2FIcon.cube",
        "repo_relative_path": "assets/icons/Icon.png",
    }


def test_adapter_load_omits_icon_when_cube_has_none(tmp_path: Path) -> None:
    """Loaded artifacts without declared icons should remain valid without icon."""

    library = _Library(tmp_path)
    adapter = _adapter(tmp_path, library)

    payload = adapter.load_cube("Owner/Repo/Plain.cube")

    assert "icon" not in payload


def test_adapter_icon_asset_returns_bytes_and_media_type(tmp_path: Path) -> None:
    """The adapter should serve bytes from SugarCubes icon resolution."""

    library = _Library(tmp_path)
    adapter = _adapter(tmp_path, library)

    content, media_type = adapter.icon_asset("Owner/Repo/Icon.cube")

    assert content == b"png-bytes"
    assert media_type == "image/png"


def test_adapter_icon_asset_maps_missing_icon_to_not_found(tmp_path: Path) -> None:
    """Missing icon assets should preserve a 404 backend error."""

    library = _Library(tmp_path)
    adapter = _adapter(tmp_path, library)

    with pytest.raises(BackendHttpError) as error:
        adapter.icon_asset("Owner/Repo/Plain.cube")

    assert error.value.status == 404
    assert error.value.code == "cube-library-not-found"


class _SugarCubesBackendError(Exception):
    """Provide SugarCubes-like status and message attributes."""

    status = 404
    message = "Cube icon not found."


class _Library:
    """Provide fake SugarCubes library behavior for icon contract tests."""

    def __init__(self, root: Path) -> None:
        """Create one fake icon asset."""

        self._icon_path = root / "assets" / "icons" / "Icon.png"
        self._icon_path.parent.mkdir(parents=True)
        self._icon_path.write_bytes(b"png-bytes")

    def list_library_catalog(self, *, include_disabled: bool) -> dict[str, object]:
        """Return one icon cube and one plain cube."""

        assert include_disabled is False
        return {
            "schemaVersion": 1,
            "cubes": [
                {
                    "cubeId": "Owner/Repo/Icon.cube",
                    "displayName": "Icon",
                    "icon": {
                        "kind": "asset",
                        "media_type": "image/png",
                        "url": "/sugarcubes/assets/icon?cube_id=ignored",
                        "repo_relative_path": "assets/icons/Icon.png",
                    },
                },
                {"cubeId": "Owner/Repo/Plain.cube", "displayName": "Plain"},
            ],
        }

    def load_library_cube(self, cube_id: str) -> dict[str, object]:
        """Return a loaded artifact without a top-level icon."""

        return {
            "schemaVersion": 1,
            "cubeId": cube_id,
            "cube": {"cube_id": cube_id, "version": "1.0.0"},
        }

    def resolve_cube_by_id(self, cube_id: str) -> Path:
        """Return a fake path for summary derivation."""

        return Path(f"{cube_id.replace('/', '_')}.cube")

    def summarize_cube(self, cube_path: Path) -> dict[str, object]:
        """Return summary metadata keyed by the fake path."""

        if "Icon" not in cube_path.name:
            return {"cube_id": "Owner/Repo/Plain.cube"}
        return {
            "cube_id": "Owner/Repo/Icon.cube",
            "icon": {
                "kind": "asset",
                "media_type": "image/png",
                "repo_relative_path": "assets/icons/Icon.png",
            },
        }

    def resolve_cube_icon_asset(self, cube_id: str) -> tuple[Path, str]:
        """Return a fake icon path or raise a missing icon error."""

        if cube_id != "Owner/Repo/Icon.cube":
            raise _SugarCubesBackendError("missing")
        return self._icon_path, "image/png"


def _adapter(
    tmp_path: Path,
    library: _Library,
    *,
    diagnostics: DiagnosticLogger | None = None,
) -> SugarCubesLibraryAdapter:
    """Return a SugarCubes adapter using fake services."""

    custom_nodes_root = tmp_path / "custom_nodes"
    (custom_nodes_root / "SugarCubes").mkdir(parents=True)
    return SugarCubesLibraryAdapter(
        extension_root=tmp_path / "Substitute-BackEnd",
        custom_nodes_root=custom_nodes_root,
        services_loader=lambda: SimpleNamespace(library=library),
        diagnostics=diagnostics,
    )

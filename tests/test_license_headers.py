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
"""Test repository license header maintenance."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, cast

_TOOLS_MODULE = Path(__file__).resolve().parents[1] / "tools" / "add_license_headers.py"
_REPO_ROOT = _TOOLS_MODULE.parents[1]


def _load_module(path: Path) -> ModuleType:
    """Load the license header tool directly from its repository path."""

    spec = importlib.util.spec_from_file_location("add_license_headers_for_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec for {path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_license_headers = cast(Any, _load_module(_TOOLS_MODULE))
_copyright_years = _license_headers._copyright_years
_header = _license_headers._header


def test_copyright_years_stays_single_year_during_start_year() -> None:
    """Keep the initial release year compact while it is still current."""

    assert _copyright_years(datetime(2026, 5, 21, tzinfo=UTC)) == "2026"


def test_copyright_years_expands_after_start_year() -> None:
    """Render a range when the tool is rerun in a later year."""

    assert _copyright_years(datetime(2030, 1, 1, tzinfo=UTC)) == "2026 - 2030"


def test_header_uses_javascript_comment_prefix_for_release_scripts() -> None:
    """Use JavaScript comments for semantic-release support files."""

    header = _header(path=Path("scripts/update-release-versions.mjs"))

    assert header.startswith("//    Substitute BackEnd")
    assert "GNU Affero General Public License" in header


def test_project_license_metadata_uses_agpl_v3_or_later() -> None:
    """Keep published package metadata aligned with source file headers."""

    metadata_paths = [
        _REPO_ROOT / "pyproject.toml",
        _REPO_ROOT / "package.json",
        _REPO_ROOT / "package-lock.json",
        _REPO_ROOT / "README.md",
    ]

    for path in metadata_paths:
        text = path.read_text(encoding="utf-8")
        assert "AGPL-3.0-only" not in text

    assert 'license = "AGPL-3.0-or-later"' in (_REPO_ROOT / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert '"license": "AGPL-3.0-or-later"' in (_REPO_ROOT / "package.json").read_text(
        encoding="utf-8"
    )
    assert "GNU Affero General Public License v3.0 or later" in (
        _REPO_ROOT / "README.md"
    ).read_text(encoding="utf-8")

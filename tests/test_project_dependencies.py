#    Substitute BackEnd - Backend services for SugarSubstitute and ComfyUI
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

"""Verify runtime dependency constraints declared by project metadata."""

from __future__ import annotations

import tomllib
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_sugar_dsl_dependency_is_hard_pinned_to_published_release() -> None:
    """Keep Backend compilation on the explicitly verified Sugar-DSL release."""

    metadata = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata.get("project")
    assert isinstance(project, dict)
    dependencies = project.get("dependencies")
    assert isinstance(dependencies, list)
    assert [value for value in dependencies if str(value).startswith("sugar-dsl")] == [
        "sugar-dsl==1.2.0"
    ]

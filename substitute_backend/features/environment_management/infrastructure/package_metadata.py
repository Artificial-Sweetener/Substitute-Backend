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
"""Read package summaries from installed distribution metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import metadata

from substitute_backend.features.environment_management.domain.packages import (
    PackageSummarySource,
)
from substitute_backend.features.environment_management.infrastructure.pip_inspector import (
    normalize_package_name,
)

_REQUIRES_DIST_NAME_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.-]+)")


@dataclass(frozen=True)
class PackageSummary:
    """Describe a package summary and the source that supplied it."""

    summary: str | None
    source: PackageSummarySource


@dataclass(frozen=True)
class PackageDependency:
    """Describe one installed distribution dependency edge."""

    package_name: str
    normalized_name: str
    requirement: str


class InstalledPackageMetadataProvider:
    """Read installed distribution metadata used by package inventory."""

    def summaries_by_package(self) -> dict[str, PackageSummary]:
        """Return installed metadata summaries keyed by normalized package name."""

        summaries: dict[str, PackageSummary] = {}
        for distribution in metadata.distributions():
            package_name = distribution.metadata.get("Name")
            if package_name is None:
                continue
            summary = distribution.metadata.get("Summary")
            if summary is None or not summary.strip():
                continue
            summaries[normalize_package_name(package_name)] = PackageSummary(
                summary=summary.strip(),
                source=PackageSummarySource.INSTALLED_METADATA,
            )
        return summaries

    def dependencies_by_package(self) -> dict[str, tuple[PackageDependency, ...]]:
        """Return installed distribution dependencies keyed by normalized package name."""

        dependencies: dict[str, tuple[PackageDependency, ...]] = {}
        for distribution in metadata.distributions():
            package_name = distribution.metadata.get("Name")
            if package_name is None:
                continue
            entries = tuple(
                dependency
                for requirement in distribution.requires or ()
                if (dependency := _to_dependency(requirement)) is not None
            )
            if entries:
                dependencies[normalize_package_name(package_name)] = entries
        return dependencies


def _to_dependency(requirement: str) -> PackageDependency | None:
    """Convert one metadata requirement string into a dependency edge."""

    match = _REQUIRES_DIST_NAME_PATTERN.match(requirement)
    if match is None:
        return None
    package_name = match.group(1)
    normalized_name = normalize_package_name(package_name)
    if not normalized_name:
        return None
    return PackageDependency(
        package_name=package_name,
        normalized_name=normalized_name,
        requirement=requirement.strip(),
    )

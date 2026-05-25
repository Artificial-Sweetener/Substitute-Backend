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
"""Application service boundary for target-owned Cube Library operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from substitute_backend.api.serialization import JsonObject
from substitute_backend.infrastructure.diagnostics import DiagnosticContext


class CubeLibraryGateway(Protocol):
    """Describe the SugarCubes-backed operations consumed by route handlers."""

    def status(self) -> JsonObject:
        """Return Cube Library availability for the active target."""

    def catalog(
        self,
        *,
        include_disabled: bool,
        diagnostic_context: DiagnosticContext | None = None,
    ) -> JsonObject:
        """Return Cube Library catalog metadata."""

    def load_cube(
        self,
        cube_id: str,
        *,
        diagnostic_context: DiagnosticContext | None = None,
    ) -> JsonObject:
        """Return one canonical cube artifact."""

    def list_cube_versions(self, cube_id: str) -> JsonObject:
        """Return artifact versions for one cube id."""

    def load_cube_version(
        self,
        *,
        cube_id: str,
        version: str,
        diagnostic_context: DiagnosticContext | None = None,
    ) -> JsonObject:
        """Return one cube artifact selected by version."""

    def prewarm_cube_version(
        self,
        *,
        cube_id: str,
        version: str,
    ) -> JsonObject:
        """Schedule a best-effort version artifact warmup."""

    def icon_asset(self, cube_id: str) -> tuple[bytes, str]:
        """Return icon bytes and media type for one cube."""

    def list_packs(self) -> JsonObject:
        """Return tracked Cube Pack records."""

    def preflight_pack(self, *, owner: str, repo: str, branch: str) -> JsonObject:
        """Return preflight results for one candidate Cube Pack."""

    def add_pack(
        self,
        *,
        owner: str,
        repo: str,
        branch: str,
        enabled: bool,
        auto_update: bool,
        sync_immediately: bool,
    ) -> JsonObject:
        """Track one Cube Pack and optionally sync it before returning."""

    def update_pack(
        self,
        *,
        owner: str,
        repo: str,
        branch: str | None,
        enabled: bool | None,
        auto_update: bool | None,
    ) -> JsonObject:
        """Update one tracked Cube Pack."""

    def remove_pack(self, *, owner: str, repo: str) -> JsonObject:
        """Remove one tracked Cube Pack."""

    def sync_pack(self, *, owner: str, repo: str) -> JsonObject:
        """Sync one tracked Cube Pack synchronously."""

    def sync_all_packs(self) -> JsonObject:
        """Sync all enabled Cube Packs synchronously."""

    def readiness(self) -> JsonObject:
        """Return read-only dependency readiness for the target library."""

    def dependency_readiness(self) -> JsonObject:
        """Return install-capable dependency readiness for the target library."""

    def repair_dependencies(
        self,
        *,
        baseline_only: bool,
        approved_node_ids: tuple[str, ...],
        sync_enabled_repos: bool,
    ) -> JsonObject:
        """Repair approved target library dependencies."""


@dataclass(frozen=True)
class CubeLibraryService:
    """Coordinate Cube Library use cases through an infrastructure gateway."""

    gateway: CubeLibraryGateway

    def status(self) -> JsonObject:
        """Return Cube Library availability for the active target."""

        return self.gateway.status()

    def catalog(
        self,
        *,
        include_disabled: bool,
        diagnostic_context: DiagnosticContext | None = None,
    ) -> JsonObject:
        """Return catalog metadata from the active target library."""

        return self.gateway.catalog(
            include_disabled=include_disabled,
            diagnostic_context=diagnostic_context,
        )

    def load_cube(
        self,
        cube_id: str,
        *,
        diagnostic_context: DiagnosticContext | None = None,
    ) -> JsonObject:
        """Return one canonical cube artifact by id."""

        return self.gateway.load_cube(cube_id, diagnostic_context=diagnostic_context)

    def list_cube_versions(self, cube_id: str) -> JsonObject:
        """Return versions for one cube id."""

        return self.gateway.list_cube_versions(cube_id)

    def load_cube_version(
        self,
        *,
        cube_id: str,
        version: str,
        diagnostic_context: DiagnosticContext | None = None,
    ) -> JsonObject:
        """Return one cube artifact by version."""

        return self.gateway.load_cube_version(
            cube_id=cube_id,
            version=version,
            diagnostic_context=diagnostic_context,
        )

    def prewarm_cube_version(
        self,
        *,
        cube_id: str,
        version: str,
    ) -> JsonObject:
        """Schedule a best-effort version artifact warmup."""

        return self.gateway.prewarm_cube_version(
            cube_id=cube_id,
            version=version,
        )

    def icon_asset(self, cube_id: str) -> tuple[bytes, str]:
        """Return icon bytes and media type for one cube."""

        return self.gateway.icon_asset(cube_id)

    def list_packs(self) -> JsonObject:
        """Return tracked Cube Packs."""

        return self.gateway.list_packs()

    def preflight_pack(self, *, owner: str, repo: str, branch: str) -> JsonObject:
        """Return candidate Cube Pack preflight results."""

        return self.gateway.preflight_pack(owner=owner, repo=repo, branch=branch)

    def add_pack(
        self,
        *,
        owner: str,
        repo: str,
        branch: str,
        enabled: bool,
        auto_update: bool,
        sync_immediately: bool,
    ) -> JsonObject:
        """Track one Cube Pack and optionally sync it before returning."""

        return self.gateway.add_pack(
            owner=owner,
            repo=repo,
            branch=branch,
            enabled=enabled,
            auto_update=auto_update,
            sync_immediately=sync_immediately,
        )

    def update_pack(
        self,
        *,
        owner: str,
        repo: str,
        branch: str | None,
        enabled: bool | None,
        auto_update: bool | None,
    ) -> JsonObject:
        """Update one tracked Cube Pack."""

        return self.gateway.update_pack(
            owner=owner,
            repo=repo,
            branch=branch,
            enabled=enabled,
            auto_update=auto_update,
        )

    def remove_pack(self, *, owner: str, repo: str) -> JsonObject:
        """Remove one tracked Cube Pack."""

        return self.gateway.remove_pack(owner=owner, repo=repo)

    def sync_pack(self, *, owner: str, repo: str) -> JsonObject:
        """Sync one tracked Cube Pack synchronously."""

        return self.gateway.sync_pack(owner=owner, repo=repo)

    def sync_all_packs(self) -> JsonObject:
        """Sync every enabled Cube Pack synchronously."""

        return self.gateway.sync_all_packs()

    def readiness(self) -> JsonObject:
        """Return read-only target dependency readiness."""

        return self.gateway.readiness()

    def dependency_readiness(self) -> JsonObject:
        """Return install-capable target dependency readiness."""

        return self.gateway.dependency_readiness()

    def repair_dependencies(
        self,
        *,
        baseline_only: bool,
        approved_node_ids: tuple[str, ...],
        sync_enabled_repos: bool,
    ) -> JsonObject:
        """Repair approved target dependencies."""

        return self.gateway.repair_dependencies(
            baseline_only=baseline_only,
            approved_node_ids=approved_node_ids,
            sync_enabled_repos=sync_enabled_repos,
        )


@dataclass(frozen=True)
class CubeLibraryServices:
    """Own Cube Library application services."""

    library: CubeLibraryService

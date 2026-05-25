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
"""Adapter from Substitute BackEnd Cube Library routes to SugarCubes."""

from __future__ import annotations

import importlib
import logging
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from substitute_backend.api.errors import BackendHttpError
from substitute_backend.api.serialization import JsonObject, require_json_object
from substitute_backend.features.cube_library.application import public_icon_descriptor
from substitute_backend.infrastructure.diagnostics import DiagnosticContext, DiagnosticLogger

SugarCubesServicesFactory = Callable[[Path], Any]
SUGARCUBES_EXTENSION_DIRECTORY = "SugarCubes"
SUGARCUBES_STATUS_SOURCE = "sugarcubes"
_LOGGER = logging.getLogger(__name__)


def _error_code_for_status(status: int) -> str:
    """Return a stable Cube Library error code for a SugarCubes HTTP status."""

    if status == 404:
        return "cube-library-not-found"
    if status == 409:
        return "cube-library-conflict"
    if status == 400:
        return "cube-library-invalid-request"
    if status == 422:
        return "cube-library-unprocessable"
    if status == 503:
        return "cube-library-unavailable"
    return "cube-library-failed"


class SugarCubesLibraryAdapter:
    """Isolate all SugarCubes imports and service calls."""

    def __init__(
        self,
        *,
        extension_root: Path,
        custom_nodes_root: Path | None = None,
        services_factory: SugarCubesServicesFactory | None = None,
        diagnostics: DiagnosticLogger | None = None,
    ) -> None:
        """Create an adapter rooted at the Substitute BackEnd extension."""

        self._extension_root = extension_root.resolve()
        self._custom_nodes_root = (
            custom_nodes_root.resolve()
            if custom_nodes_root is not None
            else self._extension_root.parent.resolve()
        )
        self._services_factory = services_factory
        self._diagnostics = diagnostics
        self._services: Any | None = None
        self._load_error: str = ""

    def status(self) -> JsonObject:
        """Return Cube Library availability without raising for missing SugarCubes."""

        try:
            return self._payload(self._library().library_status())
        except BackendHttpError as exc:
            return {
                "schemaVersion": 1,
                "available": False,
                "source": SUGARCUBES_STATUS_SOURCE,
                "catalogRevision": "",
                "packManagementSupported": False,
                "localAuthoringSupported": False,
                "readinessSupported": False,
                "errors": [{"code": exc.code, "message": exc.message}],
            }

    def catalog(
        self,
        *,
        include_disabled: bool,
        diagnostic_context: DiagnosticContext | None = None,
    ) -> JsonObject:
        """Return catalog metadata from SugarCubes services."""

        payload = self._call(
            lambda: self._library().list_library_catalog(include_disabled=include_disabled)
        )
        _rewrite_catalog_icon_descriptors(payload)
        cubes = payload.get("cubes")
        self._log_diagnostic(
            diagnostic_context,
            "backend_adapter_catalog_return",
            catalog_revision=payload.get("catalogRevision", ""),
            cube_count=len(cubes) if isinstance(cubes, list) else "",
        )
        return payload

    def subscribe_library_changes(
        self,
        listener: Callable[[Mapping[str, object]], None],
    ) -> Callable[[], None] | None:
        """Subscribe to SugarCubes generic library-change events when available."""

        try:
            library = self._library()
        except BackendHttpError:
            return None
        subscribe = getattr(library, "subscribe_library_changed", None)
        if not callable(subscribe):
            return None
        unsubscribe = subscribe(listener)
        if not callable(unsubscribe):
            return None
        return cast("Callable[[], None]", unsubscribe)

    def load_cube(
        self,
        cube_id: str,
        *,
        diagnostic_context: DiagnosticContext | None = None,
    ) -> JsonObject:
        """Return one canonical cube artifact from SugarCubes."""

        library = self._library()
        payload = self._call(lambda: library.load_library_cube(cube_id))
        self._rewrite_loaded_icon_descriptor(
            payload=payload,
            library=library,
            requested_cube_id=cube_id,
        )
        self._log_diagnostic(
            diagnostic_context,
            "backend_adapter_load_cube_return",
            requested_cube_id=cube_id,
            loaded_cube_id=payload.get("cubeId", ""),
            loaded_version=payload.get("version", ""),
            content_hash=payload.get("contentHash", ""),
        )
        return payload

    def list_cube_versions(self, cube_id: str) -> JsonObject:
        """Return versions available for one cube id from SugarCubes."""

        return self._call(lambda: self._library().list_library_cube_versions(cube_id))

    def load_cube_version(
        self,
        *,
        cube_id: str,
        version: str,
        diagnostic_context: DiagnosticContext | None = None,
    ) -> JsonObject:
        """Return one cube artifact selected by version."""

        library = self._library()
        payload = self._call(
            lambda: library.load_library_cube_version(
                cube_id=cube_id,
                version=version,
            )
        )
        self._rewrite_loaded_icon_descriptor(
            payload=payload,
            library=library,
            requested_cube_id=cube_id,
        )
        self._log_diagnostic(
            diagnostic_context,
            "backend_adapter_load_cube_return",
            requested_cube_id=cube_id,
            requested_version=version,
            loaded_cube_id=payload.get("cubeId", ""),
            loaded_version=payload.get("version", ""),
            content_hash=payload.get("contentHash", ""),
        )
        return payload

    def prewarm_cube_version(
        self,
        *,
        cube_id: str,
        version: str,
    ) -> JsonObject:
        """Ask SugarCubes to warm one cube version artifact asynchronously."""

        library = self._library()
        warm = getattr(library, "warm_library_cube_version", None)
        if not callable(warm):
            raise BackendHttpError(
                message="SugarCubes does not expose cube version prewarm.",
                status=503,
                code="sugarcubes-unavailable",
            )
        self._call(lambda: warm(cube_id=cube_id, version=version))
        return {"schemaVersion": 1, "accepted": True}

    def icon_asset(self, cube_id: str) -> tuple[bytes, str]:
        """Return icon bytes and media type through SugarCubes resolution."""

        try:
            icon_path, media_type = self._library().resolve_cube_icon_asset(cube_id)
            return Path(icon_path).read_bytes(), str(media_type)
        except BackendHttpError:
            raise
        except OSError as exc:
            raise BackendHttpError(
                message="Cube icon asset could not be read.",
                status=500,
                code="cube-icon-read-failed",
            ) from exc
        except Exception as exc:
            status = getattr(exc, "status", None)
            message = getattr(exc, "message", None)
            if isinstance(status, int) and isinstance(message, str):
                raise BackendHttpError(
                    message=message,
                    status=status,
                    code=_error_code_for_status(status),
                ) from exc
            raise

    def list_packs(self) -> JsonObject:
        """Return tracked Cube Packs from SugarCubes."""

        return self._call(lambda: self._library().list_library_packs())

    def preflight_pack(self, *, owner: str, repo: str, branch: str) -> JsonObject:
        """Return candidate Cube Pack preflight results from SugarCubes."""

        return self._call(
            lambda: self._library().preflight_library_pack(
                owner=owner,
                repo=repo,
                branch=branch,
            )
        )

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
        """Track one Cube Pack through SugarCubes."""

        return self._call(
            lambda: self._library().add_library_pack(
                owner=owner,
                repo=repo,
                branch=branch,
                enabled=enabled,
                auto_update=auto_update,
                sync_immediately=sync_immediately,
            )
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
        """Update one tracked Cube Pack through SugarCubes."""

        return self._call(
            lambda: self._library().update_library_pack(
                owner=owner,
                repo=repo,
                branch=branch,
                enabled=enabled,
                auto_update=auto_update,
            )
        )

    def remove_pack(self, *, owner: str, repo: str) -> JsonObject:
        """Remove one tracked Cube Pack through SugarCubes policy."""

        return self._call(lambda: self._library().remove_library_pack(owner=owner, repo=repo))

    def sync_pack(self, *, owner: str, repo: str) -> JsonObject:
        """Sync one tracked Cube Pack through SugarCubes synchronously."""

        return self._call(lambda: self._library().sync_library_pack(owner=owner, repo=repo))

    def sync_all_packs(self) -> JsonObject:
        """Sync enabled Cube Packs through SugarCubes synchronously."""

        return self._call(lambda: self._library().sync_all_library_packs())

    def readiness(self) -> JsonObject:
        """Return read-only dependency readiness from SugarCubes."""

        return self._call(lambda: self._library().library_readiness(self._custom_nodes_root))

    def dependency_readiness(self) -> JsonObject:
        """Return install-capable dependency readiness from SugarCubes."""

        return self._call(lambda: self._dependencies().readiness())

    def repair_dependencies(
        self,
        *,
        baseline_only: bool,
        approved_node_ids: tuple[str, ...],
        sync_enabled_repos: bool,
    ) -> JsonObject:
        """Forward dependency repair to SugarCubes without owning its logic."""

        approval_policy = "silent_baseline_only" if baseline_only else "approved_node_ids"
        return self._call(
            lambda: self._dependencies().repair(
                approval_policy=approval_policy,
                approved_node_ids=approved_node_ids,
                sync_enabled_repos=sync_enabled_repos,
            )
        )

    def _rewrite_loaded_icon_descriptor(
        self,
        *,
        payload: JsonObject,
        library: Any,
        requested_cube_id: str,
    ) -> None:
        """Attach a public icon descriptor to a loaded cube artifact when available."""

        cube_id = _read_text(payload.get("cubeId")) or requested_cube_id
        icon = public_icon_descriptor(cube_id=cube_id, icon=payload.get("icon"))
        if icon is None:
            icon = self._summary_icon_descriptor(
                library=library,
                cube_id=cube_id,
            )
        if icon is not None:
            payload["icon"] = icon
        else:
            payload.pop("icon", None)

    def _summary_icon_descriptor(
        self,
        *,
        library: Any,
        cube_id: str,
    ) -> JsonObject | None:
        """Return an icon descriptor from SugarCubes summary metadata."""

        resolve_cube_by_id = getattr(library, "resolve_cube_by_id", None)
        summarize_cube = getattr(library, "summarize_cube", None)
        if not callable(resolve_cube_by_id) or not callable(summarize_cube):
            return None
        try:
            summary = summarize_cube(resolve_cube_by_id(cube_id))
        except Exception as exc:  # pragma: no cover - host version variance
            _LOGGER.warning(
                "Skipped Cube Library icon descriptor derivation",
                extra={"cube_id": cube_id, "error": repr(exc)},
            )
            return None
        if not isinstance(summary, Mapping):
            return None
        return public_icon_descriptor(cube_id=cube_id, icon=summary.get("icon"))

    def _log_diagnostic(
        self,
        context: DiagnosticContext | None,
        event: str,
        **fields: object,
    ) -> None:
        """Emit one adapter diagnostic when a request explicitly enables it."""

        if context is None or self._diagnostics is None:
            return
        self._diagnostics.debug(context, event, fields)

    def _library(self) -> Any:
        """Return the SugarCubes library service or raise a typed HTTP error."""

        services = self._load_services()
        library = getattr(services, "library", None)
        if library is None:
            raise BackendHttpError(
                message="SugarCubes did not expose a library service.",
                status=503,
                code="sugarcubes-unavailable",
            )
        return library

    def _dependencies(self) -> Any:
        """Return the SugarCubes dependency service or raise a typed HTTP error."""

        services = self._load_services()
        dependencies = getattr(services, "dependencies", None)
        if dependencies is None:
            raise BackendHttpError(
                message="SugarCubes did not expose dependency maintenance.",
                status=503,
                code="sugarcubes-unavailable",
            )
        return dependencies

    def _load_services(self) -> Any:
        """Import SugarCubes services lazily so backend tests stay isolated."""

        if self._services is not None:
            return self._services
        try:
            if self._services_factory is not None:
                self._services = self._services_factory(self._sugarcubes_root())
            else:
                sugar_root = self._sugarcubes_root()
                if str(sugar_root) not in sys.path:
                    sys.path.insert(0, str(sugar_root))
                backend_module = importlib.import_module("backend")
                self._services = backend_module.build_backend_services(sugar_root)
        except BackendHttpError:
            raise
        except Exception as exc:  # pragma: no cover - host import variance
            self._load_error = str(exc)
            raise BackendHttpError(
                message="SugarCubes is not available on this target.",
                status=503,
                code="sugarcubes-unavailable",
            ) from exc
        return self._services

    def _sugarcubes_root(self) -> Path:
        """Locate the sibling SugarCubes extension root."""

        for candidate in self._custom_nodes_root.iterdir():
            if not candidate.is_dir():
                continue
            if candidate.name.lower() == SUGARCUBES_EXTENSION_DIRECTORY.lower():
                return candidate.resolve()
        raise BackendHttpError(
            message="SugarCubes is not available on this target.",
            status=503,
            code="sugarcubes-unavailable",
        )

    def _payload(self, value: object) -> JsonObject:
        """Validate gateway responses before they leave infrastructure."""

        try:
            return require_json_object(value)
        except TypeError as exc:
            raise BackendHttpError(
                message="Cube Library returned an invalid payload.",
                status=500,
                code="cube-library-invalid-payload",
            ) from exc

    def _call(self, operation: Callable[[], object]) -> JsonObject:
        """Run one SugarCubes operation and map expected backend errors."""

        try:
            return self._payload(operation())
        except BackendHttpError:
            raise
        except Exception as exc:
            status = getattr(exc, "status", None)
            message = getattr(exc, "message", None)
            if isinstance(status, int) and isinstance(message, str):
                raise BackendHttpError(
                    message=message,
                    status=status,
                    code=_error_code_for_status(status),
                ) from exc
            raise


def _rewrite_catalog_icon_descriptors(payload: JsonObject) -> None:
    """Rewrite catalog icon descriptors to Substitute-BackEnd URLs in place."""

    cubes = payload.get("cubes")
    if not isinstance(cubes, list):
        return
    for cube in cubes:
        if not isinstance(cube, dict):
            continue
        cube_id = _read_text(cube.get("cubeId"))
        icon = public_icon_descriptor(cube_id=cube_id, icon=cube.get("icon"))
        if icon is not None:
            cube["icon"] = icon
        else:
            cube.pop("icon", None)


def _read_text(value: object) -> str:
    """Read one stripped string value."""

    return value.strip() if isinstance(value, str) else ""

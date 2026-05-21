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
"""Adapter from SugarCubes cube-output hooks to Substitute websocket events."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, cast

from substitute_backend.features.cube_outputs.domain import (
    CubeOutputArtifactEvent,
    CubeOutputWebsocketEvent,
)
from substitute_backend.features.cube_outputs.domain.events import MediaKind
from substitute_backend.features.cube_outputs.infrastructure.prompt_server_publisher import (
    PromptServerCubeOutputPublisher,
)

SUGARCUBES_EXTENSION_DIRECTORY = "SugarCubes"
SUPPORTED_OBSERVER_API_VERSION = 1


class SugarCubesHookResolutionStatus(StrEnum):
    """Describe the outcome of resolving SugarCubes' observer hook."""

    RESOLVED = "resolved"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


class CubeOutputRegistrationStatus(StrEnum):
    """Describe one attempt to attach Substitute to SugarCubes output events."""

    REGISTERED = "registered"
    ALREADY_REGISTERED = "already_registered"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True)
class SugarCubesHookResolution:
    """Return a resolved hook or a typed reason registration cannot proceed yet."""

    status: SugarCubesHookResolutionStatus
    message: str
    hook: SugarCubesObserverHook | None = None


@dataclass(frozen=True)
class CubeOutputRegistrationResult:
    """Return a typed, logged result for one observer registration attempt."""

    status: CubeOutputRegistrationStatus
    message: str


class SugarCubesArtifactLike(Protocol):
    """Subset of a SugarCubes cube output artifact used for publication."""

    filename: str
    subfolder: str
    type: str
    media_kind: str
    mime_type: str | None
    width: int | None
    height: int | None
    duration_seconds: float | None


class SugarCubesEventLike(Protocol):
    """Subset of a SugarCubes cube output event used for publication."""

    version: int
    prompt_id: str | None
    node_id: str | None
    list_index: int | None
    cube_id: str
    default_alias: str
    instance_alias: str
    instance_id: str
    media_kind: str
    value_type: str
    artifacts: tuple[SugarCubesArtifactLike, ...]


class SugarCubesObserverHook(Protocol):
    """Registration functions exposed by the SugarCubes runtime hook."""

    @property
    def identity(self) -> str:
        """Return the process-local hook identity used for idempotency."""

    def register_cube_output_observer(self, observer: object) -> None:
        """Register one SugarCubes cube-output observer."""

    def unregister_cube_output_observer(self, observer: object) -> None:
        """Unregister one SugarCubes cube-output observer."""


class _ModuleSugarCubesObserverHook:
    """Wrap a loaded SugarCubes runtime module as an observer hook."""

    def __init__(self, *, module_name: str, module: object) -> None:
        """Store the loaded module and its import identity."""

        self._module_name = module_name
        self._module = module

    @property
    def identity(self) -> str:
        """Return the loaded module name used to resolve this hook."""

        return self._module_name

    def register_cube_output_observer(self, observer: object) -> None:
        """Register one observer through the SugarCubes module."""

        register = cast(Any, self._module).register_cube_output_observer
        cast(Callable[[object], None], register)(observer)

    def unregister_cube_output_observer(self, observer: object) -> None:
        """Unregister one observer through the SugarCubes module."""

        unregister = cast(Any, self._module).unregister_cube_output_observer
        cast(Callable[[object], None], unregister)(observer)


class SugarCubesObserverHookResolver:
    """Resolve SugarCubes' public runtime observer hook without importing it early."""

    def __init__(
        self,
        *,
        extension_root: Path,
        logger: logging.Logger,
        custom_nodes_root: Path | None = None,
    ) -> None:
        """Create a resolver rooted at Substitute BackEnd's extension path."""

        self._extension_root = extension_root.resolve()
        self._custom_nodes_root = (
            custom_nodes_root.resolve()
            if custom_nodes_root is not None
            else self._extension_root.parent.resolve()
        )
        self._logger = logger

    def resolve(self) -> SugarCubesHookResolution:
        """Return the already-loaded SugarCubes hook or a pending/unavailable result."""

        loaded_runtime = self._already_loaded_runtime_module()
        if loaded_runtime is not None:
            module_name, module = loaded_runtime
            api_error = _observer_api_error(module)
            if api_error is not None:
                self._logger.warning(
                    "SugarCubes observer hook unavailable; runtime API mismatch",
                    extra={"module_name": module_name, "reason": api_error},
                )
                return SugarCubesHookResolution(
                    status=SugarCubesHookResolutionStatus.UNAVAILABLE,
                    message=api_error,
                )
            return SugarCubesHookResolution(
                status=SugarCubesHookResolutionStatus.RESOLVED,
                message="SugarCubes runtime observer hook resolved.",
                hook=_ModuleSugarCubesObserverHook(module_name=module_name, module=module),
            )
        if not self._sugarcubes_root_exists():
            message = "SugarCubes extension was not found."
            self._logger.debug("SugarCubes observer hook unavailable; extension not found")
            return SugarCubesHookResolution(
                status=SugarCubesHookResolutionStatus.UNAVAILABLE,
                message=message,
            )
        message = "SugarCubes runtime is not loaded yet."
        self._logger.debug("SugarCubes observer hook pending; runtime is not loaded yet")
        return SugarCubesHookResolution(
            status=SugarCubesHookResolutionStatus.PENDING,
            message=message,
        )

    def _already_loaded_runtime_module(self) -> tuple[str, object] | None:
        """Return an already-loaded SugarCubes runtime module when present."""

        for module_name, module in _sugarcubes_runtime_modules(sys.modules.items()):
            return module_name, module
        return None

    def _sugarcubes_root_exists(self) -> bool:
        """Return whether the sibling SugarCubes extension root exists."""

        try:
            for candidate in self._custom_nodes_root.iterdir():
                if not candidate.is_dir():
                    continue
                if candidate.name.lower() == SUGARCUBES_EXTENSION_DIRECTORY.lower():
                    return True
        except OSError:
            self._logger.exception(
                "Failed to inspect custom nodes root for SugarCubes",
                extra={"custom_nodes_root": str(self._custom_nodes_root)},
            )
            return False
        return False


class SubstituteCubeOutputObserver:
    """Translate SugarCubes output events into Substitute websocket events."""

    def __init__(
        self,
        *,
        publisher: PromptServerCubeOutputPublisher,
        logger: logging.Logger,
    ) -> None:
        """Initialize the observer with its websocket publisher."""

        self._publisher = publisher
        self._logger = logger

    def on_cube_output(self, event: SugarCubesEventLike) -> None:
        """Publish one SugarCubes cube-output event for Substitute."""

        try:
            self._publisher.publish(_map_sugarcubes_event(event))
        except Exception:
            self._logger.exception(
                "Failed to handle SugarCubes cube-output event",
                extra={
                    "prompt_id": getattr(event, "prompt_id", None),
                    "node_id": getattr(event, "node_id", None),
                    "cube_id": getattr(event, "cube_id", None),
                },
            )


class SugarCubesCubeOutputRegistration:
    """Own idempotent registration with SugarCubes' observer registry."""

    def __init__(
        self,
        *,
        hook_resolver: SugarCubesObserverHookResolver,
        observer: SubstituteCubeOutputObserver,
        logger: logging.Logger,
    ) -> None:
        """Initialize registration with a lazy hook resolver."""

        self._hook_resolver = hook_resolver
        self._observer = observer
        self._logger = logger
        self._registered_hook_identity: str | None = None

    def register(self) -> CubeOutputRegistrationResult:
        """Register the Substitute observer when the canonical SugarCubes hook exists."""

        resolution = self._hook_resolver.resolve()
        if resolution.status is SugarCubesHookResolutionStatus.PENDING:
            self._logger.debug(
                "SugarCubes cube-output observer registration pending",
                extra={"reason": resolution.message},
            )
            return CubeOutputRegistrationResult(
                status=CubeOutputRegistrationStatus.PENDING,
                message=resolution.message,
            )
        if resolution.status is SugarCubesHookResolutionStatus.UNAVAILABLE:
            self._logger.warning(
                "SugarCubes cube-output observer registration unavailable",
                extra={"reason": resolution.message},
            )
            return CubeOutputRegistrationResult(
                status=CubeOutputRegistrationStatus.UNAVAILABLE,
                message=resolution.message,
            )
        hook = resolution.hook
        if hook is None:
            message = "SugarCubes hook resolution succeeded without a hook."
            self._logger.error(message)
            return CubeOutputRegistrationResult(
                status=CubeOutputRegistrationStatus.FAILED,
                message=message,
            )
        if self._registered_hook_identity == hook.identity:
            self._logger.debug(
                "SugarCubes cube-output observer already registered",
                extra={"hook_identity": hook.identity},
            )
            return CubeOutputRegistrationResult(
                status=CubeOutputRegistrationStatus.ALREADY_REGISTERED,
                message="SugarCubes cube-output observer is already registered.",
            )
        try:
            hook.register_cube_output_observer(self._observer)
        except Exception:
            self._logger.exception(
                "Failed to register SugarCubes cube-output observer",
                extra={"hook_identity": hook.identity},
            )
            return CubeOutputRegistrationResult(
                status=CubeOutputRegistrationStatus.FAILED,
                message="Failed to register SugarCubes cube-output observer.",
            )
        self._registered_hook_identity = hook.identity
        self._logger.info(
            "SugarCubes cube-output observer registered",
            extra={"hook_identity": hook.identity},
        )
        return CubeOutputRegistrationResult(
            status=CubeOutputRegistrationStatus.REGISTERED,
            message="SugarCubes cube-output observer registered.",
        )


def _sugarcubes_runtime_modules(
    modules: Iterable[tuple[str, object]],
) -> Iterable[tuple[str, object]]:
    """Yield loaded runtime modules whose identity belongs to SugarCubes."""

    for module_name, module in tuple(modules):
        if not _is_sugarcubes_runtime_module_name(module_name):
            continue
        yield module_name, module


def _is_sugarcubes_runtime_module_name(module_name: str) -> bool:
    """Return whether a module name represents SugarCubes' runtime package."""

    normalized = module_name.replace("\\", ".").replace("/", ".").lower()
    return normalized == "sugarcubes.runtime" or normalized.endswith(".sugarcubes.runtime")


def _observer_api_error(module: object) -> str | None:
    """Return an API mismatch reason, or ``None`` when the runtime API is supported."""

    if not callable(getattr(module, "register_cube_output_observer", None)):
        return "SugarCubes runtime does not expose register_cube_output_observer."
    if not callable(getattr(module, "unregister_cube_output_observer", None)):
        return "SugarCubes runtime does not expose unregister_cube_output_observer."
    version = getattr(module, "CUBE_OUTPUT_OBSERVER_API_VERSION", SUPPORTED_OBSERVER_API_VERSION)
    if version != SUPPORTED_OBSERVER_API_VERSION:
        return (
            "SugarCubes runtime observer API version "
            f"{version!r} is not supported; expected {SUPPORTED_OBSERVER_API_VERSION}."
        )
    return None


def _map_sugarcubes_event(event: SugarCubesEventLike) -> CubeOutputWebsocketEvent:
    """Map SugarCubes' neutral event object to Substitute's public payload."""

    return CubeOutputWebsocketEvent(
        prompt_id=event.prompt_id,
        node_id=event.node_id,
        list_index=event.list_index,
        cube_id=event.cube_id,
        default_alias=event.default_alias,
        instance_alias=event.instance_alias,
        instance_id=event.instance_id,
        media_kind=_media_kind(event.media_kind),
        value_type=event.value_type,
        artifacts=tuple(_map_artifact(artifact) for artifact in event.artifacts),
        version=1,
    )


def _map_artifact(artifact: SugarCubesArtifactLike) -> CubeOutputArtifactEvent:
    """Map one SugarCubes artifact to the Substitute websocket payload."""

    return CubeOutputArtifactEvent(
        filename=artifact.filename,
        subfolder=artifact.subfolder,
        type=artifact.type,
        media_kind=_media_kind(artifact.media_kind),
        mime_type=artifact.mime_type,
        width=artifact.width,
        height=artifact.height,
        duration_seconds=artifact.duration_seconds,
    )


def _media_kind(value: str) -> MediaKind:
    """Normalize media-kind strings to Substitute's versioned contract."""

    if value in {"image", "audio", "video", "value", "unknown"}:
        return cast(MediaKind, value)
    return "unknown"

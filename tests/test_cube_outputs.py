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
"""Tests for SugarCubes cube-output websocket publishing."""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

from substitute_backend.features.cube_outputs.domain import (
    CubeOutputArtifactEvent,
    CubeOutputWebsocketEvent,
)
from substitute_backend.features.cube_outputs.infrastructure.prompt_server_publisher import (
    EVENT_TYPE,
    PromptServerCubeOutputPublisher,
)
from substitute_backend.features.cube_outputs.infrastructure.sugarcubes_observer import (
    CubeOutputRegistrationStatus,
    SubstituteCubeOutputObserver,
    SugarCubesCubeOutputRegistration,
    SugarCubesHookResolution,
    SugarCubesHookResolutionStatus,
    SugarCubesObserverHookResolver,
)
from substitute_backend.features.prompt_queue.application.run_context_store import (
    SubstituteRunContextStore,
)
from substitute_backend.features.prompt_queue.domain.run_context import (
    SubstituteRunContext,
    SubstituteSourceRoute,
)


class _PromptServer:
    """Collect PromptServer websocket sends."""

    client_id = "client-1"

    def __init__(self) -> None:
        """Initialize an empty send list."""

        self.sent: list[tuple[str, object, str | None]] = []

    def send_sync(self, event: str, data: object, sid: str | None = None) -> None:
        """Collect one sent event."""

        self.sent.append((event, data, sid))


class _FailingPromptServer:
    """Raise from PromptServer sends."""

    client_id = None

    def send_sync(self, _event: str, _data: object, _sid: str | None = None) -> None:
        """Fail one send."""

        raise RuntimeError("send failed")


class _Hook:
    """Collect SugarCubes observer registrations."""

    identity = "test-hook"
    CUBE_OUTPUT_OBSERVER_API_VERSION = 1

    def __init__(self) -> None:
        """Initialize empty observer lists."""

        self.registered: list[object] = []
        self.unregistered: list[object] = []

    def register_cube_output_observer(self, observer: object) -> None:
        """Collect one observer registration."""

        self.registered.append(observer)

    def unregister_cube_output_observer(self, observer: object) -> None:
        """Collect one observer unregistration."""

        self.unregistered.append(observer)


def test_cube_output_event_payload_matches_public_contract() -> None:
    """Cube-output domain events should serialize the versioned websocket payload."""

    event = CubeOutputWebsocketEvent(
        prompt_id="prompt-1",
        node_id="node-1",
        list_index=0,
        cube_id="owner/repo/demo.cube",
        default_alias="Demo",
        instance_alias="Demo Instance",
        instance_id="instance-1",
        media_kind="image",
        value_type="torch.Tensor",
        artifacts=(
            CubeOutputArtifactEvent(
                filename="ComfyUI_temp_demo_00001_.png",
                subfolder="",
                type="temp",
                media_kind="image",
                mime_type="image/png",
                width=64,
                height=32,
            ),
        ),
    )

    assert event.to_payload() == {
        "version": 1,
        "prompt_id": "prompt-1",
        "node_id": "node-1",
        "list_index": 0,
        "cube_id": "owner/repo/demo.cube",
        "default_alias": "Demo",
        "instance_alias": "Demo Instance",
        "instance_id": "instance-1",
        "media_kind": "image",
        "value_type": "torch.Tensor",
        "artifacts": [
            {
                "filename": "ComfyUI_temp_demo_00001_.png",
                "subfolder": "",
                "type": "temp",
                "media_kind": "image",
                "mime_type": "image/png",
                "width": 64,
                "height": 32,
            }
        ],
    }


def test_prompt_server_cube_output_publisher_sends_event() -> None:
    """PromptServer publisher should send the cube-output event name and payload."""

    prompt_server = _PromptServer()
    publisher = PromptServerCubeOutputPublisher(
        prompt_server=prompt_server,
        logger=logging.getLogger("test.cube_outputs.publisher"),
    )
    event = CubeOutputWebsocketEvent(
        prompt_id=None,
        node_id="node-1",
        list_index=None,
        cube_id="owner/repo/demo.cube",
        default_alias="Demo",
        instance_alias="Demo",
        instance_id="instance-1",
        media_kind="value",
        value_type="builtins.str",
        artifacts=(),
    )

    publisher.publish(event)

    assert prompt_server.sent == [(EVENT_TYPE, event.to_payload(), "client-1")]


def test_prompt_server_cube_output_publisher_swallows_send_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PromptServer send failures should not raise into Comfy execution."""

    publisher = PromptServerCubeOutputPublisher(
        prompt_server=_FailingPromptServer(),
        logger=logging.getLogger("test.cube_outputs.publisher.failure"),
    )

    with caplog.at_level(logging.ERROR):
        publisher.publish(
            CubeOutputWebsocketEvent(
                prompt_id="prompt-1",
                node_id="node-1",
                list_index=None,
                cube_id="owner/repo/demo.cube",
                default_alias="Demo",
                instance_alias="Demo",
                instance_id="instance-1",
                media_kind="value",
                value_type="builtins.str",
                artifacts=(),
            )
        )

    assert "Failed to publish cube-output event" in caplog.text


def test_observer_adapter_maps_sugarcubes_event_to_substitute_payload() -> None:
    """Observer adapter should translate SugarCubes events before publishing."""

    prompt_server = _PromptServer()
    publisher = PromptServerCubeOutputPublisher(
        prompt_server=prompt_server,
        logger=logging.getLogger("test.cube_outputs.publisher"),
    )
    observer = SubstituteCubeOutputObserver(
        publisher=publisher,
        logger=logging.getLogger("test.cube_outputs.observer"),
    )
    sugar_event = types.SimpleNamespace(
        version=1,
        prompt_id="prompt-1",
        node_id="node-1",
        list_index=2,
        cube_id="owner/repo/demo.cube",
        default_alias="Demo",
        instance_alias="Demo Instance",
        instance_id="instance-1",
        media_kind="image",
        value_type="torch.Tensor",
        artifacts=(
            types.SimpleNamespace(
                filename="image.png",
                subfolder="",
                type="temp",
                media_kind="image",
                mime_type="image/png",
                width=16,
                height=8,
                duration_seconds=None,
            ),
        ),
    )

    observer.on_cube_output(cast(Any, sugar_event))

    assert prompt_server.sent[0][0] == EVENT_TYPE
    payload = prompt_server.sent[0][1]
    assert isinstance(payload, dict)
    assert payload["prompt_id"] == "prompt-1"
    assert payload["node_id"] == "node-1"
    assert payload["artifacts"] == [
        {
            "filename": "image.png",
            "subfolder": "",
            "type": "temp",
            "media_kind": "image",
            "mime_type": "image/png",
            "width": 16,
            "height": 8,
        }
    ]


def test_observer_enriches_cube_output_with_substitute_context() -> None:
    """Observer should publish v2 cube-output events to the run client id."""

    prompt_server = _PromptServer()
    publisher = PromptServerCubeOutputPublisher(
        prompt_server=prompt_server,
        logger=logging.getLogger("test.cube_outputs.publisher"),
    )
    run_context_store = SubstituteRunContextStore()
    run_context_store.store(
        prompt_id="prompt-1",
        context=SubstituteRunContext(
            workflow_id="wf-1",
            generation_run_id="run-1",
            client_id="client-run",
            scene_key="scene-a",
            sources={
                "node-1": SubstituteSourceRoute(
                    source_key="wf-1:node-1",
                    source_label="Demo",
                    cube_alias="Demo",
                )
            },
        ),
        executable_prompt={"node-1": {}},
    )
    observer = SubstituteCubeOutputObserver(
        publisher=publisher,
        logger=logging.getLogger("test.cube_outputs.observer"),
        run_context_store=run_context_store,
    )
    sugar_event = types.SimpleNamespace(
        version=1,
        prompt_id="prompt-1",
        node_id="node-1",
        list_index=2,
        cube_id="owner/repo/demo.cube",
        default_alias="Demo",
        instance_alias="Demo",
        instance_id="instance-1",
        media_kind="image",
        value_type="torch.Tensor",
        artifacts=(),
    )

    observer.on_cube_output(cast(Any, sugar_event))

    assert prompt_server.sent[0][2] == "client-run"
    payload = prompt_server.sent[0][1]
    assert isinstance(payload, dict)
    assert payload["version"] == 2
    assert payload["substitute"] == {
        "schemaVersion": 1,
        "workflowId": "wf-1",
        "generationRunId": "run-1",
        "clientId": "client-run",
        "sourceKey": "wf-1:node-1",
        "sourceLabel": "Demo",
        "sceneKey": "scene-a",
    }


def test_observer_skips_unresolved_cube_output_when_context_required(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Observer should not fabricate identity for unknown prompt/node outputs."""

    prompt_server = _PromptServer()
    observer = SubstituteCubeOutputObserver(
        publisher=PromptServerCubeOutputPublisher(
            prompt_server=prompt_server,
            logger=logging.getLogger("test.cube_outputs.publisher"),
        ),
        logger=logging.getLogger("test.cube_outputs.observer.unresolved"),
        run_context_store=SubstituteRunContextStore(),
    )
    sugar_event = types.SimpleNamespace(
        version=1,
        prompt_id="missing-prompt",
        node_id="node-1",
        list_index=0,
        cube_id="owner/repo/demo.cube",
        default_alias="Demo",
        instance_alias="Demo",
        instance_id="instance-1",
        media_kind="image",
        value_type="torch.Tensor",
        artifacts=(),
    )

    with caplog.at_level(logging.WARNING):
        observer.on_cube_output(cast(Any, sugar_event))

    assert prompt_server.sent == []
    assert any(
        getattr(record, "reason", None) == "unknown_prompt_context" for record in caplog.records
    )


def test_hook_resolver_reports_unavailable_when_sugarcubes_is_missing(
    tmp_path: Path,
) -> None:
    """Hook resolution should disable publishing when SugarCubes is not installed."""

    extension_root = tmp_path / "Substitute-BackEnd"
    extension_root.mkdir()

    resolver = SugarCubesObserverHookResolver(
        extension_root=extension_root,
        logger=logging.getLogger("test.cube_outputs.resolver"),
        custom_nodes_root=tmp_path,
    )

    resolution = resolver.resolve()

    assert resolution.status is SugarCubesHookResolutionStatus.UNAVAILABLE
    assert resolution.hook is None


def test_hook_resolver_does_not_import_sibling_sugarcubes_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Hook resolution should wait for Comfy to load SugarCubes' runtime module."""

    extension_root = tmp_path / "Substitute-BackEnd"
    sugar_root = tmp_path / "SugarCubes"
    extension_root.mkdir()
    sugar_root.mkdir()
    monkeypatch.delitem(sys.modules, "runtime", raising=False)

    resolver = SugarCubesObserverHookResolver(
        extension_root=extension_root,
        logger=logging.getLogger("test.cube_outputs.resolver"),
        custom_nodes_root=tmp_path,
    )

    resolution = resolver.resolve()

    assert resolution.status is SugarCubesHookResolutionStatus.PENDING
    assert resolution.hook is None
    assert "runtime" not in sys.modules


def test_hook_resolver_ignores_old_prefixed_sugarcubes_folder(tmp_path: Path) -> None:
    """Hook resolution should not treat the old prefixed folder as SugarCubes."""

    extension_root = tmp_path / "Substitute-BackEnd"
    old_sugar_root = tmp_path / "ComfyUI-SugarCubes"
    extension_root.mkdir()
    old_sugar_root.mkdir()
    resolver = SugarCubesObserverHookResolver(
        extension_root=extension_root,
        logger=logging.getLogger("test.cube_outputs.resolver.old_name"),
        custom_nodes_root=tmp_path,
    )

    resolution = resolver.resolve()

    assert resolution.status is SugarCubesHookResolutionStatus.UNAVAILABLE
    assert resolution.hook is None


def test_hook_resolver_reuses_loaded_packaged_sugarcubes_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Hook resolution should reuse Comfy's already-loaded SugarCubes runtime module."""

    extension_root = tmp_path / "Substitute-BackEnd"
    extension_root.mkdir()
    hook = _Hook()
    monkeypatch.setitem(sys.modules, "custom_nodes.SugarCubes.runtime", hook)

    resolver = SugarCubesObserverHookResolver(
        extension_root=extension_root,
        logger=logging.getLogger("test.cube_outputs.resolver.loaded"),
        custom_nodes_root=tmp_path,
    )

    resolution = resolver.resolve()

    assert resolution.status is SugarCubesHookResolutionStatus.RESOLVED
    assert resolution.hook is not None
    observer = object()
    resolution.hook.register_cube_output_observer(observer)
    assert hook.registered == [observer]


def test_registration_is_idempotent() -> None:
    """Registration should not duplicate observer delivery across repeated setup."""

    hook = _Hook()
    resolver = cast(
        Any,
        types.SimpleNamespace(
            resolve=lambda: SugarCubesHookResolution(
                status=SugarCubesHookResolutionStatus.RESOLVED,
                message="resolved",
                hook=hook,
            )
        ),
    )
    observer = SubstituteCubeOutputObserver(
        publisher=PromptServerCubeOutputPublisher(
            prompt_server=_PromptServer(),
            logger=logging.getLogger("test.cube_outputs.publisher"),
        ),
        logger=logging.getLogger("test.cube_outputs.observer"),
    )
    registration = SugarCubesCubeOutputRegistration(
        hook_resolver=resolver,
        observer=observer,
        logger=logging.getLogger("test.cube_outputs.registration"),
    )

    assert registration.register().status is CubeOutputRegistrationStatus.REGISTERED
    assert registration.register().status is CubeOutputRegistrationStatus.ALREADY_REGISTERED
    assert hook.registered == [observer]


def test_registration_retries_after_pending_resolution() -> None:
    """Registration should be safe to retry when SugarCubes loads after Substitute."""

    hook = _Hook()
    resolutions = [
        SugarCubesHookResolution(
            status=SugarCubesHookResolutionStatus.PENDING,
            message="SugarCubes runtime is not loaded yet.",
        ),
        SugarCubesHookResolution(
            status=SugarCubesHookResolutionStatus.RESOLVED,
            message="resolved",
            hook=hook,
        ),
        SugarCubesHookResolution(
            status=SugarCubesHookResolutionStatus.RESOLVED,
            message="resolved",
            hook=hook,
        ),
    ]
    resolver = cast(Any, types.SimpleNamespace(resolve=lambda: resolutions.pop(0)))
    observer = SubstituteCubeOutputObserver(
        publisher=PromptServerCubeOutputPublisher(
            prompt_server=_PromptServer(),
            logger=logging.getLogger("test.cube_outputs.publisher"),
        ),
        logger=logging.getLogger("test.cube_outputs.observer"),
    )
    registration = SugarCubesCubeOutputRegistration(
        hook_resolver=resolver,
        observer=observer,
        logger=logging.getLogger("test.cube_outputs.registration.retry"),
    )

    assert registration.register().status is CubeOutputRegistrationStatus.PENDING
    assert registration.register().status is CubeOutputRegistrationStatus.REGISTERED
    assert registration.register().status is CubeOutputRegistrationStatus.ALREADY_REGISTERED
    assert hook.registered == [observer]

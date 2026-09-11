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
"""Tests for Substitute context capture at SugarCubes' native queue boundary."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import pytest

from substitute_backend.features.prompt_queue.application.run_context_store import (
    SubstituteRunContextStore,
)
from substitute_backend.features.prompt_queue.infrastructure.sugarcubes_queue_context import (
    SugarCubesQueueContextObserver,
)
from substitute_backend.features.sugarcubes_integration.queue_context_registration import (
    SugarCubesQueueContextRegistration,
)
from substitute_backend.infrastructure.sugarcubes_host_api import (
    SugarCubesHostApi,
    SugarCubesHostApiResolution,
    SugarCubesHostApiResolutionStatus,
    SugarCubesHostApiResolver,
)


@dataclass(frozen=True)
class _ValidatedQueueEvent:
    """Provide the structural queue event consumed by the observer."""

    prompt_id: str
    prompt: object
    extra_data: object
    report: object | None = None


class _HostApi:
    """Capture the exact callable registered at the cross-extension boundary."""

    def __init__(self) -> None:
        """Initialize empty registration state."""

        self.observer: Callable[[object], None] | None = None
        self.required = False

    def register_validated_queue_observer(
        self,
        observer: object,
        *,
        required: bool = False,
    ) -> None:
        """Retain a callable observer and its fail-closed policy."""

        assert callable(observer)
        self.observer = observer
        self.required = required


class _Resolver:
    """Resolve one configured host API for registration tests."""

    def __init__(self, api: _HostApi) -> None:
        """Store the API returned by resolve."""

        self._api = api

    def resolve(self) -> SugarCubesHostApiResolution:
        """Return a successful structural resolution."""

        return SugarCubesHostApiResolution(
            status=SugarCubesHostApiResolutionStatus.RESOLVED,
            message="resolved",
            api=cast(SugarCubesHostApi, self._api),
        )


def test_native_queue_observer_stores_substitute_context_before_queueing() -> None:
    """A validated native prompt should retain its Substitute visual routing context."""

    store = SubstituteRunContextStore(time_source=lambda: 123.0)
    observer = SugarCubesQueueContextObserver(run_context_store=store)

    observer.on_validated_queue(
        _ValidatedQueueEvent(
            prompt_id="prompt-1",
            prompt={"5": {"class_type": "TestNode", "inputs": {}}},
            extra_data={"substitute": _substitute_context()},
        )
    )

    context = store.resolve("prompt-1")
    assert context is not None
    assert context.workflow_id == "wf-1"
    assert context.sources["5"].source_label == "CubeA"


def test_native_queue_observer_ignores_non_substitute_comfy_prompts() -> None:
    """Ordinary Comfy queue traffic should not create Substitute-owned context."""

    store = SubstituteRunContextStore()
    observer = SugarCubesQueueContextObserver(run_context_store=store)

    observer.on_validated_queue(
        _ValidatedQueueEvent(prompt_id="prompt-1", prompt={}, extra_data={})
    )

    assert store.resolve("prompt-1") is None


def test_native_queue_observer_derives_output_sources_from_execution_report() -> None:
    """SugarCubes output identities should become BackEnd routing sources atomically."""

    @dataclass(frozen=True)
    class _OutputIdentity:
        """Provide one SugarCubes report output identity."""

        execution_id: str
        instance_id: str
        instance_alias: str | None

    @dataclass(frozen=True)
    class _Report:
        """Provide the output-identity portion of a SugarCubes execution report."""

        output_identities: tuple[_OutputIdentity, ...]

    store = SubstituteRunContextStore()
    observer = SugarCubesQueueContextObserver(run_context_store=store)
    context = _substitute_context()
    context.pop("sources")

    observer.on_validated_queue(
        _ValidatedQueueEvent(
            prompt_id="prompt-1",
            prompt={"output-1": {"class_type": "SugarCubes.CubeOutput"}},
            extra_data={"substitute": context},
            report=_Report((_OutputIdentity("output-1", "instance-a", "CubeA"),)),
        )
    )

    stored = store.resolve("prompt-1")
    assert stored is not None
    assert stored.sources["output-1"].source_key == "cube:instance-a"
    assert stored.sources["output-1"].source_label == "CubeA"


def test_native_queue_observer_uses_substitute_cube_presentation_labels() -> None:
    """Use pre-queue presentation labels instead of qualified execution aliases."""

    @dataclass(frozen=True)
    class _OutputIdentity:
        """Provide one SugarCubes report output identity."""

        execution_id: str
        instance_id: str
        instance_alias: str

    @dataclass(frozen=True)
    class _Report:
        """Provide output identities after SugarCubes lowers the graph."""

        output_identities: tuple[_OutputIdentity, ...]

    store = SubstituteRunContextStore()
    observer = SugarCubesQueueContextObserver(run_context_store=store)
    context = _substitute_context()
    context.pop("sources")
    context["cubePresentations"] = {"instance-a": "Prompt by Region"}

    observer.on_validated_queue(
        _ValidatedQueueEvent(
            prompt_id="prompt-1",
            prompt={"output-1": {"class_type": "SugarCubes.CubeOutput"}},
            extra_data={"substitute": context},
            report=_Report(
                (
                    _OutputIdentity(
                        "output-1",
                        "instance-a",
                        "Anima/Prompt by Region",
                    ),
                )
            ),
        )
    )

    stored = store.resolve("prompt-1")
    assert stored is not None
    assert stored.sources["output-1"].source_key == "cube:instance-a"
    assert stored.sources["output-1"].source_label == "Prompt by Region"


def test_native_queue_observer_routes_every_cube_owned_execution_node() -> None:
    """Internal lowered nodes should carry Cube identity for previews and timing."""

    @dataclass(frozen=True)
    class _ExecutionIdentity:
        """Provide one SugarCubes lowered-node identity."""

        execution_id: str
        instance_id: str
        instance_alias: str

    @dataclass(frozen=True)
    class _Report:
        """Provide the node-identity portion of a SugarCubes execution report."""

        execution_node_identities: tuple[_ExecutionIdentity, ...]

    store = SubstituteRunContextStore()
    observer = SugarCubesQueueContextObserver(run_context_store=store)
    context = _substitute_context()
    context.pop("sources")

    observer.on_validated_queue(
        _ValidatedQueueEvent(
            prompt_id="prompt-1",
            prompt={"cube-a:sampler": {"class_type": "KSampler"}},
            extra_data={"substitute": context},
            report=_Report((_ExecutionIdentity("cube-a:sampler", "instance-a", "CubeA"),)),
        )
    )

    stored = store.resolve("prompt-1")
    assert stored is not None
    assert stored.sources["cube-a:sampler"].source_key == "cube:instance-a"
    assert stored.sources["cube-a:sampler"].source_label == "CubeA"


def test_native_queue_observer_rejects_malformed_substitute_context() -> None:
    """Malformed claimed Substitute context must stop queue insertion fail-closed."""

    observer = SugarCubesQueueContextObserver(run_context_store=SubstituteRunContextStore())

    with pytest.raises(ValueError, match="Substitute run context"):
        observer.on_validated_queue(
            _ValidatedQueueEvent(
                prompt_id="prompt-1",
                prompt={},
                extra_data={"substitute": {"schemaVersion": 1}},
            )
        )


def test_registration_passes_the_observer_method_as_a_required_callable() -> None:
    """Registration must give SugarCubes a callable instead of its owning object."""

    store = SubstituteRunContextStore()
    observer = SugarCubesQueueContextObserver(run_context_store=store)
    api = _HostApi()
    registration = SugarCubesQueueContextRegistration(
        observer=observer,
        logger=logging.getLogger(__name__),
        host_api_resolver=cast(SugarCubesHostApiResolver, _Resolver(api)),
    )

    registration.register()

    assert api.required is True
    assert api.observer is not None
    api.observer(
        _ValidatedQueueEvent(
            prompt_id="prompt-registered",
            prompt={"5": {"class_type": "TestNode", "inputs": {}}},
            extra_data={"substitute": _substitute_context()},
        )
    )
    assert store.resolve("prompt-registered") is not None


def _substitute_context() -> dict[str, object]:
    """Return a valid app-owned visual routing payload."""

    return {
        "schemaVersion": 1,
        "workflowId": "wf-1",
        "generationRunId": "run-1",
        "clientId": "client-1",
        "sources": {
            "5": {
                "sourceKey": "wf-1:5",
                "sourceLabel": "CubeA",
                "cubeAlias": "CubeA",
            }
        },
    }

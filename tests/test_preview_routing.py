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
"""Tests for Backend preview metadata enrichment."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from substitute_backend.features.preview_routing import (
    PreviewMetadataEnrichmentInstaller,
)
from substitute_backend.features.prompt_queue.application.run_context_store import (
    SubstituteRunContextStore,
)
from substitute_backend.features.prompt_queue.domain.run_context import (
    SubstituteRunContext,
    SubstituteSourceRoute,
)


class _PromptServer:
    """Collect preview metadata sends without altering image bytes."""

    def __init__(self) -> None:
        """Initialize send capture."""

        self.sent: list[tuple[bytes, object, str | None]] = []

    def send_image_with_metadata(
        self,
        image_data: bytes,
        metadata: object,
        sid: str | None = None,
    ) -> None:
        """Collect one preview send."""

        self.sent.append((image_data, metadata, sid))


class _AsyncPromptServer:
    """Collect async preview metadata sends like current Comfy PromptServer."""

    def __init__(self) -> None:
        """Initialize send capture."""

        self.sent: list[tuple[bytes, object, str | None]] = []

    async def send_image_with_metadata(
        self,
        image_data: bytes,
        metadata: object,
        sid: str | None = None,
    ) -> None:
        """Collect one awaited preview send."""

        self.sent.append((image_data, metadata, sid))


def test_preview_metadata_enrichment_adds_substitute_identity() -> None:
    """Preview hook should enrich known prompt/node metadata before Comfy sends it."""

    prompt_server = _AsyncPromptServer()
    run_context_store = SubstituteRunContextStore()
    run_context_store.store(
        prompt_id="prompt-1",
        context=SubstituteRunContext(
            workflow_id="wf-1",
            generation_run_id="run-1",
            client_id="client-1",
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
    installer = PreviewMetadataEnrichmentInstaller(
        prompt_server=prompt_server,
        run_context_store=run_context_store,
        logger=logging.getLogger("tests.preview_routing"),
    )

    assert installer.install() is True
    assert installer.install() is False
    asyncio.run(
        cast(Any, prompt_server).send_image_with_metadata(
            b"preview-bytes",
            {"prompt_id": "prompt-1", "node_id": "node-1"},
            "client-1",
        )
    )

    image_bytes, metadata, sid = prompt_server.sent[0]
    assert image_bytes == b"preview-bytes"
    assert sid == "client-1"
    assert metadata == {
        "prompt_id": "prompt-1",
        "node_id": "node-1",
        "substitute": {
            "schemaVersion": 1,
            "workflowId": "wf-1",
            "generationRunId": "run-1",
            "clientId": "client-1",
            "sourceKey": "wf-1:node-1",
            "sourceLabel": "Demo",
        },
    }


def test_preview_metadata_enrichment_supports_legacy_sync_sender() -> None:
    """Preview hook should also delegate when the original sender is synchronous."""

    prompt_server = _PromptServer()
    run_context_store = SubstituteRunContextStore()
    run_context_store.store(
        prompt_id="prompt-1",
        context=SubstituteRunContext(
            workflow_id="wf-1",
            generation_run_id="run-1",
            client_id="client-1",
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
    installer = PreviewMetadataEnrichmentInstaller(
        prompt_server=prompt_server,
        run_context_store=run_context_store,
        logger=logging.getLogger("tests.preview_routing.sync"),
    )

    assert installer.install() is True
    asyncio.run(
        cast(Any, prompt_server).send_image_with_metadata(
            b"preview-bytes",
            {"prompt_id": "prompt-1", "node_id": "node-1"},
            "client-1",
        )
    )

    assert prompt_server.sent[0][1] == {
        "prompt_id": "prompt-1",
        "node_id": "node-1",
        "substitute": {
            "schemaVersion": 1,
            "workflowId": "wf-1",
            "generationRunId": "run-1",
            "clientId": "client-1",
            "sourceKey": "wf-1:node-1",
            "sourceLabel": "Demo",
        },
    }


def test_preview_metadata_enrichment_leaves_unknown_frames_unresolved() -> None:
    """Preview hook should not guess Substitute identity for unknown metadata."""

    prompt_server = _AsyncPromptServer()
    installer = PreviewMetadataEnrichmentInstaller(
        prompt_server=prompt_server,
        run_context_store=SubstituteRunContextStore(),
        logger=logging.getLogger("tests.preview_routing.unknown"),
    )

    assert installer.install() is True
    asyncio.run(
        cast(Any, prompt_server).send_image_with_metadata(
            b"preview-bytes",
            {"prompt_id": "missing-prompt", "node_id": "node-1"},
            "client-1",
        )
    )

    image_bytes, metadata, sid = prompt_server.sent[0]
    assert image_bytes == b"preview-bytes"
    assert sid == "client-1"
    assert metadata == {"prompt_id": "missing-prompt", "node_id": "node-1"}

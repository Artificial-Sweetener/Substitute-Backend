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
"""Patch Comfy preview metadata frames with Substitute visual identity."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, MutableMapping
from inspect import isawaitable
from typing import Any, Protocol, cast

from substitute_backend.features.prompt_queue.application import (
    SubstituteRunContextStore,
)

_INSTALLED_FLAG = "_substitute_preview_metadata_enrichment_installed"


class PromptServerPreviewLike(Protocol):
    """Subset of PromptServer used by preview metadata enrichment."""

    def send_image_with_metadata(
        self,
        image_data: bytes,
        metadata: MutableMapping[str, object],
        sid: str | None = None,
    ) -> Awaitable[None] | None:
        """Send a Comfy metadata-bearing binary preview frame."""


class PreviewMetadataEnrichmentInstaller:
    """Install an idempotent runtime adapter for Comfy preview metadata."""

    def __init__(
        self,
        *,
        prompt_server: object,
        run_context_store: SubstituteRunContextStore,
        logger: logging.Logger,
    ) -> None:
        """Capture the PromptServer instance and shared run-context store."""

        self._prompt_server = prompt_server
        self._run_context_store = run_context_store
        self._logger = logger

    def install(self) -> bool:
        """Wrap PromptServer preview metadata sending when available."""

        if bool(getattr(self._prompt_server, _INSTALLED_FLAG, False)):
            return False
        original = getattr(self._prompt_server, "send_image_with_metadata", None)
        if not callable(original):
            self._logger.warning(
                "Preview metadata enrichment unavailable; PromptServer lacks sender",
                extra={"reason": "missing_send_image_with_metadata"},
            )
            return False

        async def enriched_send_image_with_metadata(
            image_data: bytes,
            metadata: MutableMapping[str, object],
            sid: str | None = None,
        ) -> None:
            """Enrich preview metadata before delegating to Comfy's sender."""

            enriched_metadata = self._enrich_metadata(metadata)
            cast_original = original
            result = cast_original(image_data, enriched_metadata, sid)
            if isawaitable(result):
                await result

        cast(Any, self._prompt_server).send_image_with_metadata = enriched_send_image_with_metadata
        setattr(self._prompt_server, _INSTALLED_FLAG, True)
        return True

    def _enrich_metadata(
        self,
        metadata: MutableMapping[str, object],
    ) -> MutableMapping[str, object]:
        """Attach Substitute identity to known prompt/node preview metadata."""

        prompt_id = _optional_string(metadata.get("prompt_id"))
        resolved = self._run_context_store.resolve_source(
            prompt_id=prompt_id,
            node_id=_optional_string(metadata.get("node_id")),
            display_node_id=_optional_string(metadata.get("display_node_id")),
            parent_node_id=_optional_string(metadata.get("parent_node_id")),
            real_node_id=_optional_string(metadata.get("real_node_id")),
        )
        if resolved is None:
            return metadata
        context, source = resolved
        metadata["substitute"] = context.substitute_payload_for_source(source)
        return metadata


def _optional_string(value: object) -> str | None:
    """Return an optional string value from Comfy metadata."""

    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    return None


__all__ = ["PreviewMetadataEnrichmentInstaller"]

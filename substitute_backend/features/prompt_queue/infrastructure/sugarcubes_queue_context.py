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
"""Capture Substitute routing context at SugarCubes' validated queue boundary."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Protocol

from substitute_backend.features.prompt_queue.application.run_context_store import (
    SubstituteRunContextStore,
)
from substitute_backend.features.prompt_queue.domain.run_context import (
    parse_substitute_run_context,
)


class ValidatedQueueEventLike(Protocol):
    """Describe the stable SugarCubes queue event surface consumed by BackEnd."""

    @property
    def prompt_id(self) -> str:
        """Return the validated host prompt identity."""

    @property
    def prompt(self) -> object:
        """Return the final executable prompt."""

    @property
    def extra_data(self) -> object:
        """Return the host queue metadata envelope."""

    @property
    def report(self) -> object | None:
        """Return the optional SugarCubes execution report."""


class SugarCubesQueueContextObserver:
    """Persist validated Substitute routing metadata before native queue insertion."""

    def __init__(self, *, run_context_store: SubstituteRunContextStore) -> None:
        """Store the authoritative process-lifetime run-context owner."""

        self._run_context_store = run_context_store

    def on_validated_queue(self, event: ValidatedQueueEventLike) -> None:
        """Capture valid Substitute context while leaving ordinary Comfy prompts alone."""

        extra_data = event.extra_data
        if not isinstance(extra_data, Mapping) or "substitute" not in extra_data:
            return
        context_payload = _context_with_report_sources(
            extra_data["substitute"],
            getattr(event, "report", None),
        )
        context = parse_substitute_run_context(context_payload)
        if context is None:
            raise ValueError("Substitute run context is malformed.")
        self._run_context_store.store(
            prompt_id=event.prompt_id,
            context=context,
            executable_prompt=event.prompt,
        )


def _context_with_report_sources(value: object, report: object) -> object:
    """Fill native node routing from SugarCubes' authoritative execution report."""

    if not isinstance(value, Mapping):
        return value
    enriched = deepcopy(dict(value))
    raw_presentations = enriched.pop("cubePresentations", None)
    presentations = raw_presentations if isinstance(raw_presentations, Mapping) else {}
    if isinstance(value.get("sources"), Mapping):
        return enriched
    identities = getattr(report, "execution_node_identities", None)
    if not isinstance(identities, tuple | list):
        identities = getattr(report, "output_identities", None)
    if not isinstance(identities, tuple | list):
        return enriched
    sources: dict[str, dict[str, str]] = {}
    for identity in identities:
        execution_id = getattr(identity, "execution_id", None)
        instance_id = getattr(identity, "instance_id", None)
        instance_alias = getattr(identity, "instance_alias", None)
        if not isinstance(execution_id, str) or not isinstance(instance_id, str):
            continue
        presentation_label = presentations.get(instance_id)
        source_label = (
            presentation_label.strip()
            if isinstance(presentation_label, str) and presentation_label.strip()
            else (
                instance_alias
                if isinstance(instance_alias, str) and instance_alias.strip()
                else instance_id
            )
        )
        sources[execution_id] = {
            "sourceKey": f"cube:{instance_id}",
            "sourceLabel": source_label,
            "cubeAlias": source_label,
        }
    enriched["sources"] = sources
    return enriched


__all__ = ["SugarCubesQueueContextObserver", "ValidatedQueueEventLike"]

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
"""Store Substitute visual routing context for active and recent prompts."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass

from substitute_backend.features.prompt_queue.domain.run_context import (
    SubstituteRunContext,
    SubstituteSourceRoute,
)


@dataclass(frozen=True, slots=True)
class StoredRunContext:
    """Describe one prompt context plus its queue-time bookkeeping."""

    prompt_id: str
    context: SubstituteRunContext
    queued_at: float
    executable_node_ids: tuple[str, ...]


class SubstituteRunContextStore:
    """Own prompt-scoped visual routing context without module-global state."""

    def __init__(
        self,
        *,
        max_contexts: int = 256,
        expiry_seconds: float = 30 * 60,
        time_source: object = time.time,
    ) -> None:
        """Initialize a bounded in-memory context store."""

        self._max_contexts = max(1, int(max_contexts))
        self._expiry_seconds = max(1.0, float(expiry_seconds))
        self._time_source = time_source
        self._contexts: dict[str, StoredRunContext] = {}

    def store(
        self,
        *,
        prompt_id: str,
        context: SubstituteRunContext,
        executable_prompt: object,
    ) -> None:
        """Store context for one queued prompt and prune stale entries."""

        self._contexts[prompt_id] = StoredRunContext(
            prompt_id=prompt_id,
            context=context,
            queued_at=self._now(),
            executable_node_ids=_executable_node_ids(executable_prompt),
        )
        self.cleanup()

    def resolve(self, prompt_id: str | None) -> SubstituteRunContext | None:
        """Return context for a prompt id when still retained."""

        if prompt_id is None:
            return None
        stored = self._contexts.get(prompt_id)
        if stored is None:
            return None
        if self._expired(stored):
            self._contexts.pop(prompt_id, None)
            return None
        return stored.context

    def resolve_source(
        self,
        *,
        prompt_id: str | None,
        node_id: str | None = None,
        display_node_id: str | None = None,
        parent_node_id: str | None = None,
        real_node_id: str | None = None,
    ) -> tuple[SubstituteRunContext, SubstituteSourceRoute] | None:
        """Resolve Substitute source identity from Comfy node metadata."""

        context = self.resolve(prompt_id)
        if context is None:
            return None
        for candidate in (node_id, display_node_id, parent_node_id, real_node_id):
            if candidate is None:
                continue
            source = context.sources.get(candidate)
            if source is not None:
                return context, source
        return None

    def cleanup(self) -> None:
        """Prune expired entries and keep the store bounded."""

        expired_prompt_ids = [
            prompt_id for prompt_id, stored in self._contexts.items() if self._expired(stored)
        ]
        for prompt_id in expired_prompt_ids:
            self._contexts.pop(prompt_id, None)
        while len(self._contexts) > self._max_contexts:
            oldest_prompt_id = min(
                self._contexts,
                key=lambda prompt_id: self._contexts[prompt_id].queued_at,
            )
            self._contexts.pop(oldest_prompt_id, None)

    def discard(self, prompt_id: str) -> None:
        """Remove one prompt context after explicit terminal cleanup."""

        self._contexts.pop(prompt_id, None)

    def _expired(self, stored: StoredRunContext) -> bool:
        """Return whether a stored context exceeded its retention window."""

        return self._now() - stored.queued_at > self._expiry_seconds

    def _now(self) -> float:
        """Return current monotonic-ish time from the configured source."""

        time_source = self._time_source
        if callable(time_source):
            return float(time_source())
        return time.time()


def _executable_node_ids(prompt: object) -> tuple[str, ...]:
    """Return node ids visible in the prompt Comfy will execute."""

    if not isinstance(prompt, Mapping):
        return ()
    return tuple(str(node_id) for node_id in prompt)


__all__ = [
    "StoredRunContext",
    "SubstituteRunContextStore",
]

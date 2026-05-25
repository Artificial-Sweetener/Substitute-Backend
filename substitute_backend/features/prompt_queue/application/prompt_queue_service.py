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
"""Application service for backend-owned prompt queueing."""

from __future__ import annotations

from substitute_backend.features.prompt_queue.domain.queue_response import QueuePromptResult
from substitute_backend.features.prompt_queue.infrastructure.comfy_prompt_queue import (
    ComfyPromptQueueAdapter,
)


class PromptQueueService:
    """Delegate prompt queue requests to the Comfy runtime adapter."""

    def __init__(self, adapter: ComfyPromptQueueAdapter) -> None:
        """Store the queue adapter."""

        self._adapter = adapter

    async def queue_prompt(self, payload: dict[str, object]) -> QueuePromptResult:
        """Queue one Comfy-compatible prompt request."""

        return await self._adapter.queue_prompt(payload)

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
"""Preview serving use case for model metadata."""

from __future__ import annotations

from dataclasses import dataclass

from substitute_backend.features.model_metadata.domain.previews import PreviewFile
from substitute_backend.features.model_metadata.infrastructure.preview_store import (
    PreviewStore,
)


@dataclass(frozen=True)
class PreviewService:
    """Resolve opaque preview IDs to validated local preview files."""

    preview_store: PreviewStore

    def resolve(self, preview_id: str) -> PreviewFile | None:
        """Resolve an opaque preview ID through the preview store."""

        return self.preview_store.resolve(preview_id)
